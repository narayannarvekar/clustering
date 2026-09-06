"""Synthetic order generation, per metro — dev/demo data only.

In production, friction scores are computed by a separate upstream service and
pushed to POST /api/clusters/compute; this module exists purely so the app has
something to display locally without that service. `build_demo_friction_records`
produces the exact same shape as that push payload, so nothing downstream of
`Dataset.ingest()` knows or cares that the data came from here instead.
"""

from dataclasses import dataclass

import h3
import numpy as np

from app import geo

DEFAULT_SEED = 42
DEFAULT_ORDER_COUNT = 50_000
KM_PER_DEG_LAT = 111.0
BASE_LATE_PROB = 0.12
BASE_DELAY_SCALE_MIN = 8.0

# Demo-only friction scoring (stands in for the upstream service's own confidence/scoring
# logic — a real push would only include hexes it already trusts).
MIN_SAMPLES = 3
DELAY_NORMALIZATION_MINUTES = 30.0
LATE_RATE_WEIGHT = 0.6
DELAY_WEIGHT = 0.4

# Per metro: urban population centers that draw order density (lat, lng, sigma_km, weight),
# and zones with elevated lateness (lat, lng, radius_km, intensity) — interchanges, causeways,
# airport congestion, and under-supplied pockets.
METRO_PROFILES = {
    "miami": {
        "urban_cores": [
            (25.7743, -80.1937, 4.0, 3.0),   # Downtown Miami
            (25.7907, -80.1300, 3.0, 2.0),   # Miami Beach
            (25.8576, -80.2781, 4.0, 1.5),   # Hialeah
            (26.1224, -80.1373, 4.0, 2.0),   # Fort Lauderdale
            (26.0112, -80.1495, 3.0, 1.2),   # Hollywood
            (26.2379, -80.1248, 3.0, 1.0),   # Pompano Beach
            (26.7153, -80.0534, 4.0, 1.5),   # West Palm Beach
            (26.3683, -80.1289, 3.0, 1.2),   # Boca Raton
        ],
        "background_weight": 2.0,
        "friction_centers": [
            (25.7830, -80.1750, 2.5, 1.8),  # MacArthur Causeway / downtown-Beach approach
            (25.9300, -80.1990, 3.0, 1.6),  # I-95 / 826 Golden Glades interchange
            (25.7700, -80.1770, 2.0, 1.2),  # Port of Miami / downtown congestion
            (26.1000, -80.1150, 2.0, 1.3),  # Fort Lauderdale beach causeway (Las Olas/17th St)
            (25.9500, -80.1450, 2.5, 1.2),  # Hallandale / Aventura Ives Dairy corridor
            (26.7100, -80.0530, 2.0, 1.0),  # West Palm Beach downtown / Flagler bridge
            (26.0500, -80.2400, 2.5, 1.4),  # Interior Broward, under-supplied suburban pocket
        ],
    },
    "dallas": {
        "urban_cores": [
            (32.7767, -96.7970, 4.0, 3.0),   # Downtown Dallas
            (32.7555, -97.3308, 4.0, 2.2),   # Downtown Fort Worth
            (32.7357, -97.1081, 3.0, 1.5),   # Arlington
            (33.0198, -96.6989, 3.0, 1.3),   # Plano
            (32.8140, -96.9489, 3.0, 1.2),   # Irving
            (32.9126, -96.6389, 3.0, 1.0),   # Garland
            (33.1507, -96.8236, 3.0, 1.0),   # Frisco
            (32.9483, -96.7299, 3.0, 0.9),   # Richardson
            (32.7460, -96.9978, 3.0, 0.9),   # Grand Prairie
        ],
        "background_weight": 2.5,
        "friction_centers": [
            (32.8968, -97.0380, 3.5, 1.8),  # DFW International Airport congestion
            (32.7767, -96.8080, 2.5, 1.6),  # Downtown Dallas "Mixmaster" (I-30/I-35E)
            (32.7290, -97.3200, 2.5, 1.4),  # Fort Worth "Mixmaster" (I-30/I-35W)
            (32.9130, -96.7690, 2.5, 1.5),  # High Five Interchange (I-635/US-75)
            (32.7473, -97.0945, 2.0, 1.2),  # Arlington entertainment district (stadiums)
            (33.0000, -96.7300, 3.0, 1.3),  # US-75 Central Expressway commute corridor
            (32.8850, -96.7000, 2.5, 1.2),  # LBJ Freeway (I-635) east Dallas segment
        ],
    },
}


@dataclass
class HexStats:
    order_count: int
    late_rate: float
    avg_delay_minutes: float


def _points_in_polygon(xs: np.ndarray, ys: np.ndarray, polygon_xy: list[tuple[float, float]]) -> np.ndarray:
    """Vectorized even-odd point-in-polygon test. polygon_xy is a list of (x, y) = (lng, lat)."""
    poly = np.array(polygon_xy)
    n = len(poly)
    inside = np.zeros(len(xs), dtype=bool)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        denom = (yj - yi) if (yj - yi) != 0 else 1e-15
        cond = ((yi > ys) != (yj > ys)) & (xs < (xj - xi) * (ys - yi) / denom + xi)
        inside ^= cond
        j = i
    return inside


def _in_metro_shape(xs: np.ndarray, ys: np.ndarray, rings: list) -> np.ndarray:
    """Union test: point counts as inside if inside any of the metro shape's exterior rings."""
    inside = np.zeros(len(xs), dtype=bool)
    for ring in rings:
        inside |= _points_in_polygon(xs, ys, ring)
    return inside


def _sample_points(metro_id: str, n: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Rejection-sample n (lat, lng) points inside the metro shape."""
    profile = METRO_PROFILES[metro_id]
    urban_cores = profile["urban_cores"]
    rings = geo.metro_exterior_rings_lnglat(metro_id)
    weights = np.array([c[3] for c in urban_cores] + [profile["background_weight"]])
    weights = weights / weights.sum()

    min_lat, min_lng, max_lat, max_lng = geo.polygon_bbox(metro_id)

    lats = np.empty(0)
    lngs = np.empty(0)
    batch = int(n * 1.5)
    while len(lats) < n:
        choice = rng.choice(len(weights), size=batch, p=weights)
        batch_lats = np.empty(batch)
        batch_lngs = np.empty(batch)

        is_bg = choice == (len(weights) - 1)
        n_bg = is_bg.sum()
        if n_bg:
            batch_lats[is_bg] = rng.uniform(min_lat, max_lat, size=n_bg)
            batch_lngs[is_bg] = rng.uniform(min_lng, max_lng, size=n_bg)

        for core_idx, (clat, clng, sigma_km, _w) in enumerate(urban_cores):
            mask = choice == core_idx
            n_core = mask.sum()
            if not n_core:
                continue
            dy_km = rng.normal(0, sigma_km, size=n_core)
            dx_km = rng.normal(0, sigma_km, size=n_core)
            batch_lats[mask] = clat + dy_km / KM_PER_DEG_LAT
            batch_lngs[mask] = clng + dx_km / (KM_PER_DEG_LAT * np.cos(np.radians(clat)))

        keep = _in_metro_shape(batch_lngs, batch_lats, rings)
        lats = np.concatenate([lats, batch_lats[keep]])
        lngs = np.concatenate([lngs, batch_lngs[keep]])

    return lats[:n], lngs[:n]


def _friction_boost(metro_id: str, lats: np.ndarray, lngs: np.ndarray) -> np.ndarray:
    boost = np.zeros(len(lats))
    for clat, clng, radius_km, intensity in METRO_PROFILES[metro_id]["friction_centers"]:
        dy_km = (lats - clat) * KM_PER_DEG_LAT
        dx_km = (lngs - clng) * KM_PER_DEG_LAT * np.cos(np.radians(clat))
        dist_km = np.sqrt(dx_km**2 + dy_km**2)
        boost += intensity * np.exp(-((dist_km / radius_km) ** 2))
    return boost


def generate_hex_stats(
    metro_id: str,
    n_orders: int = DEFAULT_ORDER_COUNT,
    seed: int = DEFAULT_SEED,
    resolution: int = geo.H3_RESOLUTION,
) -> dict[str, HexStats]:
    """Generate synthetic orders and aggregate on-time performance per H3 cell."""
    rng = np.random.default_rng(seed)
    lats, lngs = _sample_points(metro_id, n_orders, rng)

    boost = _friction_boost(metro_id, lats, lngs)
    late_prob = np.clip(BASE_LATE_PROB + boost * 0.15, 0, 0.95)
    is_late = rng.random(n_orders) < late_prob
    delay_minutes = np.where(
        is_late,
        rng.exponential(scale=BASE_DELAY_SCALE_MIN * (1 + boost), size=n_orders),
        0.0,
    )

    cells = np.array([h3.latlng_to_cell(lat, lng, resolution) for lat, lng in zip(lats, lngs)])
    uniq_cells, inverse = np.unique(cells, return_inverse=True)

    order_count = np.bincount(inverse)
    late_count = np.bincount(inverse, weights=is_late.astype(float))
    sum_delay = np.bincount(inverse, weights=delay_minutes)

    late_rate = late_count / order_count
    avg_delay = sum_delay / order_count

    return {
        cell: HexStats(order_count=int(order_count[i]), late_rate=float(late_rate[i]), avg_delay_minutes=float(avg_delay[i]))
        for i, cell in enumerate(uniq_cells)
    }


def _demo_friction_score(late_rate: float, avg_delay_minutes: float) -> float:
    normalized_delay = min(avg_delay_minutes / DELAY_NORMALIZATION_MINUTES, 1.0)
    score = LATE_RATE_WEIGHT * late_rate + DELAY_WEIGHT * normalized_delay
    return max(0.0, min(score, 1.0))


def build_demo_friction_records(
    metro_id: str,
    n_orders: int = DEFAULT_ORDER_COUNT,
    seed: int = DEFAULT_SEED,
    resolution: int = geo.H3_RESOLUTION,
) -> list[dict]:
    """
    Local stand-in for what the real friction-scoring service would push to
    POST /api/clusters/compute: one record per hex with `h3` + `friction_score`
    (plus order-volume context for display). Hexes with too few synthetic orders
    to trust are simply omitted — same as a real upstream service would only
    publish scores it's confident in, rather than us deciding what counts as
    "low sample" on its behalf.
    """
    hex_stats = generate_hex_stats(metro_id, n_orders=n_orders, seed=seed, resolution=resolution)
    return [
        {
            "h3": cell,
            "friction_score": round(_demo_friction_score(stats.late_rate, stats.avg_delay_minutes), 4),
            "order_count": stats.order_count,
            "late_rate": round(stats.late_rate, 4),
            "avg_delay_minutes": round(stats.avg_delay_minutes, 2),
        }
        for cell, stats in hex_stats.items()
        if stats.order_count >= MIN_SAMPLES
    ]
