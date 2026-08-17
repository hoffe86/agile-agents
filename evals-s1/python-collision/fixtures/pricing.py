"""Fixture for the S1 collision test — a module with obvious untested branches."""


def normalise_discount(raw, *, cap=0.9):
    """Coerce a raw discount into a fraction between 0 and `cap`."""
    if raw is None:
        return 0.0
    if isinstance(raw, str):
        raw = raw.strip().rstrip("%")
        if not raw:
            return 0.0
        raw = float(raw) / 100.0
    if raw < 0:
        raise ValueError("discount cannot be negative")
    return min(float(raw), cap)


def apply_discount(price, discount):
    if price < 0:
        raise ValueError("price cannot be negative")
    return round(price * (1.0 - normalise_discount(discount)), 2)
