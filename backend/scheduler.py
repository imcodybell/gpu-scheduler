"""Scheduler: syncs GPU offerings from all providers and selects the cheapest one.

Also runs a background polling task for pending/bootstrapping instances.
"""

from __future__ import annotations

import threading
import time
import logging
import uuid

from adapters.base import CloudAdapter
from adapters.luchen import LuchenAdapter
from adapters.ppio import PPIOAdapter
# from adapters.manual import ManualAdapter
from config import (
    SCHEDULER_SYNC_INTERVAL_SECONDS,
    INSTANCE_POLL_INTERVAL_SECONDS,
    CALLBACK_BASE_URL,
)
from database import get_db

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self) -> None:
        self.adapters: list[CloudAdapter] = [
            LuchenAdapter(),
            PPIOAdapter(),   # uncomment after registration
            # ManualAdapter(),
        ]
        self._adapter_map: dict[str, CloudAdapter] = {
            a.name: a for a in self.adapters
        }
        self._sync_stop = threading.Event()
        self._poll_stop = threading.Event()
        self._sync_thread: threading.Thread | None = None
        self._poll_thread: threading.Thread | None = None

    # ------------------------------------------------------------------ #
    #  Public helpers (used by routers)
    # ------------------------------------------------------------------ #

    def get_adapter(self, provider: str) -> CloudAdapter:
        if provider in self._adapter_map:
            return self._adapter_map[provider]
        raise ValueError(f"Unknown provider: {provider}")

    def select_cheapest_offer(
        self, gpu_type: str, gpu_count: int = 1
    ) -> dict | None:
        """Return the cheapest available offer for the given canonical GPU type.

        Matches against `normalized_gpu_type` so that different providers'
        variants (e.g. "A100-SXM" vs "A100-PCIE") are aggregated under "A100".
        Also falls back to raw `gpu_type` for backward compatibility.
        """
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM gpu_offers "
                "WHERE (normalized_gpu_type = ? OR gpu_type = ?) AND available = 1 "
                "ORDER BY price_per_hour ASC",
                (gpu_type, gpu_type),
            ).fetchall()
        if not rows:
            return None
        return dict(rows[0])

    # ------------------------------------------------------------------ #
    #  Background: sync GPU offerings from all providers
    # ------------------------------------------------------------------ #

    def _sync_loop(self) -> None:
        """Periodic loop: upsert gpu_offers from every adapter."""
        while not self._sync_stop.is_set():
            for adapter in self.adapters:
                try:
                    offers = adapter.list_available_gpus()
                    with get_db() as conn:
                        for o in offers:
                            d = o.to_dict()
                            conn.execute(
                                """INSERT INTO gpu_offers (
                                    id, provider, gpu_type, normalized_gpu_type, gpu_count,
                                    price_per_hour, region, available,
                                    raw_instance_type_id, raw_image_id,
                                    raw_region_id, updated_at
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                                ON CONFLICT(id) DO UPDATE SET
                                    provider=excluded.provider,
                                    gpu_type=excluded.gpu_type,
                                    normalized_gpu_type=excluded.normalized_gpu_type,
                                    gpu_count=excluded.gpu_count,
                                    price_per_hour=excluded.price_per_hour,
                                    region=excluded.region,
                                    available=excluded.available,
                                    raw_instance_type_id=excluded.raw_instance_type_id,
                                    raw_image_id=excluded.raw_image_id,
                                    raw_region_id=excluded.raw_region_id,
                                    updated_at=datetime('now')
                                """,
                                (
                                    d["id"], d["provider"], d["gpu_type"],
                                    d["normalized_gpu_type"],
                                    d["gpu_count"], d["price_per_hour"],
                                    d["region"], d["available"],
                                    d["raw_instance_type_id"],
                                    d["raw_image_id"],
                                    d["raw_region_id"],
                                ),
                            )
                    logger.info(
                        "%s: synced %d offers", adapter.name, len(offers)
                    )
                except Exception:
                    logger.exception("%s: sync failed", adapter.name)

            self._sync_stop.wait(SCHEDULER_SYNC_INTERVAL_SECONDS)

    # ------------------------------------------------------------------ #
    #  Background: poll instance status
    # ------------------------------------------------------------------ #

    def _poll_loop(self) -> None:
        """Poll pending/bootstrapping instances and update their status."""
        while not self._poll_stop.is_set():
            try:
                with get_db() as conn:
                    pending = conn.execute(
                        "SELECT id, provider, provider_instance_id, status "
                        "FROM instances "
                        "WHERE status IN ('pending', 'bootstrapping')"
                    ).fetchall()

                for row in pending:
                    inst_id = row["id"]
                    provider = row["provider"]
                    prov_inst_id = row["provider_instance_id"]
                    current_status = row["status"]

                    if not prov_inst_id or prov_inst_id.startswith("manual_"):
                        # Manual instances skip adapter polling
                        continue

                    try:
                        adapter = self.get_adapter(provider)
                        info = adapter.get_instance(prov_inst_id)

                        with get_db() as conn:
                            if info.status == "running" and current_status == "pending":
                                conn.execute(
                                    "UPDATE instances SET status = 'bootstrapping', "
                                    "ssh_host = ?, ssh_port = ?, ssh_user = ? "
                                    "WHERE id = ?",
                                    (info.ssh_host, info.ssh_port, info.ssh_user, inst_id),
                                )
                                logger.info(
                                    "%s transitioned pending -> bootstrapping", inst_id
                                )
                    except Exception:
                        logger.exception("Failed to poll instance %s on %s", prov_inst_id, provider)

            except Exception:
                logger.exception("Poll loop error")

            self._poll_stop.wait(INSTANCE_POLL_INTERVAL_SECONDS)

    # ------------------------------------------------------------------ #
    #  Start / Stop
    # ------------------------------------------------------------------ #

    def start_background_tasks(self) -> None:
        self._sync_stop.clear()
        self._poll_stop.clear()
        self._sync_thread = threading.Thread(
            target=self._sync_loop, daemon=True, name="gpu-sync"
        )
        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="instance-poll"
        )
        self._sync_thread.start()
        self._poll_thread.start()
        logger.info("Scheduler background tasks started")


# Global singleton — imported by main.py and routers.
scheduler = Scheduler()
