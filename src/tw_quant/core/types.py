"""Core primitive aliases shared across all layers."""

from datetime import date, datetime
from typing import TypeAlias

Symbol: TypeAlias = str
DateLike: TypeAlias = date | datetime | str
