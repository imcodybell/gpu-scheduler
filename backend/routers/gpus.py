from fastapi import APIRouter
from database import get_db

router = APIRouter(prefix="/api/gpus", tags=["gpus"])


@router.get("")
def list_gpus(
    gpu_type: str | None = None,
    provider: str | None = None,
    normalized: bool = False,
) -> list[dict]:
    """Return available GPU offerings, optionally filtered.

    When ``normalized=True`` the ``gpu_type`` parameter matches against the
    canonical model name (``normalized_gpu_type``), e.g. ``A100`` groups
    both ``A100-SXM`` and ``A100-PCIE`` from all providers.

    When ``normalized=False`` (default) a raw ``gpu_type`` match is performed.
    """
    where = ["available = 1"]
    params: list = []
    if gpu_type:
        if normalized:
            where.append("normalized_gpu_type = ?")
        else:
            where.append("gpu_type = ?")
        params.append(gpu_type)
    if provider:
        where.append("provider = ?")
        params.append(provider)

    query = "SELECT * FROM gpu_offers WHERE " + " AND ".join(where) + " ORDER BY price_per_hour ASC"
    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]
