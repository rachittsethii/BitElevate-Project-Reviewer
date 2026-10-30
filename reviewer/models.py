"""Data models shared across the pipeline."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class RepoSnapshot(BaseModel):
    """A bounded, in-memory view of a repository (what the reviewer 'sees')."""

    name: str
    source: str  # URL or local path
    paths: list[str] = Field(description="Every file path in the repo (tree listing)")
    files: dict[str, str] = Field(description="Selected file contents, path -> text")
    truncated: bool = False


class DimensionScore(BaseModel):
    dimension: str
    score: int = Field(ge=0, le=5)
    rationale: str
    evidence: list[str] = Field(
        default_factory=list,
        description="File paths from the repo that support this score",
    )

    @field_validator("rationale")
    @classmethod
    def _short(cls, v: str) -> str:
        return v.strip()[:600]


class Fix(BaseModel):
    priority: Literal["high", "medium", "low"]
    file: str | None = None
    action: str = Field(description="One concrete, actionable change")


class LLMReview(BaseModel):
    """Schema the LLM must return. Scores only -- totals are computed in code."""

    summary: str
    dimensions: list[DimensionScore]
    top_fixes: list[Fix]
    strengths: list[str]


class FinalReview(BaseModel):
    repo: str
    overall_score: float  # 0-100, computed in code from weights
    readiness: Literal["Needs rework", "Developing", "Portfolio-ready", "Placement-ready"]
    llm: LLMReview
    static_signals: dict
    dropped_evidence: list[str] = Field(default_factory=list)
    model: str = ""
    needs_mentor_review: bool = False
    mentor_flags: list[str] = Field(default_factory=list)
