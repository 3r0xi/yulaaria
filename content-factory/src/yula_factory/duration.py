from __future__ import annotations


# The curve grows gently from the existing 15-second Day 10 reel and reaches
# roughly 70 seconds at month end. Small 2/3-second variations keep the pacing
# editorial rather than mechanical.
DAILY_TARGET_SECONDS = {
    1: 10,
    2: 10,
    3: 11,
    4: 12,
    5: 13,
    6: 13,
    7: 14,
    8: 14,
    9: 15,
    10: 15,
    11: 17,
    12: 20,
    13: 22,
    14: 25,
    15: 28,
    16: 30,
    17: 33,
    18: 36,
    19: 38,
    20: 41,
    21: 44,
    22: 47,
    23: 49,
    24: 52,
    25: 55,
    26: 58,
    27: 61,
    28: 64,
    29: 67,
    30: 70,
}


def target_duration_seconds(day: int) -> int:
    try:
        return DAILY_TARGET_SECONDS[int(day)]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("day must be an integer from 1 to 30") from exc


def validate_duration(day: int, actual_seconds: float, tolerance_seconds: float = 3.0) -> str | None:
    """Return a validation message when a Day 11+ render misses its soft target."""
    if int(day) < 11:
        return None
    target = target_duration_seconds(day)
    if abs(float(actual_seconds) - target) > tolerance_seconds:
        return f"Day {int(day)} render duration should be about {target}s (allowed +/-{tolerance_seconds:g}s)"
    return None
