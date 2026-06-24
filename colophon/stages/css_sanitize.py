from __future__ import annotations

from colophon.stages import Stage


class CssSanitizeStage(Stage):
    label = "Stage 6 — CSS sanitization"

    def run(self, ctx: dict) -> None:
        # TODO: strip unused selectors, normalize font sizes, strip hardcoded colors
        pass

    def analyze(self, ctx: dict) -> None:
        pass
