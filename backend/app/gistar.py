"""Getis-Ord Gi* hotspot statistic over an H3 hex grid.

Manual implementation (no libpysal/esda dependency): spatial weights come from
H3's own grid_disk adjacency, so the neighborhood is defined purely in hex-grid
terms rather than a separately-built KNN/distance weight matrix.
"""

from dataclasses import dataclass

import h3
import numpy as np
from scipy.stats import norm

DEFAULT_K_RING = 2


@dataclass
class GiStarResult:
    z: float
    p: float
    confidence: int  # 0, 90, 95, or 99
    spot_type: str  # "hot", "cold", "not_significant"


def _confidence_and_spot(z: float, p: float) -> tuple[int, str]:
    if abs(z) > 2.58 and p < 0.01:
        confidence = 99
    elif abs(z) > 1.96 and p < 0.05:
        confidence = 95
    elif abs(z) > 1.65 and p < 0.10:
        confidence = 90
    else:
        confidence = 0

    if confidence == 0:
        spot_type = "not_significant"
    elif z > 0:
        spot_type = "hot"
    else:
        spot_type = "cold"
    return confidence, spot_type


def compute_gistar(values: dict[str, float], k: int = DEFAULT_K_RING) -> dict[str, GiStarResult]:
    """Gi* z-score/p-value/confidence per cell, using cells present in `values` as the study set."""
    cells = list(values.keys())
    n = len(cells)
    if n < 2:
        return {c: GiStarResult(0.0, 1.0, 0, "not_significant") for c in cells}

    idx = {c: i for i, c in enumerate(cells)}
    x = np.array([values[c] for c in cells], dtype=float)
    xbar = x.mean()
    s = x.std()  # population std (ddof=0), per the standard Getis-Ord formula

    results: dict[str, GiStarResult] = {}
    for cell in cells:
        neighbor_idxs = [idx[nb] for nb in h3.grid_disk(cell, k) if nb in idx]
        w = len(neighbor_idxs)
        sum_wx = x[neighbor_idxs].sum()
        sum_w = float(w)
        sum_w2 = float(w)  # binary weights: w_ij^2 == w_ij

        variance_term = (n * sum_w2 - sum_w**2) / (n - 1)
        denom = s * np.sqrt(max(variance_term, 0.0))

        if denom <= 1e-12 or s <= 1e-12:
            z = 0.0
        else:
            z = (sum_wx - xbar * sum_w) / denom

        p = float(2 * (1 - norm.cdf(abs(z))))
        confidence, spot_type = _confidence_and_spot(z, p)
        results[cell] = GiStarResult(z=float(z), p=p, confidence=confidence, spot_type=spot_type)

    return results
