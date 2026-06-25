"""Interactive confirmation for low/medium-confidence pipeline changes."""
from __future__ import annotations

import sys
from typing import Any

from colophon.report import ChangeStatus, Confidence, RepairChange


def review_flagged_changes(ctx: dict) -> None:
    """Prompt the user for each flagged change when --interactive is set."""
    config = ctx.get("config")
    if config is None or not config.interactive:
        return

    report = ctx.get("report")
    if report is None:
        return

    pending = [
        c for c in report.changes
        if c.status == ChangeStatus.FLAGGED
        and c.confidence in (Confidence.LOW, Confidence.MEDIUM)
    ]
    if not pending:
        return

    decisions: list[dict[str, Any]] = ctx.setdefault("interactive_decisions", [])
    print(f"\n{len(pending)} change(s) need review (--interactive):\n")

    for i, change in enumerate(pending, 1):
        print(f"[{i}/{len(pending)}] {change.stage}: {change.description}")
        if change.location:
            print(f"  Location: {change.location}")
        if change.original:
            print(f"  Original:   {change.original}")
        if change.replacement:
            print(f"  Proposed:   {change.replacement}")
        print(f"  Confidence: {change.confidence.value}")

        while True:
            try:
                answer = input("Apply this change? [y/N/a=all/s=skip remaining] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nInteractive review aborted.")
                sys.exit(1)
            if answer in ("y", "yes"):
                change.status = ChangeStatus.APPLIED
                decisions.append({"change": change.description, "applied": True})
                break
            if answer in ("", "n", "no"):
                decisions.append({"change": change.description, "applied": False})
                break
            if answer in ("a", "all"):
                for rest in pending[i - 1:]:
                    rest.status = ChangeStatus.APPLIED
                    decisions.append({"change": rest.description, "applied": True})
                return
            if answer in ("s", "skip"):
                decisions.append({"change": change.description, "applied": False})
                for rest in pending[i:]:
                    decisions.append({"change": rest.description, "applied": False})
                return
            print("  Please answer y, n, a, or s.")