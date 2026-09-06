"""Per-metro clustering dataset: friction scores in, Gi*/clusters out.

`Dataset` holds no opinion about where friction scores come from — `ingest()`
takes whatever it's given (a real push from the upstream friction-scoring
service, or `synthetic_data.build_demo_friction_records()` for local dev) and
recomputes Gi*/clusters from it. This module never generates friction data
itself.
"""

import threading

from app import clusters as clusters_mod
from app import geo, gistar, synthetic_data


class Dataset:
    def __init__(self, metro_id: str, k: int = gistar.DEFAULT_K_RING):
        self.metro_id = metro_id
        self.k = k
        self._all_cells = geo.get_hex_cells(metro_id)
        self._friction_records: dict[str, dict] = {}
        self.hex_records: list[dict] = []
        self.cluster_records: list[dict] = []
        self.stats: dict = {}
        self._compute_derived()

    def ingest(self, friction_records: list[dict], k: int | None = None) -> None:
        """Replace this metro's friction data and recompute Gi*/clusters from it.

        Each record must have `h3` and `friction_score`; `order_count`, `late_rate`,
        and `avg_delay_minutes` are optional display context.
        """
        self._friction_records = {r["h3"]: r for r in friction_records}
        if k is not None:
            self.k = k
        self._compute_derived()

    def _compute_derived(self) -> None:
        friction_scores = {h3_id: rec["friction_score"] for h3_id, rec in self._friction_records.items()}
        gi_results = gistar.compute_gistar(friction_scores, k=self.k)

        hex_records = []
        for cell in self._all_cells:
            rec = self._friction_records.get(cell)
            hex_records.append(
                {
                    "h3": cell,
                    "has_data": rec is not None,
                    "friction_score": rec["friction_score"] if rec else None,
                    "order_count": rec.get("order_count") if rec else None,
                    "late_rate": rec.get("late_rate") if rec else None,
                    "avg_delay_minutes": rec.get("avg_delay_minutes") if rec else None,
                }
            )

        cluster_list = clusters_mod.build_clusters(friction_scores, gi_results)
        cluster_records = [
            {
                "cluster_id": c.cluster_id,
                "hex_count": c.hex_count,
                "hex_ids": c.hex_ids,
                "mean_friction": c.mean_friction,
                "mean_z": c.mean_z,
                "max_z": c.max_z,
                "confidence_level": c.confidence_level,
                "severity_score": c.severity_score,
                "intervention_tier": c.intervention_tier,
                "suggested_bonus_pct": c.suggested_bonus_pct,
                "centroid": c.centroid,
            }
            for c in cluster_list
        ]

        self.hex_records = hex_records
        self.cluster_records = cluster_records
        self.stats = {
            "metro": self.metro_id,
            "hex_count": len(self._all_cells),
            "hexes_with_friction_data": len(self._friction_records),
            "cluster_count": len(cluster_records),
            "mean_friction_score": round(sum(friction_scores.values()) / len(friction_scores), 4)
            if friction_scores
            else 0.0,
            "k_ring": self.k,
        }


class DatasetStore:
    """Thread-safe holder for one Dataset instance per metro.

    Seeds every metro with demo synthetic data at startup so the app is usable
    immediately; a real deployment would instead wait for the upstream service's
    first push to each metro (or seed the same way as a fallback).
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._datasets = {metro_id: Dataset(metro_id) for metro_id in geo.METRO_REGISTRY}
        for metro_id, dataset in self._datasets.items():
            dataset.ingest(synthetic_data.build_demo_friction_records(metro_id))

    def get(self, metro_id: str) -> Dataset:
        with self._lock:
            return self._datasets[metro_id]

    def ingest(self, metro_id: str, friction_records: list[dict], k: int | None = None) -> Dataset:
        with self._lock:
            dataset = self._datasets[metro_id]
            dataset.ingest(friction_records, k=k)
            return dataset


store = DatasetStore()
