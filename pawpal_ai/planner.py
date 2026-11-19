"""Planners turn retrieved guidelines + pet profiles into proposed tasks.

ClaudePlanner  - calls Claude with the retrieved chunks and asks for JSON that
                 matches PLAN_SCHEMA (structured outputs), citing chunk ids.
OfflinePlanner - deterministic fallback built from the `suggested_tasks` in the
                 retrieved documents' front matter. Used when no API key is set,
                 when the API fails, and in tests, so the app always runs.

Both receive the same inputs and return a PlannerOutput, so the agent and the
guardrails treat them the same way.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Protocol

from pawpal_system import PRIORITY_RANK, Owner

from .guardrails import _key_words
from .models import CATEGORIES, PlannerOutput, ProposedTask
from .retriever import Chunk

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "pet_name": {"type": "string"},
                    "description": {"type": "string"},
                    "category": {"type": "string", "enum": CATEGORIES},
                    "duration_minutes": {"type": "integer"},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    "frequency": {"type": "string", "enum": ["daily", "weekly", "once"]},
                    "time": {"type": "string", "description": "Preferred start HH:MM, or empty string for flexible"},
                    "citations": {"type": "array", "items": {"type": "string"}},
                    "rationale": {"type": "string"},
                },
                "required": ["pet_name", "description", "category", "duration_minutes",
                             "priority", "frequency", "time", "citations", "rationale"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string"},
        "confidence": {"type": "number", "description": "0 to 1: how well the sources support this plan"},
    },
    "required": ["tasks", "notes", "confidence"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are the planning step inside PawPal+, an app that builds a pet owner's daily care schedule.

You receive the owner's pets, their time budget, an optional request, and numbered excerpts from a vetted pet-care knowledge base. Propose care tasks for today.

Rules:
- Ground every task in the excerpts. Put the excerpt ids you relied on (for example "pvc-daily-routine#overview") in `citations`. If the excerpts don't support a task, leave it out rather than relying on general knowledge.
- Fit the plan to the owner's minutes. The total should not exceed the budget; prefer high priority for health and safety basics (water, feeding, litter, walks) and lower priority for nice-to-haves.
- Match tasks to species: no litter boxes for dogs, no walks for cats.
- Medication, preventives, vaccines and deworming may appear only as reminders to follow the vet's existing instructions, with category "meds". Never name a drug or product, never give a dose or amount, never suggest home remedies, and never suggest inducing vomiting.
- Don't repeat a task the pet already has.
- Use "time" only when the owner asked for a specific time; otherwise leave it as an empty string.
- Keep descriptions short (under 8 words) and the rationale to one sentence that says what the source recommends.
- Set `confidence` lower when the sources are thin for this pet (for example an unusual species) and say so in `notes`.
- If revision feedback is included, fix every listed problem."""


class Planner(Protocol):
    def plan(self, owner: Owner, request: str, chunks: list[Chunk], feedback: list[str] | None = None) -> PlannerOutput: ...


def describe_owner(owner: Owner) -> str:
    lines = [f"Owner: {owner.name}. Minutes available today: {owner.available_minutes}. Day starts at {owner.day_start}."]
    for pet in owner.pets:
        existing = ", ".join(f"{t.description} ({t.duration_minutes} min)" for t in pet.tasks if not t.completed) or "none"
        notes = f" Notes: {pet.notes}." if pet.notes else ""
        lines.append(f"- {pet.name}: {pet.species}, age {pet.age}.{notes} Existing tasks: {existing}.")
    return "\n".join(lines)


def format_chunks(chunks: list[Chunk]) -> str:
    return "\n\n".join(f"[{c.id}] {c.doc.title} — {c.heading}\n{c.text}" for c in chunks)


class OfflinePlanner:
    """Rule-based planner over the knowledge base's suggested tasks."""

    source = "offline"

    def plan(self, owner: Owner, request: str, chunks: list[Chunk], feedback: list[str] | None = None) -> PlannerOutput:
        by_doc: dict[str, Chunk] = {}
        for c in chunks:
            by_doc.setdefault(c.doc.id, c)   # best-scoring chunk per document

        proposals: list[ProposedTask] = []
        for pet in owner.pets:
            species = pet.species.lower()
            for doc_id, chunk in by_doc.items():
                if chunk.doc.species and species not in chunk.doc.species:
                    continue
                for s in chunk.doc.suggested_tasks:
                    if s.get("species") and species not in s["species"]:
                        continue
                    if any(t.category == s.get("category") and _key_words(t.description) & _key_words(s["description"])
                           for t in pet.tasks if not t.completed):
                        continue   # pet already has something like this
                    proposals.append(ProposedTask(
                        pet_name=pet.name,
                        description=s["description"],
                        category=s.get("category", "general"),
                        duration_minutes=int(s.get("duration_minutes", 10)),
                        priority=s.get("priority", "medium"),
                        frequency=s.get("frequency", "daily"),
                        citations=[chunk.id],
                        rationale=f"Suggested by '{chunk.doc.title}'." + (f" ({s['note']})" if s.get("note") else ""),
                    ))

        # Highest priority first, then shortest, so trimming drops nice-to-haves.
        proposals.sort(key=lambda t: (-PRIORITY_RANK.get(t.priority, 0), t.duration_minutes))
        notes = "Offline planner: tasks come straight from the knowledge base's suggested tasks."
        if feedback and any("budget" in f or "skipped" in f for f in feedback):
            budget, kept, used = owner.available_minutes, [], sum(
                t.duration_minutes for p in owner.pets for t in p.tasks if t.is_due_today()
            )
            for t in proposals:
                if used + t.duration_minutes <= budget:
                    kept.append(t)
                    used += t.duration_minutes
            dropped = [f"{t.description} for {t.pet_name} ({t.priority}, {t.duration_minutes} min)"
                       for t in proposals if t not in kept]
            notes += f" Revised to fit {budget} min; left out: {'; '.join(dropped)}."
            proposals = kept
        unknown = [p.name for p in owner.pets if p.species.lower() not in {"dog", "cat"}]
        confidence = 0.4 if unknown else 0.7
        if unknown:
            notes += f" The knowledge base has little guidance for {', '.join(unknown)}."
        return PlannerOutput(proposals, notes, confidence, source="offline")


class ClaudePlanner:
    """Claude-backed planner using structured outputs for schema-valid JSON."""

    source = "claude"

    def __init__(self, model: str | None = None, client=None, effort: str = "medium"):
        import anthropic   # imported here so offline use never needs the SDK

        self.anthropic = anthropic
        self.model = model or os.getenv("PAWPAL_MODEL", DEFAULT_MODEL)
        self.client = client or anthropic.Anthropic()
        self.effort = effort

    def _build_messages(self, owner: Owner, request: str, chunks: list[Chunk], feedback: list[str] | None) -> list[dict]:
        content = (
            f"<pets>\n{describe_owner(owner)}\n</pets>\n\n"
            f"<request>\n{request.strip() or '(no extra request)'}\n</request>\n\n"
            f"<sources>\n{format_chunks(chunks)}\n</sources>"
        )
        if feedback:
            content += "\n\n<revision_feedback>\n" + "\n".join(f"- {f}" for f in feedback) + "\n</revision_feedback>"
        return [{"role": "user", "content": content}]

    def plan(self, owner: Owner, request: str, chunks: list[Chunk], feedback: list[str] | None = None) -> PlannerOutput:
        a = self.anthropic
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=self._build_messages(owner, request, chunks, feedback),
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": PLAN_SCHEMA}},
            # Server-side fallback: if a safety classifier declines, the API
            # retries on a fallback model inside the same call.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        log.info("Claude response %s: stop_reason=%s usage=%s", getattr(response, "_request_id", "?"),
                 response.stop_reason, getattr(response, "usage", None))
        if response.stop_reason == "refusal":
            raise RuntimeError("Claude declined this request")
        if response.stop_reason == "max_tokens":
            raise RuntimeError("Claude's answer was cut off (max_tokens)")
        text = next((b.text for b in response.content if b.type == "text"), "")
        data = json.loads(text)
        tasks = [ProposedTask.from_dict(t) for t in data.get("tasks", [])]
        return PlannerOutput(
            tasks=tasks,
            notes=data.get("notes", ""),
            confidence=float(data.get("confidence", 0.0)),
            source="claude",
            model=response.model,
        )


def default_planner() -> Planner:
    """Claude if an API key is configured, otherwise the offline planner."""
    if os.getenv("ANTHROPIC_API_KEY", "").startswith("sk-ant-") and "..." not in os.getenv("ANTHROPIC_API_KEY", ""):
        try:
            return ClaudePlanner()
        except Exception as err:   # SDK missing or misconfigured
            log.warning("Claude planner unavailable (%s); using offline planner", err)
    return OfflinePlanner()
