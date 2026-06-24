from __future__ import annotations

from colophon.stages import Stage


class HtmlRepairStage(Stage):
    label = "Stage 2 — HTML structural repair"

    def run(self, ctx: dict) -> None:
        # TODO: BeautifulSoup parse, semantic tag restoration, inline style removal
        pass

    def analyze(self, ctx: dict) -> None:
        pass
