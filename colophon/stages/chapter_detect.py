from __future__ import annotations

from colophon.stages import Stage


class ChapterDetectStage(Stage):
    label = "Stage 4 — Chapter detection & splitting"

    def run(self, ctx: dict) -> None:
        # TODO: heading-based and graph-informed chapter boundary detection
        pass

    def analyze(self, ctx: dict) -> None:
        pass
