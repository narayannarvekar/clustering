"""UX-supporting endpoints: metro list, boundary geometry, friction display, summary stats.

Nothing here is clustering output — no Gi*/confidence/spot_type fields. That data
lives under /api/clusters; the frontend fetches both and merges by `h3` id if it
needs both a hex's friction display and its cluster membership.
"""

from fastapi import APIRouter

from app import geo, schemas
from app.api_common import METRO_QUERY, validate_metro
from app.dataset import store

router = APIRouter(prefix="/api/map", tags=["map"])


@router.get("/metros", response_model=schemas.MetrosResponse, summary="List available metros")
def get_metros():
    """
    List every metro the service has data for.

    Each entry gives the metro's id (pass this as `?metro=` to every other endpoint),
    display name, and a suggested map center/zoom for the frontend to jump to when the
    metro is selected. Backed by `geo.METRO_REGISTRY` — a static, hardcoded list, not a
    computed result.
    """
    return {"metros": geo.list_metros()}


@router.get("/boundary", response_model=schemas.BoundaryFeature, summary="Metro's real MSA boundary")
def get_boundary(metro: str = METRO_QUERY):
    """
    The metro's official U.S. Census Bureau Metropolitan Statistical Area boundary, as a
    GeoJSON `Feature` (real geometry — full TIGER/Line resolution, lightly simplified).

    Static reference geography, unrelated to friction data — it doesn't change across
    `/api/clusters/compute` calls. Used by the frontend purely to draw the metro
    outline; it is not the source of the H3 hex grid (see `/api/map/hexes`).
    """
    metro = validate_metro(metro)
    return {
        "type": "Feature",
        "geometry": geo.metro_boundary_geojson(metro),
        "properties": {"metro": metro, "name": geo.METRO_REGISTRY[metro]["name"]},
    }


@router.get("/hexes", response_model=schemas.MapHexesResponse, summary="Per-hex friction display data")
def get_hexes(metro: str = METRO_QUERY):
    """
    Every H3 (resolution 7) hex covering the metro, with friction display data only —
    no Gi*/cluster fields (those come from `/api/clusters`).

    No geometry — `h3` is the H3 cell id; the frontend derives each hexagon's boundary
    client-side via h3-js's `cellToBoundary`. `has_data` is `false` for hexes the
    friction-scoring service hasn't published a score for (render these as "no data",
    not "good performance").

    Reads from the cached dataset — this endpoint does no computation of its own.
    """
    metro = validate_metro(metro)
    dataset = store.get(metro)
    return {"hexes": dataset.hex_records}


@router.get("/stats", response_model=schemas.MapStatsResponse, summary="Summary counts for the current dataset")
def get_stats(metro: str = METRO_QUERY):
    """Hex/cluster counts and mean friction for the metro's currently cached dataset."""
    metro = validate_metro(metro)
    return store.get(metro).stats
