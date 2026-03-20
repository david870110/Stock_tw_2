def to_snake_case(value: str) -> str:
    """Convert a simple space or hyphen separated string to snake_case."""
    cleaned = value.strip().replace("-", " ")
    return "_".join(part.lower() for part in cleaned.split())


def normalize_whitespace(value: str) -> str:
    """Collapse whitespace runs to single spaces and trim both ends."""
    return " ".join(value.split())
