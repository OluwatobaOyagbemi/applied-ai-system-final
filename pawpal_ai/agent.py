"""The PawPal+ planning agent: retrieve -> plan -> check -> schedule -> revise.

    owner request
        |
    [input guardrail] --emergency--> stop, tell owner to call a vet
        |
    [retrieve] guidelines per pet from knowledge/
        |
    [plan] Claude (or offline planner) proposes cited tasks
        |
    [guardrails] block unsafe/ungrounded tasks, flag vet-sensitive ones
        |
    [schedule] dry-run the existing Scheduler on a copy of the owner
        |
    problems? (blocked tasks, skipped tasks, conflicts) --yes--> feedback, re-plan (max N rounds)
        |
    result with a full trace -> owner reviews and approves (human in the loop)
        |
    apply_approved() adds only the ticked tasks to the real pets

The agent never changes the owner's data on its own; apply_approved() is the
only write, and it runs only after the owner approves.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field

from pawpal_system import Owner, Scheduler, Task

from . import guardrails
from .models import BLOCKED, NEEDS_REVIEW, OK, PlannerOutput, ProposedTask, TraceStep
from .planner import OfflinePlanner, Planner, default_planner
from .retriever import Chunk, Retriever

log = logging.getLogger(__name__)


@dataclass
class AgentResult:
    request: str
    stopped: bool = False                 # True when the input guardrail halted planning
    stop_reason: str = ""
    proposals: list[ProposedTask] = field(default_factory=list)
    retrieved: list[Chunk] = field(default_factory=list)
    preview: list[tuple[str, Task, str]] = field(default_factory=list)   # dry-run schedule
    skipped: list[tuple[Task, str]] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    trace: list[TraceStep] = field(default_factory=list)
    rounds: int = 0
    planner_source: str = ""
    planner_model: str = ""
    planner_notes: str = ""
    planner_confidence: float = 0.0

    @property
    def counts(self) -> dict[str, int]:
        return {v: sum(p.verdict == v for p in self.proposals) for v in (OK, NEEDS_REVIEW, BLOCKED)}

    @property
    def grounded_rate(self) -> float:
        """Share of proposals whose citations point at retrieved chunks."""
        if not self.proposals:
            return 0.0
        ok = sum(not any(i.startswith("not grounded") for i in p.issues) for p in self.proposals)
        return round(ok / len(self.proposals), 2)

    @property
    def confidence(self) -> float:
        """Blend of the planner's self-rating and how many proposals survived
        the guardrails. Shown to the owner next to the plan."""
        if self.stopped or not self.proposals:
            return 0.0
        survived = 1 - self.counts[BLOCKED] / len(self.proposals)
        return round(0.5 * self.planner_confidence + 0.5 * survived, 2)


class PawPalAgent:
    def __init__(self, planner: Planner | None = None, retriever: Retriever | None = None,
                 max_rounds: int = 3, chunks_per_pet: int = 6):
        self.planner = planner or default_planner()
        self.retriever = retriever or Retriever()
        self.max_rounds = max_rounds
        self.chunks_per_pet = chunks_per_pet
        self.fallback = OfflinePlanner()

    # --- steps ---------------------------------------------------------------

    def retrieve(self, owner: Owner, request: str) -> list[Chunk]:
        """One query per pet (species, life stage, notes, request) plus the
        request alone, merged and de-duplicated by chunk id."""
        found: dict[str, Chunk] = {}
        for pet in owner.pets:
            stage = "puppy kitten young" if pet.age < 1 else "senior older" if pet.age >= 8 else "adult"
            query = f"{pet.species} {stage} daily care routine feeding water exercise play grooming {pet.notes} {request}"
            for c in self.retriever.search(query, species=pet.species, k=self.chunks_per_pet):
                if c.id not in found or c.score > found[c.id].score:
                    found[c.id] = c
        if request.strip():
            for c in self.retriever.search(request, k=3):
                found.setdefault(c.id, c)
        return sorted(found.values(), key=lambda c: c.score, reverse=True)

    def _plan(self, owner: Owner, request: str, chunks: list[Chunk], feedback: list[str] | None,
              result: AgentResult) -> PlannerOutput:
        try:
            return self.planner.plan(owner, request, chunks, feedback)
        except Exception as err:   # API down, refusal, bad JSON: degrade, don't crash
            log.exception("Planner failed; falling back to offline planner")
            result.trace.append(TraceStep("plan", f"Claude planner failed ({err}); using the offline planner instead."))
            return self.fallback.plan(owner, request, chunks, feedback)

    @staticmethod
    def simulate(owner: Owner, proposals: list[ProposedTask]) -> Scheduler:
        """Dry-run the real Scheduler on a copy of the owner with every
        non-blocked proposal added."""
        sandbox = copy.deepcopy(owner)
        for p in proposals:
            if p.verdict == BLOCKED:
                continue
            pet = sandbox.get_pet(p.pet_name)
            if pet is not None:
                pet.add_task(to_task(p))
        scheduler = Scheduler(sandbox)
        scheduler.generate_plan()
        return scheduler

    # --- main loop -------------------------------------------------------------

    def run(self, owner: Owner, request: str = "") -> AgentResult:
        result = AgentResult(request=request)
        log.info("Agent run started: %d pet(s), %d min, request=%r", len(owner.pets), owner.available_minutes, request)

        check = guardrails.check_request(request)
        if not check.ok:
            result.stopped, result.stop_reason = True, check.reason
            result.trace.append(TraceStep("stop", check.reason, {"emergency": check.emergency}))
            log.warning("Agent stopped at input guardrail: %s", check.reason)
            return result
        if not owner.pets:
            result.stopped, result.stop_reason = True, "Add at least one pet before asking the AI to plan."
            result.trace.append(TraceStep("stop", result.stop_reason))
            return result

        chunks = self.retrieve(owner, request)
        result.retrieved = chunks
        result.trace.append(TraceStep("retrieve", f"Retrieved {len(chunks)} guideline excerpts.",
                                      {"ids": [c.id for c in chunks]}))
        if not chunks:
            result.stopped, result.stop_reason = True, "No relevant guidelines found, so the AI won't guess."
            result.trace.append(TraceStep("stop", result.stop_reason))
            return result
        allowed = {c.id for c in chunks}

        feedback: list[str] | None = None
        best: tuple[int, list[ProposedTask], Scheduler, PlannerOutput] | None = None
        for round_no in range(1, self.max_rounds + 1):
            result.rounds = round_no
            output = self._plan(owner, request, chunks, feedback, result)
            result.trace.append(TraceStep("plan", f"Round {round_no}: {output.source} planner proposed {len(output.tasks)} task(s).",
                                          {"confidence": output.confidence}))

            proposals = guardrails.check_all(output.tasks, owner, allowed)
            n_blocked = sum(p.verdict == BLOCKED for p in proposals)
            n_review = sum(p.verdict == NEEDS_REVIEW for p in proposals)
            result.trace.append(TraceStep("guardrails", f"{len(proposals) - n_blocked - n_review} ok, "
                                          f"{n_review} need your review, {n_blocked} blocked."))

            scheduler = self.simulate(owner, proposals)
            skipped = [(t, r) for t, r in scheduler.skipped]
            conflicts = scheduler.detect_conflicts()
            result.trace.append(TraceStep("schedule", f"Dry run: {len(scheduler.plan)} scheduled, {len(skipped)} skipped, "
                                          f"{len(conflicts)} conflict(s)."))

            problems = n_blocked + len(skipped)
            if best is None or problems < best[0]:
                best = (problems, proposals, scheduler, output)
            if problems == 0:
                break

            feedback = [f"'{p.description}' for {p.pet_name} was blocked: {'; '.join(p.issues)}"
                        for p in proposals if p.verdict == BLOCKED]
            feedback += [f"'{t.description}' for {t.pet_name} was skipped: {r}. The plan is over the "
                         f"{owner.available_minutes}-minute budget; drop or shorten lower-priority tasks."
                         for t, r in skipped]
            if round_no < self.max_rounds:
                result.trace.append(TraceStep("revise", f"Asking the planner to fix {len(feedback)} problem(s).",
                                              {"feedback": feedback}))

        _, proposals, scheduler, output = best
        result.proposals = proposals
        result.preview, result.skipped = scheduler.plan, scheduler.skipped
        result.conflicts = scheduler.detect_conflicts()
        result.planner_source, result.planner_model = output.source, output.model
        result.planner_notes, result.planner_confidence = output.notes, output.confidence
        result.trace.append(TraceStep("done", f"Plan ready after {result.rounds} round(s). Confidence {result.confidence:.2f}. "
                                      "Waiting for your approval."))
        log.info("Agent run finished: rounds=%d counts=%s confidence=%.2f", result.rounds, result.counts, result.confidence)
        return result


def to_task(p: ProposedTask) -> Task:
    return Task(p.description, p.duration_minutes, p.priority, frequency=p.frequency, time=p.time, category=p.category)


def apply_approved(owner: Owner, proposals: list[ProposedTask], approved: list[int]) -> list[Task]:
    """Add the owner-approved proposals (by index) to the real pets.
    Blocked proposals are refused even if their index is passed in."""
    added = []
    for i in approved:
        p = proposals[i]
        if p.verdict == BLOCKED:
            log.warning("Refused to apply blocked proposal %r", p.description)
            continue
        pet = owner.get_pet(p.pet_name)
        if pet is None:
            continue
        task = to_task(p)
        pet.add_task(task)
        added.append(task)
        log.info("Owner approved: %s for %s", p.description, p.pet_name)
    return added
