from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ChangeStatus(str, Enum):
    APPLIED = "applied"
    FLAGGED = "flagged"
    SKIPPED = "skipped"


@dataclass
class RepairChange:
    stage: str
    description: str
    confidence: Confidence
    status: ChangeStatus
    location: str | None = None  # e.g. "chapter03.xhtml:42"
    original: str | None = None
    replacement: str | None = None


@dataclass
class RepairReport:
    source_epub: str
    changes: list[RepairChange] = field(default_factory=list)
    epubcheck_violations_before: int = 0
    epubcheck_violations_after: int = 0

    def add(self, change: RepairChange) -> None:
        self.changes.append(change)

    def summary(self) -> dict[str, int]:
        return {
            "applied": sum(1 for c in self.changes if c.status == ChangeStatus.APPLIED),
            "flagged": sum(1 for c in self.changes if c.status == ChangeStatus.FLAGGED),
            "skipped": sum(1 for c in self.changes if c.status == ChangeStatus.SKIPPED),
        }

    def write(self, path: Path) -> None:
        data = {
            "source_epub": self.source_epub,
            "summary": self.summary(),
            "epubcheck_violations_before": self.epubcheck_violations_before,
            "epubcheck_violations_after": self.epubcheck_violations_after,
            "changes": [
                {
                    "stage": c.stage,
                    "description": c.description,
                    "confidence": c.confidence,
                    "status": c.status,
                    "location": c.location,
                    "original": c.original,
                    "replacement": c.replacement,
                }
                for c in self.changes
            ],
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
