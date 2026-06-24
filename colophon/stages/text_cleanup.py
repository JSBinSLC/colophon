from __future__ import annotations

from colophon.stages import Stage


class TextCleanupStage(Stage):
    label = "Stage 3 — Text cleanup"

    def run(self, ctx: dict) -> None:
        # TODO: ligature normalization, hard hyphen resolution, OCR noise, proper noun pass
        pass

    def analyze(self, ctx: dict) -> None:
        pass
