"""Luchen Cloud (潞晨云) adapter.

Auth:       Cookie with AccessToken (JWT, 24h validity)
Endpoints:  POST /api/instance/create|start|stop|terminate|list
Base URL:   https://cloud.luchentech.com/api
"""

from __future__ import annotations

import time

import requests

from adapters.base import CloudAdapter, GPUOffer, InstanceInfo
from config import (
    LUCHEN_BASE_URL,
    LUCHEN_USERNAME,
    LUCHEN_PASSWORD,
    LUCHEN_IMAGE_ID,
    LUCHEN_REGION_ID,
)


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _map_runtime_status(raw: str) -> str:
    """Map luchen runtime status to our unified status."""
    mapping = {
        "Running": "running",
        "Starting": "running",
        "Initializing": "pending",
        "PullingImage": "pending",
        "Restarting": "running",
        "Stopped": "stopped",
        "StartingFailed": "failed",
        "InitializationFailed": "failed",
        "Archived": "stopped",
        "Released": "stopped",
    }
    return mapping.get(raw, "pending")


class LuchenAdapter(CloudAdapter):
    @property
    def name(self) -> str:
        return "luchen"

    def __init__(self) -> None:
        self.base_url = LUCHEN_BASE_URL
        self._token: str = ""
        self._token_expires_at: float = 0
        self._username = LUCHEN_USERNAME
        self._password = LUCHEN_PASSWORD

    # ------------------------------------------------------------------ #
    #  Auth
    # ------------------------------------------------------------------ #
    def _ensure_token(self) -> None:
        """Log in and cache a JWT if it is expired or missing."""
        if self._token and time.time() < self._token_expires_at:
            return

        resp = requests.post(
            f"{self.base_url}/user/login",
            json={"username": self._username, "password": self._password},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        # token may be returned as {"token": "..."} or similar
        self._token = data.get("token") or data.get("accessToken") or ""
        if not self._token:
            raise RuntimeError(f"Luchen login succeeded but no token in response: {data}")
        # JWT valid 24 h; refresh 30 min early
        self._token_expires_at = time.time() + 23.5 * 3600

    def _headers(self) -> dict:
        self._ensure_token()
        return {"Cookie": f"AccessToken={self._token}", "Content-Type": "application/json"}

    # ------------------------------------------------------------------ #
    #  list_available_gpus
    #  Luchen does NOT expose a public "available instances" API.
    #  We combine the static GPU catalog (luchen_gpus.json) with the
    #  UUID mapping in config.  Only entries whose UUID is actually set
    #  are returned as creatable offers.
    # ------------------------------------------------------------------ #
    def list_available_gpus(self) -> list[GPUOffer]:
        from config import _LUCHEN_GPU_CATALOG, LUCHEN_GPU_TYPE_NORMALIZE, LUCHEN_INSTANCE_TYPE_IDS

        offers: list[GPUOffer] = []
        for entry in _LUCHEN_GPU_CATALOG:
            gpu_name = entry["gpu"]
            instance_type_uuid = LUCHEN_INSTANCE_TYPE_IDS.get(gpu_name, "")
            normalized_type = LUCHEN_GPU_TYPE_NORMALIZE.get(gpu_name, gpu_name)
            offers.append(GPUOffer(
                provider=self.name,
                gpu_type=gpu_name,
                gpu_count=1,
                price_per_hour=entry.get("price_per_hour_cny", 0.0),
                normalized_gpu_type=normalized_type,
                region="",
                available=bool(instance_type_uuid),  # only "available" if UUID is configured
                raw_instance_type_id=instance_type_uuid,
                raw_image_id=LUCHEN_IMAGE_ID,
                raw_region_id=LUCHEN_REGION_ID,
                raw_id=gpu_name,
            ))
        return offers

    # ------------------------------------------------------------------ #
    #  create_instance
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
        payload = {
            "name": name,
            "imageId": image_id,
            "instanceTypeId": instance_type_id,
            "region": region_id,
            "billing": {
                "chargeMode": "perHour",
                "duration": 1,
            },
            "instanceConfiguration": {
                "extraDataDiskSizeDB": 100,
                "enableCommonData": True,
                "enableDocker": True,
                "dockerStorageSize": 50,
            },
        }
        if init_script:
            payload["instanceConfiguration"]["initScript"] = init_script

        resp = requests.post(
            f"{self.base_url}/instance/create",
            json=payload,
            headers=self._headers(),
            timeout=60,
        )
        data = resp.json()
        if "message" in data and "instanceId" not in data:
            raise RuntimeError(f"Luchen create failed: {data['message']}")

        instance_id = data["instanceId"]
        return InstanceInfo(
            provider_instance_id=instance_id,
            status="pending",
        )

    # ------------------------------------------------------------------ #
    #  get_instance
    # ------------------------------------------------------------------ #
    def get_instance(self, provider_instance_id: str) -> InstanceInfo:
        # list API lets us filter by instanceId in the response
        resp = requests.post(
            f"{self.base_url}/instance/list",
            json={"pager": {"currentPage": 1, "pageSize": 10}},
            headers=self._headers(),
            timeout=15,
        )
        data = resp.json()
        target = None
        for inst in data.get("instances", []):
            meta = inst.get("instanceMetadata", {})
            if meta.get("instanceId") == provider_instance_id:
                target = inst
                break

        if target is None:
            raise RuntimeError(
                f"Instance {provider_instance_id} not found in luchen list response"
            )

        runtime = target.get("instanceRuntimeInfo", {})
        raw_status = runtime.get("status", "Unknown")
        status = _map_runtime_status(raw_status)

        info = InstanceInfo(
            provider_instance_id=provider_instance_id,
            status=status,
        )

        # Extract SSH-relevant info when running
        if status == "running":
            info.ssh_user = target.get("instanceMetadata", {}).get("instanceUsername", "root")
            # Luchen may expose IP/port in instanceSpecInfo.nodePorts or via a separate call
            spec = target.get("instanceSpecInfo", {})
            ports = spec.get("nodePorts", [])
            if ports:
                # Assume first port mapping is SSH (port 22)
                for p in ports:
                    if p.get("internal") == 22:
                        info.ssh_port = p.get("external", 22)
                        break
                else:
                    info.ssh_port = ports[0].get("external", 22)

            # External IP may need a separate API call; mark for now
            # TODO: Call /api/instance/address to get real host:port

        return info

    # ------------------------------------------------------------------ #
    #  stop_instance
    # ------------------------------------------------------------------ #
    def stop_instance(self, provider_instance_id: str) -> bool:
        resp = requests.post(
            f"{self.base_url}/instance/stop",
            json={"instanceId": provider_instance_id},
            headers=self._headers(),
            timeout=30,
        )
        data = resp.json()
        return "message" not in data

    # ------------------------------------------------------------------ #
    #  start_instance
    # ------------------------------------------------------------------ #
    def start_instance(self, provider_instance_id: str) -> bool:
        resp = requests.post(
            f"{self.base_url}/instance/start",
            json={"instanceId": provider_instance_id},
            headers=self._headers(),
            timeout=30,
        )
        data = resp.json()
        return "message" not in data

    # ------------------------------------------------------------------ #
    #  delete_instance
    # ------------------------------------------------------------------ #
    def delete_instance(self, provider_instance_id: str) -> bool:
        resp = requests.post(
            f"{self.base_url}/instance/terminate",
            json={"instanceId": provider_instance_id},
            headers=self._headers(),
            timeout=30,
        )
        data = resp.json()
        return "message" not in data
