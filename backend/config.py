import json
import os

# ---- Luchen Cloud ----
LUCHEN_BASE_URL = "https://cloud.luchentech.com/api"
LUCHEN_USERNAME = os.getenv("LUCHEN_USERNAME", "")
LUCHEN_PASSWORD = os.getenv("LUCHEN_PASSWORD", "")
# Pre-configured resource IDs (UUID format) obtained from Luchen dashboard
LUCHEN_IMAGE_ID = os.getenv("LUCHEN_IMAGE_ID", "")       # e.g. Ubuntu + CUDA base image
LUCHEN_REGION_ID = os.getenv("LUCHEN_REGION_ID", "")     # e.g. CN-East

# GPU catalog with prices (from luchen_gpus.json)
_LUCHEN_GPU_CATALOG_PATH = os.path.join(os.path.dirname(__file__), "adapters", "luchen_gpus.json")
_LUCHEN_GPU_CATALOG: list[dict] = []
if os.path.exists(_LUCHEN_GPU_CATALOG_PATH):
    with open(_LUCHEN_GPU_CATALOG_PATH) as _f:
        _LUCHEN_GPU_CATALOG = json.load(_f)

# Instance type UUID mapping — MUST be filled from browser DevTools
# Key = gpu label matching luchen_gpus.json "gpu" field
# Value = instanceTypeId UUID from the Luchen create-instance API call
LUCHEN_INSTANCE_TYPE_IDS: dict[str, str] = {
    # Example (replace with real UUIDs):
    "RTX-4090D":  "c2a5f1a4-7d3b-4d4e-9e2b-3c8a1f6b2e91-...",
    "A100-PCIE":  "8f0c2e19-6a44-4c1d-91d8-5a3e7b2c4f60-...",
    "A100-SXM":   "1d9b7c3e-5a2f-4e88-8c0a-6f4b1d2e9a73-...",
    "H800-PCIE":  "b7e3a2c1-9d4f-4b65-a8c3-2f1e7d9a0b54-...",
    "H800-SXM":   "3c6f1a9d-2e8b-4d7a-b5c1-9e0a4f2d7b63-...",
    "H100-SXM":   "a1d4c7e9-3b2f-4a68-9c5e-7f0d2b1a8c34-...",
    "H200-PCIE":  "5e2b9c1a-8d4f-4f6a-92c3-1a7e0d3b6f85-...",
    "RTX-3090":   "9a3f6d2b-1c8e-4b7a-a5d4-6c0f2e9b3a71-...",
    "RTX-4090":   "4b1e8c3a-7d2f-4a69-8c5b-0e9d6f2a1c87-...",
}

# Backward compat: build {gpu_name -> instance_type_uuid} dict
def _build_instance_types() -> dict[str, str]:
    return {gpu: LUCHEN_INSTANCE_TYPE_IDS.get(gpu, "") for gpu in [g["gpu"] for g in _LUCHEN_GPU_CATALOG]}

LUCHEN_INSTANCE_TYPES: dict[str, str] = _build_instance_types()

# GPU model normalization — maps provider-specific names to canonical types.
# This enables multi-vendor aggregation: e.g. luchen "A100-SXM" and ppio
# "A100-SXM-80G" both normalize to "A100", so the user just requests "A100".
LUCHEN_GPU_TYPE_NORMALIZE: dict[str, str] = {
    "RTX-3090":   "RTX3090",
    "RTX-4090":   "RTX4090",
    "RTX-4090D":  "RTX4090D",
    "A100-PCIE":  "A100",
    "A100-SXM":   "A100",
    "H800-PCIE":  "H800",
    "H800-SXM":   "H800",
    "H100-SXM":   "H100",
    "H200-PCIE":  "H200",
}

# ---- PPIO ----
PPIO_BASE_URL = os.getenv("PPIO_BASE_URL", "https://api.ppinfra.com/v3")
PPIO_API_KEY = os.getenv("PPIO_API_KEY", "")

# ---- Scheduler ----
SCHEDULER_SYNC_INTERVAL_SECONDS = int(os.getenv("SCHEDULER_SYNC_INTERVAL", "300"))
INSTANCE_POLL_INTERVAL_SECONDS = int(os.getenv("INSTANCE_POLL_INTERVAL", "15"))

# ---- Callback ----
# Base URL the instance uses to reach back (e.g. ngrok URL)
CALLBACK_BASE_URL = os.getenv("CALLBACK_BASE_URL", "http://localhost:9898")

# ---- Database ----
DB_PATH = os.getenv("DB_PATH", "gpu_scheduler.db")
