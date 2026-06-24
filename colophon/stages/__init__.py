from __future__ import annotations

from abc import ABC, abstractmethod


class Stage(ABC):
    """Base class for all pipeline stages."""

    label: str = ""

    def run(self, ctx: dict) -> None:
        """Apply changes (default pipeline mode)."""

    def analyze(self, ctx: dict) -> None:
        """Inspect only — used in --dry-run mode."""
