from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_db

router = APIRouter(tags=["telemetry_and_callback"])


class CallbackBody(BaseModel):
    instance_id: str
    status: str
    benchmark: dict | None = None


class TelemetryBody(BaseModel):
    instance_id: str
    timestamp: float
    gpu_util_pct: float | None = None
    gpu_mem_used_mb: float | None = None
    gpu_mem_total_mb: float | None = None
    gpu_temp_c: float | None = None


# ------------------------------------------------------------------ #
#  Bootstrap callback
# ------------------------------------------------------------------ #
@router.post("/api/callback")
def bootstrap_callback(body: CallbackBody):
    """Called by bootstrap.sh when setup is complete."""
    benchmark_json = json.dumps(body.benchmark) if body.benchmark else None

    with get_db() as conn:
        conn.execute(
            "UPDATE instances SET status = ?, benchmark_result = ?, "
            "ready_at = datetime('now') WHERE id = ?",
            (body.status, benchmark_json, body.instance_id),
        )
    return {"ok": True}


# ------------------------------------------------------------------ #
#  Telemetry ingest
# ------------------------------------------------------------------ #
@router.post("/api/telemetry")
def ingest_telemetry(body: TelemetryBody):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO telemetry (
                instance_id, timestamp, gpu_util_pct,
                gpu_mem_used_mb, gpu_mem_total_mb, gpu_temp_c
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                body.instance_id,
                body.timestamp,
                body.gpu_util_pct,
                body.gpu_mem_used_mb,
                body.gpu_mem_total_mb,
                body.gpu_temp_c,
            ),
        )
    return {"ok": True}


@router.get("/api/telemetry/{instance_id}/latest")
def latest_telemetry(instance_id: str, limit: int = 60):
    """Return the most recent telemetry records for an instance."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM telemetry WHERE instance_id = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (instance_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------ #
#  Performance reports (for frontend dashboard)
# ------------------------------------------------------------------ #

@router.get("/api/reports/benchmark/{instance_id}")
def get_benchmark(instance_id: str):
    """Get benchmark results for a specific instance."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, provider, gpu_type, benchmark_result, ready_at "
            "FROM instances WHERE id = ?",
            (instance_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Instance not found")
    result = {
        "instance_id": row["id"],
        "provider": row["provider"],
        "gpu_type": row["gpu_type"],
        "ready_at": row["ready_at"],
        "benchmark": json.loads(row["benchmark_result"]) if row["benchmark_result"] else None,
    }
    return result


@router.get("/api/reports/benchmark")
def list_benchmarks():
    """List benchmark results for all ready instances, ordered by price performance."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT i.id, i.provider, i.gpu_type, i.benchmark_result, i.ready_at, "
            "g.price_per_hour "
            "FROM instances i "
            "LEFT JOIN gpu_offers g ON g.normalized_gpu_type = i.gpu_type AND g.provider = i.provider "
            "WHERE i.status = 'ready' AND i.benchmark_result IS NOT NULL "
            "ORDER BY i.ready_at DESC",
        ).fetchall()

    results = []
    for row in rows:
        bm = json.loads(row["benchmark_result"]) if row["benchmark_result"] else {}
        price = row["price_per_hour"] or 0
        results.append({
            "instance_id": row["id"],
            "provider": row["provider"],
            "gpu_type": row["gpu_type"],
            "price_per_hour": price,
            "ready_at": row["ready_at"],
            "benchmark": bm,
        })
    return results


@router.get("/api/reports/performance/{instance_id}")
def get_performance_report(instance_id: str, limit: int = 1000):
    """Get a full performance report for an instance with chart-ready time-series data."""
    with get_db() as conn:
        inst = conn.execute(
            "SELECT * FROM instances WHERE id = ?",
            (instance_id,),
        ).fetchone()
    if not inst:
        raise HTTPException(status_code=404, detail="Instance not found")

    benchmark = json.loads(inst["benchmark_result"]) if inst["benchmark_result"] else None

    with get_db() as conn:
        rows = conn.execute(
            "SELECT timestamp, gpu_util_pct, gpu_mem_used_mb, gpu_mem_total_mb, gpu_temp_c "
            "FROM telemetry WHERE instance_id = ? "
            "ORDER BY timestamp ASC LIMIT ?",
            (instance_id, limit),
        ).fetchall()

    telemetry_series = [dict(r) for r in rows]

    # Compute summary statistics
    if telemetry_series:
        utils = [r["gpu_util_pct"] for r in telemetry_series if r["gpu_util_pct"] is not None]
        temps = [r["gpu_temp_c"] for r in telemetry_series if r["gpu_temp_c"] is not None]
        mem_used = [r["gpu_mem_used_mb"] for r in telemetry_series if r["gpu_mem_used_mb"] is not None]
        summary = {
            "avg_gpu_util": round(sum(utils) / len(utils), 1) if utils else None,
            "max_gpu_util": round(max(utils), 1) if utils else None,
            "min_gpu_util": round(min(utils), 1) if utils else None,
            "avg_temp": round(sum(temps) / len(temps), 1) if temps else None,
            "max_temp": round(max(temps), 1) if temps else None,
            "avg_mem_used_mb": round(sum(mem_used) / len(mem_used), 1) if mem_used else None,
            "data_points": len(telemetry_series),
        }
    else:
        summary = {"data_points": 0}

    return {
        "instance_id": inst["id"],
        "provider": inst["provider"],
        "gpu_type": inst["gpu_type"],
        "status": inst["status"],
        "created_at": inst["created_at"],
        "ready_at": inst["ready_at"],
        "benchmark": benchmark,
        "summary": summary,
        "telemetry_series": telemetry_series,
    }


@router.get("/api/reports/performance")
def aggregate_performance_report():
    """Aggregate performance summary across all ready instances."""
    with get_db() as conn:
        instances = conn.execute(
            "SELECT id, provider, gpu_type, benchmark_result FROM instances "
            "WHERE status = 'ready'",
        ).fetchall()

    result = {
        "total_instances": len(instances),
        "gpu_types": {},
        "benchmark_summary": {
            "avg_disk_read_MBs": [],
            "avg_disk_write_MBs": [],
            "avg_net_download_Mbps": [],
            "avg_gpu_mem_bw_GBps": [],
        },
    }

    gpu_type_counts = {}
    for inst in instances:
        gpu = inst["gpu_type"]
        gpu_type_counts[gpu] = gpu_type_counts.get(gpu, 0) + 1

        bm = json.loads(inst["benchmark_result"]) if inst["benchmark_result"] else {}
        if bm:
            if bm.get("disk_read_MBs") is not None:
                result["benchmark_summary"]["avg_disk_read_MBs"].append(bm["disk_read_MBs"])
            if bm.get("disk_write_MBs") is not None:
                result["benchmark_summary"]["avg_disk_write_MBs"].append(bm["disk_write_MBs"])
            if bm.get("net_download_Mbps") is not None:
                result["benchmark_summary"]["avg_net_download_Mbps"].append(bm["net_download_Mbps"])
            if bm.get("gpu_mem_bw_GBps") is not None:
                result["benchmark_summary"]["avg_gpu_mem_bw_GBps"].append(bm["gpu_mem_bw_GBps"])

    # Compute averages
    for key in result["benchmark_summary"]:
        vals = result["benchmark_summary"][key]
        result["benchmark_summary"][key] = round(sum(vals) / len(vals), 1) if vals else None

    result["gpu_types"] = gpu_type_counts
    return result


@router.get("/api/reports/dashboard")
def dashboard_summary():
    """Top-level dashboard summary - key metrics for the frontend landing page."""
    with get_db() as conn:
        stats = conn.execute(
            "SELECT COUNT(*) as total, "
            "SUM(CASE WHEN status='ready' THEN 1 ELSE 0 END) as ready, "
            "SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) as pending, "
            "SUM(CASE WHEN status='bootstrapping' THEN 1 ELSE 0 END) as bootstrapping, "
            "SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed, "
            "SUM(CASE WHEN status='stopped' THEN 1 ELSE 0 END) as stopped "
            "FROM instances",
        ).fetchone()

        gpu_offers = conn.execute(
            "SELECT provider, normalized_gpu_type, COUNT(*) as cnt, "
            "MIN(price_per_hour) as min_price, MAX(price_per_hour) as max_price "
            "FROM gpu_offers WHERE available = 1 "
            "GROUP BY provider, normalized_gpu_type",
        ).fetchall()

        # Recent ready instances with benchmark highlights
        recent = conn.execute(
            "SELECT id, provider, gpu_type, ready_at, benchmark_result "
            "FROM instances WHERE status = 'ready' AND benchmark_result IS NOT NULL "
            "ORDER BY ready_at DESC LIMIT 5",
        ).fetchall()

    return {
        "instance_stats": dict(stats),
        "available_offers": [
            {
                "provider": r["provider"],
                "gpu_type": r["normalized_gpu_type"],
                "count": r["cnt"],
                "min_price": r["min_price"],
                "max_price": r["max_price"],
            }
            for r in gpu_offers
        ],
        "recent_instances": [
            {
                "id": r["id"],
                "provider": r["provider"],
                "gpu_type": r["gpu_type"],
                "ready_at": r["ready_at"],
                "benchmark": json.loads(r["benchmark_result"]),
            }
            for r in recent
        ],
    }
