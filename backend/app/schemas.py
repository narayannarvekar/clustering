"""Pydantic response models, so the OpenAPI docs show real structured schemas
instead of the empty/untyped schema FastAPI falls back to when a route has no
declared response_model (which Swagger UI's docs then render as "string")."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

# --- shared -------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str


# --- map (UX-supporting) endpoints --------------------------------------

class MetroInfo(BaseModel):
    id: str
    name: str
    full_name: str
    center: list[float]
    zoom: int


class MetrosResponse(BaseModel):
    metros: list[MetroInfo]


class BoundaryProperties(BaseModel):
    metro: str
    name: str


class BoundaryFeature(BaseModel):
    type: Literal["Feature"]
    geometry: dict[str, Any]  # GeoJSON Polygon/MultiPolygon — shape varies by type
    properties: BoundaryProperties


class MapHexRecord(BaseModel):
    """No Gi*/cluster fields — those live under /api/clusters. No geometry — the
    client derives each hex's boundary from `h3` via h3-js."""

    h3: str
    has_data: bool
    friction_score: float | None
    order_count: int | None
    late_rate: float | None
    avg_delay_minutes: float | None


class MapHexesResponse(BaseModel):
    hexes: list[MapHexRecord]


class MapStatsResponse(BaseModel):
    metro: str
    hex_count: int
    hexes_with_friction_data: int
    cluster_count: int
    mean_friction_score: float
    k_ring: int


# --- clusters (core computation) endpoints ------------------------------

class HexFrictionInput(BaseModel):
    """One hex's friction score, as pushed by the upstream friction-scoring service."""

    h3: str
    friction_score: float
    order_count: int | None = None
    late_rate: float | None = None
    avg_delay_minutes: float | None = None


class ComputeRequest(BaseModel):
    """Body for POST /api/clusters/compute.

    `hexes` is required — this service retains no friction data between calls to
    compute clusters from, only the derived cluster output (and hex display data
    for /api/map/hexes). Every call is a full, self-contained push. `k` is
    optional and defaults to the metro's current neighborhood radius.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "k": 2,
                "hexes": [
                    {"h3": "8744acc05ffffff", "friction_score": 0.42, "order_count": 89, "late_rate": 0.13, "avg_delay_minutes": 4.1},
                    {"h3": "8744acc04ffffff", "friction_score": 0.08, "order_count": 61, "late_rate": 0.02, "avg_delay_minutes": 0.6},
                ],
            }
        }
    )

    hexes: list[HexFrictionInput]
    k: int | None = None


class ClusterRecord(BaseModel):
    """No geometry — the client derives the dissolved boundary from `hex_ids` via h3-js."""

    cluster_id: int
    hex_count: int
    hex_ids: list[str]
    mean_friction: float
    mean_z: float
    max_z: float
    confidence_level: int
    severity_score: float
    intervention_tier: str
    suggested_bonus_pct: int
    centroid: list[float]


class ClustersResponse(BaseModel):
    clusters: list[ClusterRecord]
