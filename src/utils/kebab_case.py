import re


_KEBAB_CASE_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def to_kebab_case(value: str) -> str:
    """Normalize text into kebab-case using whitespace, underscores, and hyphens as separators."""
    tokens = [token.lower() for token in re.split(r"[\s_-]+", value.strip()) if token]
    return "-".join(tokens)


def is_kebab_case(value: str) -> bool:
    """Return True when value is strict kebab-case: lowercase/digits segments joined by single hyphens."""
    return _KEBAB_CASE_PATTERN.fullmatch(value) is not None