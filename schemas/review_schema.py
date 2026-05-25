"""Schema for Review Agent output."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReviewResult:
    title: str
    source_file: str
    reviewed_at: str
    logic_score: int
    duplication_score: int
    structure_score: int
    average_score: float
    overall_verdict: str
    awkward_expressions: list[str] = field(default_factory=list)
    incomplete_sentences: list[str] = field(default_factory=list)
    missing_sections: list[str] = field(default_factory=list)
    detected_sections: list[str] = field(default_factory=list)
    feedback_summary: str = ""
