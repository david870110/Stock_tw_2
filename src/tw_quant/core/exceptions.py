"""Core exceptions used by interface boundaries."""


class TwQuantError(Exception):
    """Base application exception for tw_quant."""


class ConfigurationError(TwQuantError):
    """Raised when required configuration is missing or invalid."""
