"""Pure math for house-meter delta samples (no Home Assistant imports)."""


def relative_spread_kw(samples: list[float]) -> float:
    if len(samples) < 2:
        return 0.0
    lo, hi = min(samples), max(samples)
    mean = sum(samples) / len(samples)
    denom = max(mean, 0.05)
    return (hi - lo) / denom


def best_triple_from_four(
    four: list[float], spread_max: float
) -> tuple[float, float] | None:
    """
    Drop one of four samples so the remaining triple has relative spread <= spread_max.
    Prefer the drop that minimizes triple spread; tie-break by higher triple mean.
    Returns (mean_kw, triple_spread) or None if no single outlier explains the spread.
    """
    best_spread: float | None = None
    best_mean: float | None = None
    for i in range(4):
        sub = [four[j] for j in range(4) if j != i]
        sp = relative_spread_kw(sub)
        if sp <= spread_max:
            mean = sum(sub) / 3.0
            if best_spread is None or sp < best_spread - 1e-12:
                best_spread = sp
                best_mean = mean
            elif best_spread is not None and abs(sp - best_spread) < 1e-12:
                if best_mean is None or mean > best_mean:
                    best_mean = mean
    if best_mean is None or best_spread is None:
        return None
    return (best_mean, best_spread)
