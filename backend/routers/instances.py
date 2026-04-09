import uuid
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_db
from scheduler import scheduler
from adapters.manual import ManualActionRequired
from config import CALLBACK_BASE_URL

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/instances", tags=["instances"])

# NOTE: /import MUST be registered before /{instance_id} to avoid FastAPI
# matching "import" as an instance_id path param.


class CreateInstanceReq(BaseModel):
    gpu_type: str
    gpu_count: int = 1
    name: str = ""


class ImportInstanceReq(BaseModel):
    ssh_host: str
    ssh_port: int = 22
    ssh_user: str = "root"
    ssh_password: str
    gpu_type: str


@router.post("")
def create_instance(req: CreateInstanceReq):
    """Schedule selection → cheapest provider → create instance → return id."""
    # 1. Select cheapest offer from DB
    offer = scheduler.select_cheapest_offer(req.gpu_type, req.gpu_count)
    if offer is None:
        raise HTTPException(
            status_code=400,
            detail=f"No available offer for {req.gpu_type} x{req.gpu_count}",
        )

    provider = offer["provider"]
    adapter = scheduler.get_adapter(provider)

    instance_id = str(uuid.uuid4())
    instance_name = req.name or instance_id[:8]

    # 2. Build bootstrap script injection
    #    通过读取shell脚本的方式比较好
    bootstrap_script = (
        f'#!/bin/bash\n'
        f'export INSTANCE_ID="{instance_id}"\n'
        f'export CALLBACK_URL="{CALLBACK_BASE_URL}/api/callback"\n'
    )

    try:
        info = adapter.create_instance(
            name=instance_name,
            instance_type_id=offer["raw_instance_type_id"],
            image_id=offer.get("raw_image_id", ""),
            region_id=offer.get("raw_region_id", ""),
            init_script=bootstrap_script,
            gpu_type=req.gpu_type,
        )
    except ManualActionRequired:
        # Return instructions for manual creation
        return {
            "instance_id": instance_id,
            "status": "manual_action_required",
            "provider": provider,
            "message": f"Please create a {req.gpu_type} instance on {provider} console "
                       f"and import it via POST /api/instances/import",
        }
    except Exception as e:
        logger.exception("Failed to create instance on %s", provider)
        raise HTTPException(status_code=502, detail=str(e))

    # 3. Persist to DB
    with get_db() as conn:
        conn.execute(
            """INSERT INTO instances (
                id, provider_instance_id, provider, status,
                gpu_type, created_at
            ) VALUES (?, ?, ?, 'pending', ?, datetime('now'))""",
            (
                instance_id,
                info.provider_instance_id,
                provider,
                req.gpu_type,
            ),
        )

    return {
        "instance_id": instance_id,
        "provider_instance_id": info.provider_instance_id,
        "provider": provider,
        "status": "pending",
    }


@router.post("/import")
def import_instance(req: ImportInstanceReq):
    """Register a manually-created instance (for providers like AutoDL)."""
    inst_id = str(uuid.uuid4())
    with get_db() as conn:
        conn.execute(
            """INSERT INTO instances (
                id, provider, status, gpu_type,
                ssh_host, ssh_port, ssh_user, ssh_password,
                created_at
            ) VALUES (?, 'autodl', 'pending', ?, ?, ?, ?, ?, datetime('now'))""",
            (
                inst_id,
                req.gpu_type,
                req.ssh_host,
                req.ssh_port,
                req.ssh_user,
                req.ssh_password,
            ),
        )

    return {
        "instance_id": inst_id,
        "provider": "autodl",
        "status": "pending",
        "ssh_host": req.ssh_host,
        "ssh_port": req.ssh_port,
    }


@router.get("")
def list_instances():
    """Return all instances."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, provider_instance_id, provider, status, gpu_type, "
            "created_at, ready_at FROM instances ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/{instance_id}")
def get_instance(instance_id: str):
    """Return single instance details."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM instances WHERE id = ?", (instance_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Instance not found")
    result = dict(row)
    return result


@router.post("/{instance_id}/stop")
def stop_instance(instance_id: str):
    """Stop an instance."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT provider, provider_instance_id FROM instances WHERE id = ?",
            (instance_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Instance not found")

    adapter = scheduler.get_adapter(row["provider"])
    success = adapter.stop_instance(row["provider_instance_id"])
    if not success:
        raise HTTPException(status_code=502, detail="Failed to stop instance")

    with get_db() as conn:
        conn.execute(
            "UPDATE instances SET status = 'stopped' WHERE id = ?",
            (instance_id,),
        )

    return {"instance_id": instance_id, "status": "stopped"}


@router.post("/{instance_id}/start")
def start_instance(instance_id: str):
    """Start a stopped instance."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT provider, provider_instance_id FROM instances WHERE id = ?",
            (instance_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Instance not found")

    adapter = scheduler.get_adapter(row["provider"])
    success = adapter.start_instance(row["provider_instance_id"])
    if not success:
        raise HTTPException(status_code=502, detail="Failed to start instance")

    with get_db() as conn:
        conn.execute(
            "UPDATE instances SET status = 'pending' WHERE id = ?",
            (instance_id,),
        )

    return {"instance_id": instance_id, "status": "pending"}


@router.delete("/{instance_id}")
def delete_instance(instance_id: str):
    """Terminate and remove an instance."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT provider, provider_instance_id FROM instances WHERE id = ?",
            (instance_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Instance not found")

    adapter = scheduler.get_adapter(row["provider"])
    success = adapter.delete_instance(row["provider_instance_id"])
    if not success:
        raise HTTPException(status_code=502, detail="Failed to delete instance")

    with get_db() as conn:
        conn.execute("DELETE FROM instances WHERE id = ?", (instance_id,))

    return {"instance_id": instance_id, "deleted": True}
