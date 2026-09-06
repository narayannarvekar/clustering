"""Group significant hot-spot hexes into contiguous clusters and score severity.

Geometry (dissolved cluster boundary) is intentionally NOT computed here — the
client derives it from `hex_ids` via h3-js's cellsToMultiPolygon, so the API
response only carries stats, not per-cluster polygons.
"""

from dataclasses import dataclass

import h3

from app.gistar import GiStarResult

MIN_HEX_COUNT = 2

SEVERITY_TIERS = [
    (0.75, "Priority Pay + Staffing Review", 25),
    (0.5, "Incentive Bonus", 15),
    (0.3, "Monitor", 5),
    (0.0, "No action", 0),
]


@dataclass
class Cluster:
    cluster_id: int
    hex_ids: list[str]
    hex_count: int
    mean_friction: float
    mean_z: float
    max_z: float
    confidence_level: int
    severity_score: float
    intervention_tier: str
    suggested_bonus_pct: int
    centroid: list[float]  # [lng, lat]


def _connected_components(hot_cells: set[str]) -> list[list[str]]:
    unvisited = set(hot_cells)
    components: list[list[str]] = []
    while unvisited:
        start = unvisited.pop()
        stack = [start]
        component = [start]
        while stack:
            cell = stack.pop()
            neighbors = set(h3.grid_disk(cell, 1)) & unvisited
            for nb in neighbors:
                unvisited.discard(nb)
                stack.append(nb)
                component.append(nb)
        components.append(component)
    return components


def _severity_tier(severity: float) -> tuple[str, int]:
    for threshold, tier, bonus in SEVERITY_TIERS:
        if severity >= threshold:
            return tier, bonus
    return SEVERITY_TIERS[-1][1], SEVERITY_TIERS[-1][2]


def _centroid(hex_ids: list[str]) -> list[float]:
    """Mean of member hex centers — good enough for map pan/zoom, no polygon math needed."""
    lats, lngs = zip(*(h3.cell_to_latlng(c) for c in hex_ids))
    return [sum(lngs) / len(lngs), sum(lats) / len(lats)]


def build_clusters(
    friction_scores: dict[str, float],
    gi_results: dict[str, GiStarResult],
) -> list[Cluster]:
    hot_cells = {c for c, r in gi_results.items() if r.spot_type == "hot"}
    components = [comp for comp in _connected_components(hot_cells) if len(comp) >= MIN_HEX_COUNT]

    clusters: list[Cluster] = []
    for cluster_id, hex_ids in enumerate(components, start=1):
        frictions = [friction_scores[c] for c in hex_ids]
        zs = [gi_results[c].z for c in hex_ids]
        confidences = [gi_results[c].confidence for c in hex_ids]

        mean_friction = sum(frictions) / len(frictions)
        mean_z = sum(zs) / len(zs)
        max_z = max(zs)
        confidence_level = min(confidences)

        severity = max(0.0, min(0.5 * min(mean_z / 3.0, 1.0) + 0.5 * mean_friction, 1.0))
        tier, bonus = _severity_tier(severity)

        clusters.append(
            Cluster(
                cluster_id=cluster_id,
                hex_ids=hex_ids,
                hex_count=len(hex_ids),
                mean_friction=round(mean_friction, 4),
                mean_z=round(mean_z, 3),
                max_z=round(max_z, 3),
                confidence_level=confidence_level,
                severity_score=round(severity, 4),
                intervention_tier=tier,
                suggested_bonus_pct=bonus,
                centroid=_centroid(hex_ids),
            )
        )

    clusters.sort(key=lambda c: c.severity_score, reverse=True)
    for i, cluster in enumerate(clusters, start=1):
        cluster.cluster_id = i
    return clusters
