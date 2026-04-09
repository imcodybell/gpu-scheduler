from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class GPUOffer:
    provider: str
    gpu_type: str                   # provider-specific name (e.g. "A100-SXM")
    gpu_count: int
    price_per_hour: float
    region: str
    normalized_gpu_type: str = ""   # canonical type (e.g. "A100") for cross-vendor queries
    available: bool = True
    raw_instance_type_id: str = ""
    raw_image_id: str = ""
    raw_region_id: str = ""
    raw_id: str = ""

    @property
    def id(self) -> str:
        return f"{self.provider}_{self.raw_id}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "provider": self.provider,
            "gpu_type": self.gpu_type,
            "normalized_gpu_type": self.normalized_gpu_type,
            "gpu_count": self.gpu_count,
            "price_per_hour": self.price_per_hour,
            "region": self.region,
            "available": self.available,
            "raw_instance_type_id": self.raw_instance_type_id,
            "raw_image_id": self.raw_image_id,
            "raw_region_id": self.raw_region_id,
        }


@dataclass
class InstanceInfo:
    provider_instance_id: str = ""
    status: str = "pending"  # pending | running | stopped | failed
    ssh_host: str = ""
    ssh_port: int = 22
    ssh_user: str = ""
    ssh_password: str = ""

    def to_dict(self) -> dict:
        return {
            "provider_instance_id": self.provider_instance_id,
            "status": self.status,
            "ssh_host": self.ssh_host,
            "ssh_port": self.ssh_port,
            "ssh_user": self.ssh_user,
            "ssh_password": self.ssh_password,
        }


class CloudAdapter(ABC):
    """Unified interface for different cloud GPU providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def list_available_gpus(self) -> list[GPUOffer]:
        """Return a list of currently available GPU offerings."""
        ...

    @abstractmethod
    def create_instance(
        self,
        name: str,
        instance_type_id: str,
        image_id: str,
        region_id: str,
        init_script: str = "",
        gpu_type: str = "",
    ) -> InstanceInfo:
        """Provision a GPU instance and return connection info."""
        ...

    @abstractmethod
    def get_instance(self, provider_instance_id: str) -> InstanceInfo:
        """Query the current status of a running instance."""
        ...

    @abstractmethod
    def stop_instance(self, provider_instance_id: str) -> bool:
        """Stop (not delete) an instance. Returns True on success."""
        ...

    @abstractmethod
    def start_instance(self, provider_instance_id: str) -> bool:
        """Start a stopped instance. Returns True on success."""
        ...

    @abstractmethod
    def delete_instance(self, provider_instance_id: str) -> bool:
        """Terminate and delete an instance. Returns True on success."""
        ...
