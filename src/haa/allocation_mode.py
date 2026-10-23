"""Strict shared validation for the rebalance workspace preference."""
DEFAULT_ALLOCATION_MODE = "proportional"  # Only an absent preference gets this default.
ALLOCATION_MODES = ("proportional", "biggest_gap_first")
ALLOCATION_MODE_ERROR = "Choose allocation mode: proportional or biggest_gap_first."


def validate_allocation_mode(value):
    if not isinstance(value, str) or value not in ALLOCATION_MODES:
        raise ValueError(ALLOCATION_MODE_ERROR)
    return value
