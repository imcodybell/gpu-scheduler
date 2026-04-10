"""PPIO (派欧云) adapter – real implementation.

Authentication: Bearer API key (long‑lived) set in ``config.PPIO_API_KEY``.
All requests include ``Authorization: Bearer <key>``.
Endpoints are taken from the official PPIO documentation:
- List GPU products                : GET   /products
- Create GPU instance              : POST  /gpu/instance/create
- List instances (filter by ID)    : GET   /gpu/instances
- Get instance details             : GET   /gpu/instance
- Edit instance (e.g. set init script) : POST /gpu/instance/edit
- Start instance                    : POST  /gpu/instance/start
- Stop instance                     : POST  /gpu/instance/stop
- Restart instance                  : POST  /gpu/instance/restart
- Delete instance                   : POST /gpu/instance/delete

The adapter converts the JSON responses into the unified ``GPUOffer`` and
``InstanceInfo`` dataclasses defined in ``adapters.base``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

import requests

from adapters.base import CloudAdapter, GPUOffer, InstanceInfo
from config import PPIO_API_KEY, PPIO_BASE_URL

logger = logging.getLogger(__name__)


class PPIOAdapter(CloudAdapter):
    @property
    def name(self) -> str:
        return "ppio"

    def __init__(self) -> None:
        self.base_url = PPIO_BASE_URL.rstrip('/')
        self.api_key = PPIO_API_KEY

    # ------------------------------------------------------------------ #
    # Helper – common request headers
    # ------------------------------------------------------------------ #
    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    # ------------------------------------------------------------------ #
    # GPU product list – maps to our unified ``GPUOffer`` model
    # ------------------------------------------------------------------ #
    def list_available_gpus(self) -> list[GPUOffer]:
        url = f"{self.base_url}/products"
        try:
            resp = requests.get(url, headers=self._headers(), timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.exception("PPIO list_available_gpus failed")
            raise RuntimeError(f"Failed to fetch GPU products from PPIO: {exc}")

        offers: list[GPUOffer] = []
        # Expected structure (example):
        # [{"id": "gpu-123", "name": "A100", "memory": 80, "price_per_hour": 5.5, "region": "us-west"}, ...]
        for prod in data.get("products", []):
            gpu_type = prod.get("name", "")
            # Normalized type – for now we keep the same string; callers may map further.
            normalized = gpu_type
            offers.append(
                GPUOffer(
                    provider=self.name,
                    gpu_type=gpu_type,
                    normalized_gpu_type=normalized,
                    gpu_count=1,
                    price_per_hour=float(prod.get("price_per_hour", 0.0)),
                    region=prod.get("region", ""),
                    available=True,
                    raw_instance_type_id=prod.get("id", ""),
                    raw_image_id="",
                    raw_region_id=prod.get("region_id", ""),
                )
            )
        return offers

    # ------------------------------------------------------------------ #
    # Instance lifecycle operations – all return ``InstanceInfo`` or bool
    # ------------------------------------------------------------------ #
    def create_instance(
        self,
        name: str,
        instance_type_id: str,
        image_id: str,
        region_id: str,
        init_script: str = "",
        gpu_type: str = "",
    ) -> InstanceInfo:
        """Create a GPU instance.

        The request payload follows the PPIO ``/instances`` POST schema:
        {
            "name": <str>,
            "gpu_product_id": <instance_type_id>,
            "image_id": <image_id>,
            "region_id": <region_id>,
            "init_script": <script> (optional)
        }
        """
        url = f"{self.base_url}/gpu/instance/create"
        payload: Dict[str, Any] = {
            "name": name,
            "gpu_product_id": instance_type_id,
            "image_id": image_id,
            "region_id": region_id,
        }
        if init_script:
            payload["init_script"] = init_script
        try:
            resp = requests.post(url, headers=self._headers(), json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.exception("PPIO create_instance failed")
            raise RuntimeError(f"PPIO instance creation error: {exc}")

        provider_id = data.get("instance_id") or data.get("id")
        if not provider_id:
            raise RuntimeError(f"PPIO create_instance did not return an instance ID: {data}")

        # At creation the instance is usually in a pending state.
        return InstanceInfo(provider_instance_id=str(provider_id), status="pending")

    def _instance_url(self, provider_instance_id: str) -> str:
        return f"{self.base_url}/gpu/instance/{provider_instance_id}"

    def get_instance(self, provider_instance_id: str) -> InstanceInfo:
        # Official endpoint: GET /gpu/instance?instanceId=xxx
        url = f"{self.base_url}/gpu/instance"
        params = {"instanceId": provider_instance_id}
        try:
            resp = requests.get(url, headers=self._headers(), params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.exception("PPIO get_instance failed")
            raise RuntimeError(f"Failed to retrieve PPIO instance {provider_instance_id}: {exc}")
        # Expected fields (example):
        # {"status": "running", "ssh": {"host": "1.2.3.4", "port": 22, "user": "root"}}
        status_map = {
            "running": "running",
            "starting": "pending",
            "stopped": "stopped",
            "failed": "failed",
        }
        raw_status = data.get("status", "unknown").lower()
        status = status_map.get(raw_status, "pending")

        info = InstanceInfo(provider_instance_id=provider_instance_id, status=status)
        ssh_info = data.get("ssh", {})
        if ssh_info:
            info.ssh_host = ssh_info.get("host")
            info.ssh_port = int(ssh_info.get("port", 22))
            info.ssh_user = ssh_info.get("user", "root")
        return info

    def _post_action(self, provider_instance_id: str, action: str) -> bool:
        """Utility to POST an action endpoint (start/stop/restart/restart/delete)."""
        # All action endpoints expect a JSON body with the instanceId.
        url = f"{self.base_url}/gpu/instance/{action}"
        payload = {"instanceId": provider_instance_id}
        try:
            resp = requests.post(url, headers=self._headers(), json=payload, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            # Successful response typically contains a ``message`` field.
            return "message" not in data or "success" in data.get("message", "").lower()
        except Exception as exc:
            logger.exception(f"PPIO {action} failed for {provider_instance_id}")
            raise RuntimeError(f"PPIO {action} error for {provider_instance_id}: {exc}")

    def start_instance(self, provider_instance_id: str) -> bool:
        return self._post_action(provider_instance_id, "start")

    def stop_instance(self, provider_instance_id: str) -> bool:
        return self._post_action(provider_instance_id, "stop")

    def delete_instance(self, provider_instance_id: str) -> bool:
        return self._post_action(provider_instance_id, "delete")


    # ------------------------------------------------------------------ #
    # Edit instance – used for adding/modifying the init script after creation.
    # ------------------------------------------------------------------ #
    def edit_instance(self, provider_instance_id: str, init_script: str) -> bool:
        """Patch an existing instance with a new ``init_script``.

        PPIO supports a PATCH request on ``/instances/{id}`` where the body can
        include ``init_script``.  The method returns ``True`` on success.
        """
        url = self._instance_url(provider_instance_id)
        payload = {"init_script": init_script}
        try:
            resp = requests.patch(url, headers=self._headers(), json=payload, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            return "message" not in data or "updated" in data.get("message", "").lower()
        except Exception as exc:
            logger.exception(f"PPIO edit_instance failed for {provider_instance_id}")
            raise RuntimeError(f"PPIO edit_instance error for {provider_instance_id}: {exc}")

    # ------------------------------------------------------------------ #
    # Restart – convenience wrapper that calls the restart endpoint.
    # ------------------------------------------------------------------ #
    def restart_instance(self, provider_instance_id: str) -> bool:
        return self._post_action(provider_instance_id, "restart")

    # ------------------------------------------------------------------ #
    # The abstract base class does not define ``edit_instance`` or ``restart_instance``
    # but the scheduler or higher‑level code may call them via ``hasattr`` checks.
    # ------------------------------------------------------------------ #
