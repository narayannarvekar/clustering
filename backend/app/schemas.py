"""Pydantic response models, so the OpenAPI docs show real structured schemas
instead of the empty/untyped schema FastAPI falls back to when a route has no
declared response_model (which Swagger UI's docs then render as "string")."""

from typing import Any, Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


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


class HexRecord(BaseModel):
    """No geometry — the client derives each hex's boundary from `h3` via h3-js."""

    h3: str
    order_count: int
    late_rate: float
    avg_delay_minutes: float
    friction_score: float
    low_sample: bool
    gi_z: float | None
    gi_p: float | None
    confidence: int
    spot_type: str


class HexesResponse(BaseModel):
    hexes: list[HexRecord]


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


class StatsResponse(BaseModel):
    metro: str
    hex_count: int
    hexes_with_data: int
    total_orders: int
    cluster_count: int
    mean_friction_score: float
    seed: int
    k_ring: int
