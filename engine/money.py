"""Rounding shared by the calculators: dollars to cents, half up, like a payroll system."""
from decimal import ROUND_HALF_UP, Decimal


def cents(amount):
    """Round a dollar amount to cents, half up (Python's round() is half-to-even)."""
    return float(Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def require_non_negative(**values):
    for name, value in values.items():
        if value is None or value < 0:
            raise ValueError(f"{name} must be zero or more, got {value!r}")
