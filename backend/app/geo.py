"""Metro geography and H3 helpers.

Each metro's shape is its official U.S. Census Bureau Metropolitan Statistical
Area boundary (Census TIGERweb "Metropolitan Statistical Areas" layer, full
TIGER/Line resolution) — not a hand-drawn approximation. Source files live in
data/metros/<id>.geojson and are loaded + lightly simplified once at import time.
"""

import json
from functools import lru_cache
from pathlib import Path

import h3
from shapely.geometry import mapping, shape

H3_RESOLUTION = 7
SIMPLIFY_TOLERANCE_DEG = 0.001  # ~110m; keeps real coastline/county-line shape, trims render weight

DATA_DIR = Path(__file__).resolve().parent / "data" / "metros"

# Frontend map defaults are hand-picked to frame the urban core well; they
# needn't match the shape's raw geometric centroid, which can skew toward
# sparsely-populated inland portions of the MSA.
METRO_REGISTRY = {
    "miami": {
        "name": "South Florida",
        "full_name": "Miami–Fort Lauderdale–West Palm Beach, FL",
        "file": "miami.geojson",
        "center": [26.05, -80.35],
        "zoom": 9,
    },
    "dallas": {
        "name": "Dallas–Fort Worth",
        "full_name": "Dallas–Fort Worth–Arlington, TX",
        "file": "dallas.geojson",
        "center": [32.85, -97.0],
        "zoom": 9,
    },
}


def list_metros() -> list[dict]:
    return [{"id": metro_id, **{k: v for k, v in cfg.items() if k != "file"}} for metro_id, cfg in METRO_REGISTRY.items()]


@lru_cache(maxsize=None)
def _load_metro_shape(metro_id: str):
    path = DATA_DIR / METRO_REGISTRY[metro_id]["file"]
    feature_collection = json.loads(path.read_text())
    geom = shape(feature_collection["features"][0]["geometry"])
    return geom.simplify(SIMPLIFY_TOLERANCE_DEG, preserve_topology=True)


def _ring_to_latlng(ring) -> list[tuple[float, float]]:
    """A shapely ring's (lng, lat) coords -> H3's (lat, lng) tuples, ring open (no repeated closing point)."""
    coords = list(ring.coords)[:-1]  # shapely rings are closed; h3 wants them open
    return [(lat, lng) for lng, lat in coords]


def _polygon_to_latlngpoly(polygon) -> h3.LatLngPoly:
    outer = _ring_to_latlng(polygon.exterior)
    holes = [_ring_to_latlng(interior) for interior in polygon.interiors]
    return h3.LatLngPoly(outer, *holes)


def get_metro_shape(metro_id: str) -> h3.LatLngPoly | h3.LatLngMultiPoly:
    shape_geom = _load_metro_shape(metro_id)
    if shape_geom.geom_type == "Polygon":
        return _polygon_to_latlngpoly(shape_geom)
    return h3.LatLngMultiPoly(*[_polygon_to_latlngpoly(p) for p in shape_geom.geoms])


def get_hex_cells(metro_id: str, resolution: int = H3_RESOLUTION) -> list[str]:
    """All H3 cells covering the given metro's shape."""
    return list(h3.polygon_to_cells(get_metro_shape(metro_id), resolution))


def metro_boundary_geojson(metro_id: str) -> dict:
    """The metro's real MSA shape, as a GeoJSON geometry."""
    return mapping(_load_metro_shape(metro_id))


def metro_exterior_rings_lnglat(metro_id: str) -> list[list[tuple[float, float]]]:
    """Exterior ring(s) of the metro shape as (lng, lat) tuples, for point-in-polygon tests."""
    shape_geom = _load_metro_shape(metro_id)
    geoms = shape_geom.geoms if shape_geom.geom_type == "MultiPolygon" else [shape_geom]
    return [list(g.exterior.coords) for g in geoms]


def polygon_bbox(metro_id: str) -> tuple[float, float, float, float]:
    """(min_lat, min_lng, max_lat, max_lng) of the metro shape."""
    min_lng, min_lat, max_lng, max_lat = _load_metro_shape(metro_id).bounds
    return min_lat, min_lng, max_lat, max_lng
