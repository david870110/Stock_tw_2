"""Default configuration factory helpers."""

from src.tw_quant.config.models import AppConfig

DEFAULT_TIMEZONE = "Asia/Taipei"


def default_app_config() -> AppConfig:
    """Return a minimal default app config for local development."""
    return AppConfig(timezone=DEFAULT_TIMEZONE)
