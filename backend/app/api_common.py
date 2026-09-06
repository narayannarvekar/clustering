"""Shared helpers used by both the clusters and map routers."""

from fastapi import HTTPException, Query

from app import geo

METRO_QUERY = Query("miami", description="Metro id from GET /api/map/metros (e.g. 'miami', 'dallas').")


def validate_metro(metro: str) -> str:
    if metro not in geo.METRO_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Unknown metro '{metro}'")
    return metro
