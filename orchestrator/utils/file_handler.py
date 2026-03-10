"""
Vibe Coding Agent Orchestrator
File I/O helpers for reading and writing agent log files.
"""
from __future__ import annotations

from pathlib import Path


def write_log(path: str | Path, content: str) -> None:
    """Write *content* to *path*, creating parent directories as needed."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def read_log(path: str | Path) -> str:
    """Read and return the content of *path*. Returns empty string if missing."""
    p = Path(path)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def ensure_dir(path: str | Path) -> Path:
    """Create directory (and parents) if it does not exist, then return it."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p
