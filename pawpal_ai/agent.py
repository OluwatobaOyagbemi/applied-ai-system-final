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
import inspect
import logging
from dataclasses import dataclass, field

from pawpal_system import Owner, Scheduler, Task

from . import guardrails
from .models import BLOCKED, NEEDS_REVIEW, OK, PlannerOutput, ProposedTask, TraceStep
from .planner import OfflinePlanner, Planner, default_planner
from .conflicts import Conflict, find_conflicts, matching_conflict
from .retriever import Chunk, Retriever
from .safety_check import default_emergency_check

log = logging.getLogger(__name__)

HARD_MAX_ROUNDS = 5


def fingerprint(owner: Owner) -> tuple:
    """A snapshot of everything a run must not change (CODE guardrail)."""
    return (owner.name, owner.available_minutes, owner.day_start,
            tuple((p.name, p.species, p.age, p.notes,
                   tuple((t.description, t.duration_minutes, t.priority, t.frequency, t.time,
                          t.completed, t.due_date) for t in p.tasks)) for p in owner.pets))


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
    caution: str = ""                     # shown to the owner when the AI safety check was unsure or failed
    source_conflicts: list[Conflict] = field(default_factory=list)   # retrieved sources that disagree

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
                 max_rounds: int = 3, chunks_per_pet: int = 6, emergency_check="auto"):
        self.planner = planner or default_planner()
        # INPUT guardrail, layer 2: an AI emergency classifier behind the regex.
        # "auto" = use it whenever Claude is the planner (an API key is set).
        if emergency_check == "auto":
            emergency_check = default_emergency_check() if getattr(self.planner, "source", "") == "claude" else None
        self.emergency_check = emergency_check
        self.retriever = retriever or Retriever()
        # CODE guardrail: never more than HARD_MAX_ROUNDS planner calls per run,
        # whatever the caller asks for, so a loop can't run up API costs.
        self.max_rounds = max(1, min(max_rounds, HARD_MAX_ROUNDS))
        self.chunks_per_pet = chunks_per_pet
        self.fallback = OfflinePlanner()

    # --- steps ---------------------------------------------------------------

    def retrieve(self, owner: Owner, request: str) -> list[Chunk]:
        """One query per pet (species, life stage, notes, request) plus the
        request alone, merged and de-duplicated by chunk id."""
        found: dict[str, Chunk] = {}

        def add(chunks: list[Chunk]) -> None:
            for c in chunks:
                if c.id not in found or c.score > found[c.id].score:
                    found[c.id] = c

        for pet in owner.pets:
            senior_age = 7 if pet.species.lower() == "dog" else 10
            stage = "puppy kitten young" if pet.age < 1 else "senior" if pet.age >= senior_age else "adult"
            query = f"{pet.species} {stage} daily care routine feeding water exercise play grooming {pet.notes} {request}"
            add(self.retriever.search(query, species=pet.species, k=self.chunks_per_pet))
            # Life-stage guidance (senior care, puppy/kitten care) can be crowded
            # out by the general query, so it gets its own small search.
            if stage != "adult":
                stage_query = ("senior aging arthritis mobility vet exam" if stage == "senior"
                               else "puppy kitten feeding meals vaccines socialization")
                add(self.retriever.search(f"{pet.species} {stage_query}", species=pet.species, k=2))
            if request.strip():   # the request on its own, within this pet's species
                add(self.retriever.search(request, species=pet.species, k=3))
        return sorted(found.values(), key=lambda c: c.score, reverse=True)

    def _plan(self, owner: Owner, request: str, chunks: list[Chunk], feedback: list[str] | None,
              result: AgentResult, notes: list[str] | None = None) -> PlannerOutput:
        try:
            if notes and "notes" in inspect.signature(self.planner.plan).parameters:
                return self.planner.plan(owner, request, chunks, feedback, notes=notes)
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
        """Plan for `owner`. CODE guardrail: the owner's data is fingerprinted
        before and after, and a run that changed it is refused."""
        before = fingerprint(owner)
        result = self._run(owner, request or "")
        if fingerprint(owner) != before:
            log.error("Agent run modified the owner's data; result discarded")
            return AgentResult(request=request, stopped=True,
                               stop_reason="Internal safety check failed: planning changed your data, so the result was discarded.",
                               trace=result.trace + [TraceStep("stop", "Owner data changed during planning; result discarded.")])
        return result

    def _run(self, owner: Owner, request: str) -> AgentResult:
        result = AgentResult(request=request)
        log.info("Agent run started: %d pet(s), %d min, request=%r", len(owner.pets), owner.available_minutes, request)

        # INPUT guardrails
        check = guardrails.check_request(request)
        if not check.ok:
            result.stopped, result.stop_reason = True, check.reason
            result.trace.append(TraceStep("stop", check.reason, {"emergency": check.emergency}))
            log.warning("Agent stopped at input guardrail: %s", check.reason)
            return result
        if check.redactions:
            result.trace.append(TraceStep("input", f"Removed {check.redactions} piece(s) of contact info before planning."))
        request = check.cleaned
        if self.emergency_check is not None and request.strip():
            pets = "; ".join(f"{p.name}: {p.species}, age {p.age}. {p.notes}" for p in owner.pets)
            verdict = self.emergency_check.check(request, pets)
            if verdict.verdict == "emergency":
                result.stopped = True
                result.stop_reason = (f"This may be an emergency ({verdict.reason.rstrip('.')}). WhiskerWise is a daily "
                                      "planner, not medical help. Contact your veterinarian or an emergency animal "
                                      "clinic now. In the US, the ASPCA Animal Poison Control line is (888) 426-4435.")
                result.trace.append(TraceStep("stop", result.stop_reason, {"emergency": True, "layer": "ai"}))
                log.warning("Agent stopped by AI emergency check: %s", verdict.reason)
                return result
            if verdict.verdict in ("unsure", "error"):
                result.caution = ("If your pet seems unwell or this is a sudden change, contact your veterinarian "
                                  "before following any plan.")
                why = verdict.reason if verdict.verdict == "unsure" else "the AI safety check couldn't run"
                result.trace.append(TraceStep("input", f"Safety check: {why}. Planning, with a caution shown."))
            else:
                result.trace.append(TraceStep("input", "AI safety check: not an emergency."))
        profile = guardrails.check_owner(owner)
        if not profile.ok:
            result.stopped, result.stop_reason = True, profile.reason
            result.trace.append(TraceStep("stop", profile.reason))
            log.warning("Agent stopped at profile guardrail: %s", profile.reason)
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

        # Novel step: notice when the retrieved sources disagree, instead of
        # letting the planner silently pick one.
        result.source_conflicts = find_conflicts(chunks, library=self.retriever.chunks)
        notes = [c.summary() + " Mention both views and tell the owner to confirm with their vet."
                 for c in result.source_conflicts]
        if result.source_conflicts:
            result.trace.append(TraceStep("conflicts", f"{len(result.source_conflicts)} source conflict(s): "
                                          + " ".join(c.summary() for c in result.source_conflicts)))

        feedback: list[str] | None = None
        best: tuple[int, list[ProposedTask], Scheduler, PlannerOutput] | None = None
        for round_no in range(1, self.max_rounds + 1):
            result.rounds = round_no
            output = self._plan(owner, request, chunks, feedback, result, notes)
            changes = guardrails.check_planner_output(output)   # OUTPUT guardrail
            if changes:
                result.trace.append(TraceStep("output", "Output filter: " + "; ".join(changes) + "."))
            result.trace.append(TraceStep("plan", f"Round {round_no}: {output.source} planner proposed {len(output.tasks)} task(s).",
                                          {"confidence": output.confidence}))

            proposals = guardrails.check_all(output.tasks, owner, allowed)
            for p in proposals:   # tasks on a disputed topic go to the owner for review
                conflict = matching_conflict(p.description, result.source_conflicts)
                if conflict and p.verdict != BLOCKED:
                    p.issues.append(conflict.summary() + " Ask your vet which applies.")
                    p.verdict = NEEDS_REVIEW
            n_blocked = sum(p.verdict == BLOCKED for p in proposals)
            n_review = sum(p.verdict == NEEDS_REVIEW for p in proposals)
            result.trace.append(TraceStep("guardrails", f"{len(proposals) - n_blocked - n_review} ok, "
                                          f"{n_review} need your review, {n_blocked} blocked.",
                                          {"blocked": [f"{p.description} ({p.pet_name}): {p.issues[0]}"
                                                       for p in proposals if p.verdict == BLOCKED]}))

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
    for i in sorted(set(approved)):
        if not 0 <= i < len(proposals):
            log.warning("Ignored out-of-range approval index %r", i)
            continue
        p = proposals[i]
        if p.verdict == BLOCKED:
            log.warning("Refused to apply blocked proposal %r", p.description)
            continue
        # CODE guardrail: re-check at approval time, against the owner as it is
        # now, in case the proposal or the pets changed since planning.
        recheck = guardrails.check_task(copy.deepcopy(p), owner, set(p.citations), already_proposed=None)
        if recheck.verdict == BLOCKED:
            log.warning("Refused %r at approval time: %s", p.description, recheck.issues)
            continue
        pet = owner.get_pet(p.pet_name)
        if pet is None:
            continue
        task = to_task(p)
        pet.add_task(task)
        added.append(task)
        log.info("Owner approved: %s for %s", p.description, p.pet_name)
    return added
