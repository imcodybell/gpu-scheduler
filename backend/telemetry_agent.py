#!/usr/bin/env python3
"""Telemetry Agent - runs inside the provisioned instance.

Collects GPU metrics every 10 seconds and POSTs them to the backend.
Launched by bootstrap.sh Phase 6 as a nohup background process.
"""

from __future__ import annotations
import argparse
import json
import subprocess
import sys
import time
import urllib.request


def collect_gpu_metrics() -> dict:
    """Parse nvidia-smi output into a metrics dict."""
    query = (
        "utilization.gpu,"
        "memory.used,"
        "memory.total,"
        "temperature.gpu"
    )
    result = subprocess.run(
        [
            "nvidia-smi",
            f"--query-gpu={query}",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True, text=True, timeout=10,
    )
    parts = result.stdout.strip().split(",")
    if len(parts) < 4:
        return {}
    return {
        "gpu_util_pct": float(parts[0].strip()),
        "gpu_mem_used_mb": float(parts[1].strip()),
        "gpu_mem_total_mb": float(parts[2].strip()),
        "gpu_temp_c": float(parts[3].strip()),
    }


def report(metrics: dict, instance_id: str, callback_url: str) -> None:
    payload = json.dumps({
        "instance_id": instance_id,
        "timestamp": time.time(),
        **metrics,
    }).encode()
    req = urllib.request.Request(
        f"{callback_url}/api/telemetry",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            pass
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--callback-url", default="http://localhost:9898")
    parser.add_argument("--interval", type=int, default=10)
    args = parser.parse_args()

    while True:
        metrics = collect_gpu_metrics()
        if metrics:
            report(metrics, args.instance_id, args.callback_url)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
