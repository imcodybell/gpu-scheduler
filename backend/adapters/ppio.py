"""PPIO (派欧云) adapter - STUB.

Auth:       Bearer API Key (long-lived)
Endpoints:  To be determined after PPIO account registration.
"""

from __future__ import annotations

from adapters.base import CloudAdapter, GPUOffer, InstanceInfo
from config import PPIO_API_KEY, PPIO_BASE_URL


class PPIOAdapter(CloudAdapter):
    @property
    def name(self) -> str:
        return "ppio"

    def __init__(self) -> None:
        self.base_url = PPIO_BASE_URL
        self.api_key = PPIO_API_KEY

    def list_available_gpus(self) -> list[GPUOffer]:
        # TODO: Implement after API exploration
        return []

    def create_instance(
        self,
        name: str,
        instance_type_id: str,
        image_id: str,
        region_id: str,
        init_script: str = "",
        gpu_type: str = "",
    ) -> InstanceInfo:
        raise NotImplementedError("PPIO adapter not yet implemented - register account first")

    def get_instance(self, provider_instance_id: str) -> InstanceInfo:
        raise NotImplementedError("PPIO adapter not yet implemented")

    def stop_instance(self, provider_instance_id: str) -> bool:
        raise NotImplementedError("PPIO adapter not yet implemented")

    def start_instance(self, provider_instance_id: str) -> bool:
        raise NotImplementedError("PPIO adapter not yet implemented")

    def delete_instance(self, provider_instance_id: str) -> bool:
        raise NotImplementedError("PPIO adapter not yet implemented")
