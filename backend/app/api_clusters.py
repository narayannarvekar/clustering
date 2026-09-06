"""The actual clustering product: ingest friction scores, serve Gi*/cluster results.

Nothing here computes friction scores — that's the upstream friction-scoring
service's job. This router only ever consumes friction scores (via /compute)
and serves what Gi*/clustering derived from them.
"""

from typing import Annotated

from fastapi import APIRouter, Body, Query

from app import schemas
from app.api_common import METRO_QUERY, validate_metro
from app.dataset import store

COMPUTE_BODY_EXAMPLE = {
    "summary": "Push friction scores",
    "value": {
        "k": 2,
        "hexes": [
            {"h3": "8744acc05ffffff", "friction_score": 0.42, "order_count": 89, "late_rate": 0.13, "avg_delay_minutes": 4.1},
            {"h3": "8744acc04ffffff", "friction_score": 0.08, "order_count": 61, "late_rate": 0.02, "avg_delay_minutes": 0.6},
        ],
    },
}

router = APIRouter(prefix="/api/clusters", tags=["clusters"])


@router.get("", response_model=schemas.ClustersResponse, summary="Cached hotspot clusters")
def get_clusters(
    metro: str = METRO_QUERY,
    min_confidence: int = Query(
        90, ge=0, le=99, description="Only return clusters whose weakest member hex cleared this Gi* confidence tier (0, 90, 95, or 99)."
    ),
):
    """
    Contiguous clusters of statistically significant "hot" (bad-friction) hexes, each with
    a severity score and a suggested pay-intervention tier.
    """
    metro = validate_metro(metro)
    dataset = store.get(metro)
    records = [r for r in dataset.cluster_records if r["confidence_level"] >= min_confidence]
    return {"clusters": records}


@router.post("/compute", response_model=schemas.ClustersResponse, summary="Push friction scores and compute clusters")
def compute(
    metro: str = METRO_QUERY,
    payload: Annotated[schemas.ComputeRequest, Body(openapi_examples={"push_friction_scores": COMPUTE_BODY_EXAMPLE})] = ...,
):
    """
    The core clustering action. The upstream friction-scoring service calls this with a
    fresh set of per-hex friction scores for the metro; this service retains no friction
    data between calls, so every call is a full, self-contained push — it runs Gi* hotspot
    detection + connected-component clustering on exactly what's provided here and replaces
    the metro's cached cluster output with the result.

    `k` (neighborhood radius) is optional and defaults to the metro's current value.
    """
    metro = validate_metro(metro)
    dataset = store.ingest(metro, [h.model_dump() for h in payload.hexes], k=payload.k)
    return {"clusters": dataset.cluster_records}
