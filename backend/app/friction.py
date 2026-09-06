"""Friction score: how badly a hex's deliveries miss their promise time, 0-1."""

MIN_SAMPLES = 3
DELAY_NORMALIZATION_MINUTES = 30.0
LATE_RATE_WEIGHT = 0.6
DELAY_WEIGHT = 0.4


def compute_friction_score(order_count: int, late_rate: float, avg_delay_minutes: float) -> float:
    if order_count == 0:
        return 0.0
    normalized_delay = min(avg_delay_minutes / DELAY_NORMALIZATION_MINUTES, 1.0)
    score = LATE_RATE_WEIGHT * late_rate + DELAY_WEIGHT * normalized_delay
    return max(0.0, min(score, 1.0))


def is_low_sample(order_count: int) -> bool:
    return order_count < MIN_SAMPLES
