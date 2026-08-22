from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Priority(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class RiskLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ImplementationStatus(str, Enum):
    IMPLEMENTED = "implemented"
    PARTIAL = "partially_implemented"
    NOT_FOUND = "not_found"
    UNCERTAIN = "uncertain"


class Verdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    BLOCKED = "blocked"
    NEEDS_REVIEW = "needs_review"


class RequirementItem(BaseModel):
    id: str
    title: str
    description: str
    priority: Priority = Priority.P1
    acceptance_criteria: list[str] = Field(default_factory=list)
    source: str = ""


class CodeEvidence(BaseModel):
    id: str
    project: str
    path: str
    line: Optional[int] = None
    symbol: Optional[str] = None
    evidence: str
    relevance: str = ""


class ImpactScope(BaseModel):
    id: str
    requirement_id: str
    area: str
    affected_items: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.MEDIUM
    rationale: str = ""


class TestCase(BaseModel):
    id: str
    requirement_id: str
    title: str
    kind: str
    priority: Priority = Priority.P1
    preconditions: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    expected: str
    automation: str = "manual_or_pending"


class RequirementAssessment(BaseModel):
    requirement_id: str
    status: ImplementationStatus
    verdict: Verdict
    confidence: float = Field(ge=0, le=1)
    evidence_refs: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    summary: str


class AnalysisReport(BaseModel):
    report_id: str
    generated_at: datetime = Field(default_factory=now_utc)
    requirement_source: str
    projects: list[str]
    branch: str
    commit_info: dict[str, str] = Field(default_factory=dict)
    requirements: list[RequirementItem] = Field(default_factory=list)
    evidence: list[CodeEvidence] = Field(default_factory=list)
    impacts: list[ImpactScope] = Field(default_factory=list)
    test_cases: list[TestCase] = Field(default_factory=list)
    assessments: list[RequirementAssessment] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def summary(self) -> dict[str, int]:
        return {
            "requirements": len(self.requirements),
            "evidence": len(self.evidence),
            "impacts": len(self.impacts),
            "test_cases": len(self.test_cases),
            "pass": sum(a.verdict == Verdict.PASS for a in self.assessments),
            "fail": sum(a.verdict == Verdict.FAIL for a in self.assessments),
            "needs_review": sum(a.verdict == Verdict.NEEDS_REVIEW for a in self.assessments),
        }
