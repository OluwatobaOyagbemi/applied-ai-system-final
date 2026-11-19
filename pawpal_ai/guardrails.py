"""Guardrails: deterministic checks on owner input and on every task the AI proposes.

The LLM is never trusted on its own. Before a proposed task can reach the
schedule it must pass these checks:

  input checks   - empty / oversized requests, and emergency descriptions,
                   which stop planning and tell the owner to call a vet
  schema         - the values must build a valid pawpal_system.Task
  grounding      - every task must cite at least one retrieved knowledge chunk
  safety         - no drug doses, no specific human drugs, no "induce
                   vomiting", no toxic foods offered as treats (see
                   knowledge/SOURCES.md for why)
  vet-sensitive  - medication, vaccine, and deworming tasks are allowed only as
                   reminders and need the owner's explicit approval
  sanity         - unknown pets, species mismatches (litter box for a dog),
                   durations over 120 minutes, duplicates of existing tasks
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from pawpal_system import Owner, Task

from .models import BLOCKED, CATEGORIES, NEEDS_REVIEW, OK, ProposedTask

log = logging.getLogger(__name__)

MAX_REQUEST_CHARS = 2000
MAX_TASK_MINUTES = 120

# Words that describe an emergency. If the owner's request contains one, the
# system stops planning: a daily scheduler is the wrong tool.
EMERGENCY_PATTERNS = [
    r"\bseiz(ure|ing)\b", r"\bconvuls", r"\bnot breathing\b", r"\bcan'?t breathe\b",
    r"\bchok(e|ing)\b", r"\bcollaps", r"\bunconscious\b", r"\bbleeding\b",
    r"\bheat ?stroke\b", r"\bhit by (a )?car\b", r"\bpoison(ed|ing)\b", r"\bate (some |a )?(chocolate|antifreeze|grapes?|raisins?|xylitol|rat poison)",
    r"\bswallowed\b", r"\bvomit(ing)? blood\b", r"\bgr[ae]y gums\b", r"\bin shock\b",
]

# Specific drugs or home remedies the planner must never suggest. Taken from
# the safety exclusions documented in knowledge/SOURCES.md.
BLOCKED_TERMS = [
    "ipecac", "hydrogen peroxide", "peroxide", "aspirin", "tylenol", "acetaminophen",
    "ibuprofen", "advil", "naproxen", "pepto", "bismuth", "kaopectate",
    "benadryl", "diphenhydramine", "human toothpaste", "induce vomiting",
]
# Toxic foods: blocked when a task would feed them, e.g. "give chocolate treat".
TOXIC_FOODS = ["chocolate", "grape", "raisin", "xylitol", "onion", "garlic", "antifreeze"]
DOSE_PATTERN = re.compile(r"\b\d+(\.\d+)?\s?(mg|mcg|ml|cc|g|tablets?|pills?|capsules?|tsp|tbsp|units?)\b", re.I)
MEDICAL_PATTERN = re.compile(
    r"\b(med(s|ication|icine)?|pill|dose|dosage|prescri\w*|antibiotic|preventive|heartworm|"
    r"flea|tick|deworm\w*|vaccin\w*|injection|insulin|ointment|drops)\b",
    re.I,
)
SPECIES_ONLY = {
    "cat": [r"\blitter\b"],
    "dog": [r"\bwalk\b", r"\byard\b", r"\bleash\b", r"\bfetch\b"],
}


@dataclass
class InputCheck:
    ok: bool
    reason: str = ""
    emergency: bool = False


def check_request(text: str) -> InputCheck:
    """Validate the owner's free-text request before any AI call."""
    if text is None or not text.strip():
        return InputCheck(True, "No extra request; planning from pet profiles only.")
    if len(text) > MAX_REQUEST_CHARS:
        return InputCheck(False, f"Request is too long ({len(text)} characters, max {MAX_REQUEST_CHARS}).")
    lowered = text.lower()
    for pattern in EMERGENCY_PATTERNS:
        if re.search(pattern, lowered):
            log.warning("Emergency language detected in request: %r", pattern)
            return InputCheck(
                False,
                "This sounds like it could be an emergency. WhiskerWise is a daily planner, "
                "not medical help. Contact your veterinarian or an emergency animal clinic "
                "now. In the US, the ASPCA Animal Poison Control line is (888) 426-4435.",
                emergency=True,
            )
    return InputCheck(True)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()


_GENERIC = {"daily", "weekly", "morning", "evening", "afternoon", "night", "give", "the", "a", "an",
            "and", "for", "with", "pet", "time", "quick", "short", "long", "check", "session"}


def _key_words(text: str) -> set[str]:
    """Content words used to spot near-duplicates like 'Daily walk' vs 'Morning walk'."""
    return {w.rstrip("s") for w in _norm(text).split() if w not in _GENERIC and len(w) > 2}


def check_task(
    task: ProposedTask,
    owner: Owner,
    allowed_citations: set[str],
    already_proposed: list[ProposedTask] | None = None,
) -> ProposedTask:
    """Run every check on one proposed task and set its verdict and issues.
    The worst verdict wins (blocked > needs_review > ok)."""
    issues: list[str] = []
    verdict = OK

    def flag(level: str, message: str) -> None:
        nonlocal verdict
        issues.append(message)
        rank = {OK: 0, NEEDS_REVIEW: 1, BLOCKED: 2}
        if rank[level] > rank[verdict]:
            verdict = level

    # --- schema: must build a real Task ---
    if not task.description:
        flag(BLOCKED, "missing description")
    if task.category not in CATEGORIES:
        flag(BLOCKED, f"unknown category {task.category!r}")
    try:
        Task(task.description or "x", task.duration_minutes, task.priority,
             frequency=task.frequency, time=task.time, category=task.category)
    except (ValueError, AttributeError) as err:
        flag(BLOCKED, f"invalid task values: {err}")

    # --- pet must exist ---
    pet = owner.get_pet(task.pet_name)
    if pet is None:
        flag(BLOCKED, f"no pet named {task.pet_name!r}")

    # --- grounding: cite at least one retrieved chunk ---
    if not task.citations:
        flag(BLOCKED, "not grounded: no citation to the knowledge base")
    else:
        bad = [c for c in task.citations if c not in allowed_citations]
        if bad and len(bad) == len(task.citations):
            flag(BLOCKED, f"not grounded: citations {bad} were not in the retrieved sources")
        elif bad:
            issues.append(f"dropped unknown citations {bad}")
            task.citations = [c for c in task.citations if c in allowed_citations]

    # --- safety ---
    text = f"{task.description} {task.rationale}".lower()
    hits = [t for t in BLOCKED_TERMS if t in text]
    if hits:
        flag(BLOCKED, f"unsafe: mentions {', '.join(hits)} (vets only)")
    if DOSE_PATTERN.search(text):
        flag(BLOCKED, "unsafe: contains a dose or amount; dosing is the vet's decision")
    feeding_words = re.search(r"\b(give|feed|treat|snack|offer)\b", text)
    toxic = [f for f in TOXIC_FOODS if re.search(rf"\b{f}s?\b", text)]
    if toxic and feeding_words and not re.search(r"\b(avoid|never|don'?t|keep away|remove|store)\b", text):
        flag(BLOCKED, f"unsafe: would feed a toxic item ({', '.join(toxic)})")

    # --- vet-sensitive: reminders only, owner must approve ---
    if task.category == "meds" or (task.category != "cleaning" and MEDICAL_PATTERN.search(task.description)):
        flag(NEEDS_REVIEW, "vet-sensitive: confirm product and schedule with your veterinarian")

    # --- sanity ---
    if task.duration_minutes > MAX_TASK_MINUTES:
        flag(BLOCKED, f"duration {task.duration_minutes} min is over the {MAX_TASK_MINUTES} min limit")
    if pet is not None:
        species = pet.species.lower()
        for other, patterns in SPECIES_ONLY.items():
            if other != species and any(re.search(p, task.description.lower()) for p in patterns):
                flag(BLOCKED, f"species mismatch: '{task.description}' is a {other} task but {pet.name} is a {species}")
        for t in pet.tasks:
            if t.completed:
                continue
            same_name = _norm(t.description) == _norm(task.description)
            similar = t.category == task.category and _key_words(t.description) & _key_words(task.description)
            if same_name or similar:
                flag(BLOCKED, f"duplicate: {pet.name} already has '{t.description}'")
                break
    for prior in already_proposed or []:
        if prior.pet_name == task.pet_name and _norm(prior.description) == _norm(task.description):
            flag(BLOCKED, "duplicate of another proposed task")
            break

    task.verdict, task.issues = verdict, issues
    log.info("Guardrail %s: %s (%s) %s", verdict, task.description, task.pet_name, issues or "")
    return task


def check_all(tasks: list[ProposedTask], owner: Owner, allowed_citations: set[str]) -> list[ProposedTask]:
    """Check a list of proposals in order, so later duplicates are caught."""
    checked: list[ProposedTask] = []
    for task in tasks:
        checked.append(check_task(task, owner, allowed_citations, already_proposed=[t for t in checked if t.verdict != BLOCKED]))
    return checked
