"""Builds and caches the full computed dataset per metro: hexes + Gi* + clusters."""

import threading

from app import clusters as clusters_mod
from app import friction, geo, gistar, synthetic_data


class Dataset:
    def __init__(self, metro_id: str, seed: int = synthetic_data.DEFAULT_SEED, k: int = gistar.DEFAULT_K_RING):
        self.metro_id = metro_id
        self.seed = seed
        self.k = k
        self._rebuild_base()
        self._compute_derived()

    def _rebuild_base(self) -> None:
        """Regenerate synthetic orders and per-hex friction scores (expensive, seed-dependent)."""
        all_cells = geo.get_hex_cells(self.metro_id)
        hex_stats = synthetic_data.generate_hex_stats(self.metro_id, seed=self.seed)

        raw_stats: dict[str, tuple[int, float, float]] = {}
        friction_scores: dict[str, float] = {}
        low_sample: dict[str, bool] = {}
        for cell in all_cells:
            stats = hex_stats.get(cell)
            order_count = stats.order_count if stats else 0
            late_rate = stats.late_rate if stats else 0.0
            avg_delay = stats.avg_delay_minutes if stats else 0.0
            raw_stats[cell] = (order_count, late_rate, avg_delay)
            friction_scores[cell] = friction.compute_friction_score(order_count, late_rate, avg_delay)
            low_sample[cell] = friction.is_low_sample(order_count)

        self._all_cells = all_cells
        self._raw_stats = raw_stats
        self._friction_scores = friction_scores
        self._low_sample = low_sample
        self._total_orders = sum(s.order_count for s in hex_stats.values())
        self._hexes_with_data = len(hex_stats)

    def _compute_derived(self) -> None:
        """Recompute Gi*/clusters from the cached base data (cheap, k-dependent)."""
        gistar_input = {c: score for c, score in self._friction_scores.items() if not self._low_sample[c]}
        gi_results = gistar.compute_gistar(gistar_input, k=self.k)

        hex_records = []
        for cell in self._all_cells:
            order_count, late_rate, avg_delay = self._raw_stats[cell]
            gi = gi_results.get(cell)
            hex_records.append(
                {
                    "h3": cell,
                    "order_count": order_count,
                    "late_rate": round(late_rate, 4),
                    "avg_delay_minutes": round(avg_delay, 2),
                    "friction_score": round(self._friction_scores[cell], 4),
                    "low_sample": self._low_sample[cell],
                    "gi_z": round(gi.z, 3) if gi else None,
                    "gi_p": round(gi.p, 4) if gi else None,
                    "confidence": gi.confidence if gi else 0,
                    "spot_type": gi.spot_type if gi else "excluded",
                }
            )

        cluster_list = clusters_mod.build_clusters(gistar_input, gi_results)
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
            "hexes_with_data": self._hexes_with_data,
            "total_orders": self._total_orders,
            "cluster_count": len(cluster_records),
            "mean_friction_score": round(sum(self._friction_scores.values()) / len(self._friction_scores), 4)
            if self._friction_scores
            else 0.0,
            "seed": self.seed,
            "k_ring": self.k,
        }

    def regenerate(self, seed: int | None = None, k: int | None = None) -> None:
        if k is not None:
            self.k = k
        if seed is not None:
            self.seed = seed
            self._rebuild_base()
        self._compute_derived()


class DatasetStore:
    """Thread-safe holder for one Dataset instance per metro."""

    def __init__(self):
        self._lock = threading.Lock()
        self._datasets = {metro_id: Dataset(metro_id) for metro_id in geo.METRO_REGISTRY}

    def get(self, metro_id: str) -> Dataset:
        with self._lock:
            return self._datasets[metro_id]

    def regenerate(self, metro_id: str, seed: int | None = None, k: int | None = None) -> Dataset:
        with self._lock:
            dataset = self._datasets[metro_id]
            dataset.regenerate(seed=seed, k=k)
            return dataset


store = DatasetStore()
