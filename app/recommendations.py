import math


def recommend(peak: float | None, target_utilization: float, headroom_multiplier: float, unit: float) -> tuple[float | None, float | None]:
    if not 0 < target_utilization <= 1:
        raise ValueError("target_utilization must be greater than 0 and at most 1")
    if headroom_multiplier < 1 or unit <= 0:
        raise ValueError("headroom_multiplier must be at least 1 and unit must be positive")
    if peak is None or peak < 0:
        return None, None
    request = math.ceil((peak / target_utilization) / unit) * unit
    limit = math.ceil((peak * headroom_multiplier) / unit) * unit
    return request, max(request, limit)
