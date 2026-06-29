from datetime import datetime
import secrets


def generate_id() -> str:
    """Return the 20-digit timestamp/random identifier expected by EDSL models."""
    timestamp = datetime.now().strftime("%Y%m%d%H%M")
    suffix = f"{secrets.randbelow(100_000_000):08d}"
    return f"{timestamp}{suffix}"
