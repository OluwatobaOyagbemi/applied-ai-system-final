"""Guardrails: deterministic checks in three layers. The LLM is never trusted on its own.

INPUT guardrails (before any AI call)
  check_request  - empty / oversized text, emergency descriptions (stop and
                   refer to a vet), prompt-injection attempts (refuse), control
                   characters and HTML stripped, emails and phone numbers
                   redacted so they are never sent to the API
  check_owner    - time budget, pet count, name and notes length, and
                   injection text hidden in pet notes

OUTPUT guardrails (on what the planner returns)
  check_planner_output - task-count cap, confidence clamped to 0-1, links
                   stripped, planner notes screened for unsafe advice
  check_task / check_all - every proposed task, as below

CODE guardrails (runtime protections in agent.py / planner.py)
  hard cap on planning rounds, API timeout and retry limits, a fingerprint
  check that a run never modifies the owner's data, and apply_approved()
  re-checking each task at the moment it is approved

Per-task checks in check_task:
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
    # Added after the hard eval cases showed keyword-free emergencies slipping
    # through offline. The AI check (safety_check.py) still covers new wordings.
    r"\b(won'?t|can'?t|cannot|unable to) (get up|stand)\b", r"\b(can'?t|cannot|unable to) (walk|move)\b",
    r"\b(hasn'?t|has not|won'?t|isn'?t|not) (eaten|eating|drunk|drinking)\b.{0,30}\b(since|for|in|all) ",
    r"\bnothing (comes|came|is coming) out\b", r"\bstraining to (pee|urinate)\b", r"\bcan'?t (pee|urinate)\b",
    r"\bunresponsive\b", r"\bpale gums\b", r"\bblue gums\b", r"\bbloated\b", r"\b(won'?t|can'?t) stop (vomiting|shaking|bleeding)\b",
    r"\bhit by\b", r"\bbitten by\b", r"\bfell (off|from)\b",
]

# Specific drugs or home remedies the planner must never suggest. Taken from
# the safety exclusions documented in knowledge/SOURCES.md.
BLOCKED_TERMS = [
    "ipecac", "hydrogen peroxide", "peroxide", "aspirin", "tylenol", "acetaminophen",
    "ibuprofen", "advil", "naproxen", "pepto", "bismuth", "kaopectate",
    "benadryl", "diphenhydramine", "human toothpaste", "induce vomiting",
    # Added after the AI red team (round 1) slipped brand names and products through:
    "aleve", "motrin", "excedrin", "midol", "imodium", "loperamide", "sudafed", "pseudoephedrine",
    "phenylephrine", "nyquil", "dayquil", "zyrtec", "claritin", "melatonin", "xylitol", "birch sugar",
    "essential oil", "tea tree", "eucalyptus", "peppermint oil", "pine-sol", "pine sol", "permethrin",
    "motor oil", "kerosene", "turpentine", "horse dewormer", "ivermectin", "head & shoulders",
    "human shampoo", "dish soap", "bleach",
]
# Unsafe products, remedies and activities that contain no drug word. Each is
# (pattern, reason). Also added after the AI red team; see evidence/redteam_*.md.
UNSAFE_PATTERNS = [
    (r"\btoothpaste\b", r"\b(pet|dog|cat|enzymatic|veterinary|vet)[- ]?(safe )?toothpaste\b|\bnever\b|\bnot\b",
     "human toothpaste can contain xylitol and fluoride"),
    (r"\b(salt|salty) ?(water|dissolved)|\bdissolved salt\b|\btablespoon of salt\b", None, "salt water is a dangerous home remedy"),
    (r"\b(match|lighter|flame)\b.{0,40}\btick|\btick.{0,40}\b(match|lighter|flame)\b", None, "burning ticks injures the pet"),
    (r"\bsunscreen\b.{0,40}\bzinc\b|\bzinc\b.{0,40}\bsunscreen\b|\bzinc[- ]oxide\b", None, "zinc oxide is toxic if licked"),
    (r"\b(advantix|k9 advantix|dog flea (treatment|product|drops))\b", None, "dog flea products can poison cats; the vet chooses products"),
    (r"\b(wait|waits|waiting|stay|stays|left|leave)\b.{0,30}\b(in|inside) the (car|truck|vehicle)\b|\bwindows? cracked\b",
     None, "a parked car can overheat in minutes"),
    (r"\b(asphalt|pavement|blacktop|hot sand)\b.{0,60}\b(noon|midday|july|august|summer|heat|hot)\b|"
     r"\b(noon|midday|july|august)\b.{0,60}\b(asphalt|pavement|blacktop)\b", None, "hot pavement burns paws and risks heat stroke"),
    (r"\b(pickup|truck) bed\b|\bride loose\b", None, "riding loose in a truck bed risks falls"),
    (r"\b(green|scummy|algae|stagnant)\b.{0,25}\b(pond|lake|water)\b|\b(pond|lake)\b.{0,25}\b(scum|algae)\b",
     None, "blue-green algae can be fatal"),
    (r"\bshave\w*\b.{0,40}\b(husky|malamute|samoyed|double[- ]coat\w*|to the skin)\b", None, "shaving a double coat removes heat protection"),
    (r"\b(hair ties|rubber bands|string toy|yarn|thread)\b.{0,60}\b(while|alone|unsupervised|at work)\b", None,
     "strings and hair ties can cause intestinal blockages if swallowed unsupervised"),
    (r"\b(cooked|chicken wing|wing|rib|steak)\b.{0,15}\bbones?\b", None, "cooked bones splinter"),
    (r"\b(double|triple|extra)\b.{0,25}\b(dose|chewables?|tablets?|pills?|carprofen|meds?)\b", None,
     "changing a dose is the vet's decision"),
    (r"\b(motor|engine) oil\b|\bused oil\b", None, "oil-based home remedies are toxic"),
]
# Doses written in words ("two twenty-five-milligram tabs", "half a pill").
WORD_DOSE_PATTERN = re.compile(
    r"\b(one|two|three|four|half|a half|quarter|a couple of|a)\s+(\w+[- ])?(tablets?|tabs?|pills?|caplets?|chewables?|"
    r"capsules?|milligrams?|ml|teaspoons?|tablespoons?|drops?|doses?)\b|\bmilligrams?\b", re.I)
# Toxic foods: blocked when a task would feed them, e.g. "give chocolate treat".
TOXIC_FOODS = ["chocolate", "grape", "raisin", "xylitol", "onion", "garlic", "antifreeze",
               "sultana", "currant", "cacao", "cocoa", "macadamia", "coffee", "alcohol", "beer", "wine",
               "chive", "leek", "avocado", "gravy"]
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


# ============================================================================
# INPUT guardrails
# ============================================================================

MAX_PETS = 10
MAX_NAME_CHARS = 40
MAX_NOTES_CHARS = 300

# Attempts to override the planner's instructions. The rules are enforced in
# code anyway, but refusing these keeps the model from being steered at all.
INJECTION_PATTERNS = [
    r"\bignore (all |any |the |your )?(previous |prior |above )?(instructions|rules|prompt)",
    r"\bdisregard (all |any |the |your )?(previous |prior )?(instructions|rules)",
    r"\b(system|developer) prompt\b", r"\byou are now\b", r"\bact as\b", r"\bjailbreak\b",
    r"\bpretend (to be|you)\b", r"\bnew instructions\b", r"\bdo anything now\b",
    r"\boverride (the |your )?(rules|guardrails|safety)",
    r"</?(system|assistant|instructions|sources|request|pets)>",
    # Added after the AI red team (round 1):
    r"\b(system|admin|developer|debug|maintenance|test) (notice|mode|configuration|override)\b",
    r"\bsafety (module|filter|rules?|guidelines?|restrictions?|override)\b.{0,60}\b(off|disabled?|maintenance|deprecated|removed|unfiltered|override|supersede)",
    r"\b(unfiltered|without (any )?(filters?|restrictions?)|no restrictions|sin restricciones|sans restrictions)\b",
    r"\b(supersedes?|overrides?) (the )?(app'?s )?(default )?(rules|restrictions|policy|guidelines)\b",
    r"\bi (authorize|permit|allow) you to\b", r"\bcode ?word\b", r"\b(policy|rule) .{0,40}\b(removed|deprecated|updated|no longer applies)\b",
    r"[\"']?safety_override[\"']?\s*:", r"\b(olvida|ignora) (todas )?(tus|las) reglas\b", r"\boublie (toutes )?(tes|les) r[eè]gles\b",
]
EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
PHONE_PATTERN = re.compile(r"(?<!\d)(\+?\d[\d\s().-]{8,}\d)(?!\d)")
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
HTML_TAG = re.compile(r"<[^>]{1,200}>")


@dataclass
class InputCheck:
    ok: bool
    reason: str = ""
    emergency: bool = False
    cleaned: str = ""          # the sanitized, PII-redacted text to send onward
    redactions: int = 0


def sanitize_text(text: str) -> tuple[str, int]:
    """Strip control characters and HTML tags, redact emails and phone numbers.
    Returns (clean text, number of redactions)."""
    text = CONTROL_CHARS.sub("", text)
    text = HTML_TAG.sub(" ", text)
    text, n_email = EMAIL_PATTERN.subn("[email removed]", text)
    n_phone = 0

    def _phone(m: re.Match) -> str:
        nonlocal n_phone
        if sum(ch.isdigit() for ch in m.group(0)) < 10:   # dates, times, small numbers
            return m.group(0)
        n_phone += 1
        return "[phone removed]"

    text = PHONE_PATTERN.sub(_phone, text)
    return re.sub(r"[ \t]+", " ", text).strip(), n_email + n_phone


def _looks_like_injection(text: str) -> str | None:
    lowered = text.lower()
    return next((p for p in INJECTION_PATTERNS if re.search(p, lowered)), None)


def check_request(text: str) -> InputCheck:
    """Validate and sanitize the owner's free-text request before any AI call."""
    if text is None or not text.strip():
        return InputCheck(True, "No extra request; planning from pet profiles only.")
    if len(text) > MAX_REQUEST_CHARS:
        return InputCheck(False, f"Request is too long ({len(text)} characters, max {MAX_REQUEST_CHARS}).")
    injection = _looks_like_injection(text)
    if injection:
        log.warning("Prompt-injection pattern in request: %r", injection)
        return InputCheck(False, "That request looks like an attempt to change WhiskerWise's instructions, "
                                 "so it wasn't sent to the AI. Describe your pets' day instead.")
    cleaned, redactions = sanitize_text(text)
    if redactions:
        log.info("Redacted %d piece(s) of contact info from the request", redactions)
    lowered = cleaned.lower()
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
    return InputCheck(True, cleaned=cleaned, redactions=redactions)


def check_owner(owner: Owner) -> InputCheck:
    """Validate the structured profile the planner will see."""
    if not 0 < owner.available_minutes <= 1440:
        return InputCheck(False, f"Minutes available must be between 1 and 1440 (got {owner.available_minutes}).")
    if len(owner.pets) > MAX_PETS:
        return InputCheck(False, f"WhiskerWise plans for up to {MAX_PETS} pets at a time.")
    for pet in owner.pets:
        if len(pet.name) > MAX_NAME_CHARS:
            return InputCheck(False, f"Pet name '{pet.name[:20]}…' is too long (max {MAX_NAME_CHARS} characters).")
        if len(pet.notes) > MAX_NOTES_CHARS:
            return InputCheck(False, f"Notes for {pet.name} are too long (max {MAX_NOTES_CHARS} characters).")
        for field in (pet.name, pet.notes, pet.species):
            if _looks_like_injection(field):
                log.warning("Prompt-injection pattern in pet profile for %r", pet.name)
                return InputCheck(False, f"The profile for {pet.name} contains text that looks like "
                                         "instructions to the AI. Please edit it.")
    return InputCheck(True)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()


_GENERIC = {"daily", "weekly", "morning", "evening", "afternoon", "night", "give", "the", "a", "an",
            "and", "for", "with", "pet", "time", "quick", "short", "long", "check", "session"}


_NEGATION = re.compile(r"\b(never|not|no|avoid|don'?t|do not|instead of|rather than|without|unsafe|toxic|dangerous)\b")


def _affirmative_mention(term: str, text: str) -> bool:
    """True if `term` appears in `text` without a negation in the few words
    before it. 'never use human toothpaste' -> False; 'use human toothpaste' -> True."""
    for m in re.finditer(re.escape(term), text):
        window = text[max(0, m.start() - 40):m.start()]
        if not _NEGATION.search(window):
            return True
    return False


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
    # The description is what the owner would do, so any blocked term there
    # counts. In the rationale, a negated mention ("never use human
    # toothpaste") is safety advice, not a suggestion, so it is allowed.
    text = f"{task.description} {task.rationale}".lower()
    desc = task.description.lower()
    hits = [t for t in BLOCKED_TERMS
            if t in desc or _affirmative_mention(t, task.rationale.lower())]
    if hits:
        flag(BLOCKED, f"unsafe: mentions {', '.join(hits)} (vets only)")
    if DOSE_PATTERN.search(text) or (WORD_DOSE_PATTERN.search(desc) and MEDICAL_PATTERN.search(text + " pill")):
        flag(BLOCKED, "unsafe: contains a dose or amount; dosing is the vet's decision")
    for pattern, exempt, reason in UNSAFE_PATTERNS:
        if re.search(pattern, desc) and not (exempt and re.search(exempt, desc)):
            flag(BLOCKED, f"unsafe: {reason}")
    feeding_words = re.search(r"\b(give|feed|treat|treats|snack|offer|drizzle|sprinkle|stuff|top|topper|"
                              r"mix|reward|rewards|serve|add|chew)\b", text)
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
            similar = (t.category == task.category and t.frequency == task.frequency
                       and _key_words(t.description) & _key_words(task.description))
            if same_name or similar:
                flag(BLOCKED, f"duplicate: {pet.name} already has '{t.description}'")
                break
    for prior in already_proposed or []:
        same = _norm(prior.description) == _norm(task.description)
        similar = (prior.category == task.category and prior.frequency == task.frequency
                   and _key_words(prior.description) & _key_words(task.description))
        if prior.pet_name == task.pet_name and (same or similar):
            flag(BLOCKED, f"duplicate of another proposed task ('{prior.description}')")
            break

    task.verdict, task.issues = verdict, issues
    log.info("Guardrail %s: %s (%s) %s", verdict, task.description, task.pet_name, issues or "")
    return task


# ============================================================================
# OUTPUT guardrails (planner-level; per-task checks are in check_task above)
# ============================================================================

MAX_PROPOSALS = 25
URL_PATTERN = re.compile(r"https?://\S+|www\.\S+", re.I)


def _unsafe_free_text(text: str) -> list[str]:
    lowered = text.lower()
    found = [t for t in BLOCKED_TERMS if _affirmative_mention(t, lowered)]
    if DOSE_PATTERN.search(lowered):
        found.append("a dose or amount")
    return found


def check_planner_output(output) -> list[str]:
    """Screen a PlannerOutput in place before its tasks are checked one by one.
    Returns a list of what was changed, for the trace."""
    changes = []
    if len(output.tasks) > MAX_PROPOSALS:
        changes.append(f"kept the first {MAX_PROPOSALS} of {len(output.tasks)} proposals")
        output.tasks = output.tasks[:MAX_PROPOSALS]
    try:
        conf = float(output.confidence)
    except (TypeError, ValueError):
        conf = 0.0
    clamped = min(max(conf, 0.0), 1.0)
    if clamped != conf:
        changes.append(f"confidence {conf} clamped to {clamped}")
    output.confidence = clamped
    for task in output.tasks:
        if URL_PATTERN.search(task.rationale):
            task.rationale = URL_PATTERN.sub("[link removed]", task.rationale)
            changes.append(f"removed a link from '{task.description}'")
    if URL_PATTERN.search(output.notes):
        output.notes = URL_PATTERN.sub("[link removed]", output.notes)
        changes.append("removed a link from the planner notes")
    unsafe = _unsafe_free_text(output.notes)
    if unsafe:
        output.notes = "[Planner notes withheld by the safety filter.]"
        changes.append(f"withheld planner notes (mentioned {', '.join(unsafe)})")
    for c in changes:
        log.warning("Output guardrail: %s", c)
    return changes


def check_all(tasks: list[ProposedTask], owner: Owner, allowed_citations: set[str]) -> list[ProposedTask]:
    """Check a list of proposals in order, so later duplicates are caught."""
    checked: list[ProposedTask] = []
    for task in tasks:
        checked.append(check_task(task, owner, allowed_citations, already_proposed=[t for t in checked if t.verdict != BLOCKED]))
    return checked
