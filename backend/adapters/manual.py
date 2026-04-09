"""AutoDL / manual adapter.

Used when the platform has no API for automation.
The user creates the instance manually in the dashboard, then imports SSH info here.
"""

from __future__ import annotations

from adapters.base import CloudAdapter, GPUOffer, InstanceInfo


class ManualActionRequired(Exception):
    """Raised when a platform requires manual user action."""
    pass


class ManualAdapter(CloudAdapter):
    @property
    def name(self) -> str:
        return "autodl"

    def list_available_gpus(self) -> list[GPUOffer]:
        # AutoDL has no listing API in this design
        return [
            GPUOffer(
                provider=self.name,
                gpu_type=gpu_type,
                gpu_count=1,
                price_per_hour=0.0,
                region="manual",
                available=True,
                raw_instance_type_id="",
                raw_image_id="",
                raw_region_id="",
                raw_id=gpu_type,
            )
            for gpu_type in ["A100", "H800", "RTX6090"]
        ]

    def create_instance(self, *args, **kwargs) -> InstanceInfo:
        raise ManualActionRequired(
            "AutoDL requires manual creation in the console. "
            "Please create the instance and then import it via POST /api/instances/import."
        )

    def import_instance(
        self,
        ssh_host: str,
        ssh_port: int,
        ssh_user: str,
        ssh_password: str,
        gpu_type: str = "",
    ) -> InstanceInfo:
        """Register a manually-created instance with its SSH info."""
        return InstanceInfo(
            provider_instance_id=f"manual_{ssh_host}_{ssh_port}",
            status="bootstrapping",  # will trigger bootstrap push via SSH
            ssh_host=ssh_host,
            ssh_port=ssh_port,
            ssh_user=ssh_user,
            ssh_password=ssh_password,
        )

    def get_instance(self, provider_instance_id: str) -> InstanceInfo:
        # For manual instances, status is tracked in our own DB
        return InstanceInfo(
            provider_instance_id=provider_instance_id,
            status="running",
        )

    def stop_instance(self, provider_instance_id: str) -> bool:
        # Can only signal in our DB; actual stop requires console
        return True

    def start_instance(self, provider_instance_id: str) -> bool:
        return True

    def delete_instance(self, provider_instance_id: str) -> bool:
        return True
