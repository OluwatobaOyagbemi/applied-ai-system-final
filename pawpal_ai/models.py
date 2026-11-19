"""Data types shared by the planner, guardrails, and agent."""

from __future__ import annotations

from dataclasses import dataclass, field

CATEGORIES = ["walk", "feeding", "meds", "enrichment", "grooming", "cleaning", "general"]

# Verdicts a guardrail can give a proposed task, from best to worst.
OK = "ok"                    # safe to add once the owner approves the plan
NEEDS_REVIEW = "needs_review"  # vet-sensitive; owner must tick it explicitly
BLOCKED = "blocked"          # never added; shown with the reason


@dataclass
class ProposedTask:
    """A task the planner suggests. It becomes a real pawpal_system.Task only
    after it passes the guardrails and the owner approves it."""

    pet_name: str
    description: str
    category: str
    duration_minutes: int
    priority: str
    frequency: str
    time: str | None = None
    citations: list[str] = field(default_factory=list)
    rationale: str = ""
    # Filled in by the guardrails:
    verdict: str = OK
    issues: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "ProposedTask":
        """Build from planner JSON, coercing types loosely; the guardrails
        decide whether the values are acceptable."""
        try:
            duration = int(data.get("duration_minutes", 0))
        except (TypeError, ValueError):
            duration = 0
        time = data.get("time") or None
        return cls(
            pet_name=str(data.get("pet_name", "")).strip(),
            description=str(data.get("description", "")).strip(),
            category=str(data.get("category", "general")).strip().lower(),
            duration_minutes=duration,
            priority=str(data.get("priority", "medium")).strip().lower(),
            frequency=str(data.get("frequency", "daily")).strip().lower(),
            time=str(time).strip() if time else None,
            citations=[str(c) for c in data.get("citations", []) or []],
            rationale=str(data.get("rationale", "")).strip(),
        )

    def to_dict(self) -> dict:
        return {
            "pet_name": self.pet_name,
            "description": self.description,
            "category": self.category,
            "duration_minutes": self.duration_minutes,
            "priority": self.priority,
            "frequency": self.frequency,
            "time": self.time,
            "citations": self.citations,
            "rationale": self.rationale,
            "verdict": self.verdict,
            "issues": self.issues,
        }


@dataclass
class PlannerOutput:
    """What a planner returns for one round."""

    tasks: list[ProposedTask]
    notes: str = ""
    confidence: float = 0.0       # the planner's own estimate, 0-1
    source: str = "offline"       # "claude" or "offline"
    model: str = ""


@dataclass
class TraceStep:
    """One entry in the agent's visible reasoning trace."""

    stage: str      # retrieve | plan | guardrails | schedule | revise | stop | done
    message: str
    data: dict = field(default_factory=dict)
