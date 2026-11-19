"""Tests for the AI layer: retrieval, guardrails, the agent loop, and approval.

No test calls the real API. A ScriptedPlanner returns canned proposals so we
can check that the guardrails catch bad AI output and that the agent revises.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pawpal_system import Owner, Pet, Task
from pawpal_ai import OfflinePlanner, PawPalAgent, Retriever, apply_approved
from pawpal_ai.guardrails import check_request, check_task
from pawpal_ai.models import BLOCKED, NEEDS_REVIEW, OK, PlannerOutput, ProposedTask
from pawpal_ai.planner import PLAN_SCHEMA

RETRIEVER = Retriever()
CITE = "pvc-daily-routine#overview"


def make_owner(minutes=90):
    owner = Owner("Jordan", available_minutes=minutes, day_start="07:30")
    owner.add_pet(Pet("Mochi", "dog", age=2))
    owner.add_pet(Pet("Luna", "cat", age=9))
    return owner


def proposal(**kw):
    base = dict(pet_name="Mochi", description="Evening walk", category="walk", duration_minutes=20,
                priority="high", frequency="daily", citations=[CITE], rationale="Source says walk daily.")
    base.update(kw)
    return ProposedTask(**base)


class ScriptedPlanner:
    """Returns the next canned list of proposals each round and records feedback."""

    def __init__(self, *rounds):
        self.rounds = list(rounds)
        self.feedback_seen = []

    def plan(self, owner, request, chunks, feedback=None):
        self.feedback_seen.append(feedback)
        tasks = self.rounds.pop(0) if len(self.rounds) > 1 else self.rounds[0]
        return PlannerOutput([ProposedTask(**t.to_dict() | {"verdict": OK, "issues": []}) for t in tasks],
                             confidence=0.9, source="scripted")


class FailingPlanner:
    def plan(self, *args, **kwargs):
        raise RuntimeError("API unavailable")


# --- Retrieval -----------------------------------------------------------------

def test_knowledge_base_loads_and_chunks():
    assert len(RETRIEVER.documents) >= 9
    assert CITE in RETRIEVER.chunk_ids


def test_retrieval_finds_litter_guidance_for_cats():
    hits = RETRIEVER.search("litter box cleaning", species="cat", k=3)
    assert hits and hits[0].doc.id == "pvc-daily-routine"


def test_retrieval_finds_toxin_guidance():
    hits = RETRIEVER.search("is chocolate or antifreeze poisonous", k=3)
    assert "pvc-home-safety" in {h.doc.id for h in hits}


def test_retrieval_empty_query_returns_nothing():
    assert RETRIEVER.search("the and of") == []


# --- Input guardrail -------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "My dog is having a seizure right now",
    "Luna ate chocolate an hour ago",
    "he collapsed after the walk",
    "I think she was poisoned",
])
def test_emergency_requests_stop_planning(text):
    check = check_request(text)
    assert not check.ok and check.emergency


@pytest.mark.parametrize("text", ["", "Busy morning, keep it short", "keep poisonous plants away from Luna"])
def test_normal_requests_pass(text):
    assert check_request(text).ok


def test_oversized_request_rejected():
    assert not check_request("x" * 5000).ok


# --- Task guardrails ---------------------------------------------------------------

def test_good_task_is_ok():
    t = check_task(proposal(), make_owner(), {CITE})
    assert t.verdict == OK, t.issues


def test_ungrounded_task_blocked():
    t = check_task(proposal(citations=["made-up#source"]), make_owner(), {CITE})
    assert t.verdict == BLOCKED and "not grounded" in t.issues[0]


def test_task_without_citation_blocked():
    assert check_task(proposal(citations=[]), make_owner(), {CITE}).verdict == BLOCKED


@pytest.mark.parametrize("desc", ["Give aspirin for joint pain", "Give 5 ml syrup", "Induce vomiting with peroxide"])
def test_unsafe_medical_advice_blocked(desc):
    t = check_task(proposal(description=desc, category="meds"), make_owner(), {CITE})
    assert t.verdict == BLOCKED


def test_toxic_treat_blocked_but_avoidance_allowed():
    owner = make_owner()
    assert check_task(proposal(description="Give chocolate treat", category="feeding"), owner, {CITE}).verdict == BLOCKED
    safe = check_task(proposal(description="Store chocolate out of reach", category="general"), owner, {CITE})
    assert safe.verdict != BLOCKED


def test_medication_reminder_needs_review():
    t = check_task(proposal(description="Give vet-prescribed heartworm preventive", category="meds", duration_minutes=5),
                   make_owner(), {CITE})
    assert t.verdict == NEEDS_REVIEW


def test_species_mismatch_blocked():
    t = check_task(proposal(description="Clean litter box", category="cleaning"), make_owner(), {CITE})
    assert t.verdict == BLOCKED and "species mismatch" in t.issues[0]


def test_unknown_pet_and_bad_values_blocked():
    owner = make_owner()
    assert check_task(proposal(pet_name="Rex"), owner, {CITE}).verdict == BLOCKED
    assert check_task(proposal(duration_minutes=0), owner, {CITE}).verdict == BLOCKED
    assert check_task(proposal(duration_minutes=300), owner, {CITE}).verdict == BLOCKED
    assert check_task(proposal(time="25:00"), owner, {CITE}).verdict == BLOCKED


def test_near_duplicate_of_existing_task_blocked():
    owner = make_owner()
    owner.get_pet("Mochi").add_task(Task("Morning walk", 30, "high", category="walk"))
    t = check_task(proposal(description="Daily walk"), owner, {CITE})
    assert t.verdict == BLOCKED and "duplicate" in t.issues[0]


# --- Agent loop ------------------------------------------------------------------------

def test_agent_stops_on_emergency_without_calling_planner():
    planner = ScriptedPlanner([proposal()])
    result = PawPalAgent(planner=planner, retriever=RETRIEVER).run(make_owner(), "my cat is choking")
    assert result.stopped and planner.feedback_seen == [] and result.proposals == []


def test_agent_revises_after_blocked_and_over_budget():
    bad_round = [proposal(description="Give aspirin", category="meds"), proposal(duration_minutes=100)]
    good_round = [proposal(duration_minutes=20)]
    planner = ScriptedPlanner(bad_round, good_round)
    result = PawPalAgent(planner=planner, retriever=RETRIEVER).run(make_owner(minutes=60))
    assert result.rounds == 2
    assert planner.feedback_seen[1] and any("blocked" in f for f in planner.feedback_seen[1])
    assert result.counts[BLOCKED] == 0 and not result.skipped


def test_agent_keeps_best_round_when_problems_persist():
    planner = ScriptedPlanner([proposal(citations=["fake#id"])])
    result = PawPalAgent(planner=planner, retriever=RETRIEVER, max_rounds=2).run(make_owner())
    assert result.rounds == 2 and result.counts[BLOCKED] == 1 and result.confidence < 0.5


def test_agent_falls_back_to_offline_when_api_fails():
    result = PawPalAgent(planner=FailingPlanner(), retriever=RETRIEVER).run(make_owner())
    assert result.planner_source == "offline" and result.proposals
    assert any("failed" in s.message for s in result.trace)


def test_offline_plan_fits_budget_and_is_grounded():
    owner = make_owner(minutes=45)
    result = PawPalAgent(planner=OfflinePlanner(), retriever=RETRIEVER).run(owner)
    assert result.grounded_rate == 1.0
    assert not result.skipped
    assert sum(t.duration_minutes for _, t, _ in result.preview) <= 45


def test_agent_does_not_modify_owner_until_approved():
    owner = make_owner()
    PawPalAgent(planner=OfflinePlanner(), retriever=RETRIEVER).run(owner)
    assert owner.get_all_tasks() == []


# --- Human approval -----------------------------------------------------------------------

def test_apply_approved_adds_only_ticked_and_never_blocked():
    owner = make_owner()
    proposals = [proposal(), proposal(description="Fetch", verdict=BLOCKED), proposal(pet_name="Luna", description="Play", category="enrichment")]
    added = apply_approved(owner, proposals, [0, 1])
    assert [t.description for t in added] == ["Evening walk"]
    assert [t.description for t in owner.get_all_tasks()] == ["Evening walk"]


def test_plan_schema_is_strict():
    item = PLAN_SCHEMA["properties"]["tasks"]["items"]
    assert item["additionalProperties"] is False
    assert set(item["required"]) == set(item["properties"])
