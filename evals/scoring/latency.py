"""Latency percentiles and token counts."""

import math


def percentile(values: list[float], q: float) -> float | None:
    """Linear-interpolated percentile (numpy's default), q in [0, 100]."""
    if not values:
        return None
    v = sorted(values)
    pos = (len(v) - 1) * q / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def summarize(walls: list[float], tokens: list[int]) -> dict:
    return {"n": len(walls), "p50_s": percentile(walls, 50), "p95_s": percentile(walls, 95),
            "tokens_mean": sum(tokens) / len(tokens) if tokens else None}
