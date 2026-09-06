import random

from fastapi import APIRouter, HTTPException, Query

from app import geo, schemas
from app.dataset import store

router = APIRouter(prefix="/api")


def _validate_metro(metro: str) -> str:
    if metro not in geo.METRO_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Unknown metro '{metro}'")
    return metro


@router.get("/health", response_model=schemas.HealthResponse)
def health():
    return {"status": "ok"}


@router.get("/metros", response_model=schemas.MetrosResponse)
def get_metros():
    return {"metros": geo.list_metros()}


@router.get("/boundary", response_model=schemas.BoundaryFeature)
def get_boundary(metro: str = Query("miami")):
    metro = _validate_metro(metro)
    return {
        "type": "Feature",
        "geometry": geo.metro_boundary_geojson(metro),
        "properties": {"metro": metro, "name": geo.METRO_REGISTRY[metro]["name"]},
    }


@router.get("/hexes", response_model=schemas.HexFeatureCollection)
def get_hexes(metro: str = Query("miami")):
    metro = _validate_metro(metro)
    dataset = store.get(metro)
    return {"type": "FeatureCollection", "features": dataset.hex_features}


@router.get("/clusters", response_model=schemas.ClusterFeatureCollection)
def get_clusters(
    metro: str = Query("miami"),
    min_confidence: int = Query(90, ge=0, le=99),
    k: int | None = Query(None, ge=1, le=5),
):
    metro = _validate_metro(metro)
    dataset = store.get(metro)
    if k is not None and k != dataset.k:
        dataset = store.regenerate(metro, k=k)
    features = [f for f in dataset.cluster_features if f["properties"]["confidence_level"] >= min_confidence]
    return {"type": "FeatureCollection", "features": features}


@router.get("/stats", response_model=schemas.StatsResponse)
def get_stats(metro: str = Query("miami")):
    metro = _validate_metro(metro)
    return store.get(metro).stats


@router.post("/regenerate", response_model=schemas.StatsResponse)
def regenerate(metro: str = Query("miami"), seed: int | None = None):
    metro = _validate_metro(metro)
    new_seed = seed if seed is not None else random.randint(1, 1_000_000)
    dataset = store.regenerate(metro, seed=new_seed)
    return dataset.stats
