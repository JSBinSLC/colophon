from __future__ import annotations

from colophon.stages import Stage


class TocRebuildStage(Stage):
    label = "Stage 5 — TOC & spine reconstruction"

    def run(self, ctx: dict) -> None:
        # TODO: generate toc.ncx, nav.xhtml, rebuild content.opf
        pass

    def analyze(self, ctx: dict) -> None:
        pass
