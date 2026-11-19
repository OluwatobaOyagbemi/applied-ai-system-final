"""Source-conflict detection: notice when retrieved vet sources disagree.

Most RAG systems quietly pick one source when two disagree. WhiskerWise reads
the frequency claims in the retrieved chunks ("exams every 6 months", "brush at
least 3 times a week", "an exam every year"), groups them by care topic, and
reports a conflict when sources give clearly different intervals for the same
topic. The planner is told about each conflict, matching tasks are flagged for
the owner's review, and the app shows both views side by side.

This is deliberately rule-based so it is testable and never invents a claim:
every conflict quotes the exact sentence each source used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .retriever import Chunk

# Care topics and the words that signal them in a sentence.
# Order matters: more specific topics are tried first.
TOPICS = {
    "dental cleaning": r"\b(professional cleanings?|dental cleanings?|dental prophy|cleaning procedures?|scaling)\b",
    "fecal / parasite exam": r"\b(fecal|stool|internal parasite)\b",
    "heartworm test": r"\bheartworm (blood )?test\b",
    "vet exam": r"\b(exams?|examinations?|check-?ups?|wellness visits?|physical exams?)\b",
    "tooth brushing": r"\b(brush|brushing|dentifrice|dental product)\b",
    "bathing": r"\b(bathe|bathing|bath)\b",
    "nail trim": r"\b(nails?|claws?)\b",
    "litter box wash": r"\b(wash|refill|dump)\b.*\blitter\b|\blitter\b.*\b(wash|refill|dump)\b",
    "deworming": r"\bdeworm\w*",
}

_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "twelve": 12, "a": 1, "an": 1}
_UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}

# Each pattern yields an interval in days.
_FREQ_PATTERNS = [
    (re.compile(r"\bevery (\d+|one|two|three|four|five|six|twelve)(?:\s*-\s*(\d+))? (day|week|month|year)s?\b", re.I),
     lambda m: _NUM.get(m.group(1).lower(), None) or int(m.group(1)), lambda m: m.group(3)),
    (re.compile(r"\bevery (day|week|month|year)\b", re.I), lambda m: 1, lambda m: m.group(1)),
    (re.compile(r"\b(?:at least )?(\d+|once|twice|three times) (?:a|per|each|every) (day|week|month|year)\b", re.I),
     None, lambda m: m.group(2)),
    (re.compile(r"\b(daily|weekly|monthly|yearly|annually|annual)\b", re.I), None, None),
]
_TIMES = {"once": 1, "twice": 2, "three times": 3}
_WORD_UNIT = {"daily": ("day", 1), "weekly": ("week", 1), "monthly": ("month", 1),
              "yearly": ("year", 1), "annually": ("year", 1), "annual": ("year", 1)}


@dataclass
class Claim:
    topic: str
    interval_days: float     # shortest interval stated
    max_days: float          # longest interval stated (same as interval_days unless a range like "6-12 months")
    phrase: str          # the frequency words, e.g. "every 6 months"
    stage: str | None    # "young" | "adult" | "senior" | None (unspecified)
    sentence: str
    chunk_id: str
    source: str          # document title


@dataclass
class Conflict:
    topic: str
    claims: list[Claim]   # at least two, with different intervals

    def summary(self) -> str:
        views = "; ".join(f"{c.source} says {c.phrase}" + (f" (for {c.stage} pets)" if c.stage else "")
                          for c in self.claims)
        return f"Sources differ on {self.topic}: {views}."


_STAGES = [("young", r"\b(puppy|puppies|kitten|kittens|young)\b"),
           ("senior", r"\b(senior|seniors|older pets?|over \d+|aging)\b"),
           ("adult", r"\badults?\b")]


def _stage(text: str) -> str | None:
    lowered = text.lower()
    for name, pattern in _STAGES:
        if re.search(pattern, lowered):
            return name
    return None


def _compatible(a: str | None, b: str | None) -> bool:
    """Puppy/kitten schedules are only compared with each other; an unspecified
    stage is compared with adult and senior advice."""
    if "young" in (a, b):
        return a == b
    return a is None or b is None or a == b


def _frequencies(sentence: str) -> list[tuple[int, float, float, str]]:
    """Every frequency phrase in a sentence as (position, min days, max days, phrase)."""
    found = []
    for idx, (pattern, count_fn, unit_fn) in enumerate(_FREQ_PATTERNS):
        for m in pattern.finditer(sentence):
            phrase = m.group(0)
            hi = None
            if idx == 2:                                   # "twice a year", "3 times a week"
                raw = m.group(1).lower()
                per = _TIMES.get(raw) or int(raw)
                days = _UNIT_DAYS[m.group(2).lower()] / per
            elif idx == 3:                                 # "daily", "annual"
                unit, n = _WORD_UNIT[m.group(1).lower()]
                days = _UNIT_DAYS[unit] * n
            else:
                n = count_fn(m)
                if n is None:
                    continue
                unit_days = _UNIT_DAYS[unit_fn(m).lower()]
                days = unit_days * n
                if idx == 0 and m.group(2):
                    hi = unit_days * int(m.group(2))
            if not any(abs(f[0] - m.start()) < 3 for f in found):
                found.append((m.start(), days, hi or days, phrase))
    return found


def _sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text)
    return [s.strip(" -*") for s in re.split(r"(?<=[.!?])\s+|\s+-\s+|\n", text) if len(s.strip()) > 12]


def extract_claims(chunks: list[Chunk], window: int = 90) -> list[Claim]:
    """A claim is a frequency phrase with a care-topic word within `window`
    characters of it. If several topics are close, the most specific one wins
    (TOPICS order), then the nearest."""
    claims: list[Claim] = []
    for chunk in chunks:
        for sentence in _sentences(chunk.text):
            lowered = sentence.lower()
            order = {t: i for i, t in enumerate(TOPICS)}
            topic_hits = [(m.start(), topic) for topic, pattern in TOPICS.items()
                          for m in re.finditer(pattern, lowered)]
            if not topic_hits:
                continue
            for pos, days, hi, phrase in _frequencies(sentence):
                # Skip ages ("6 months of age", "over 5 years") that look like frequencies.
                tail = lowered[pos:pos + len(phrase) + 12]
                if re.search(r"(of age|old\b)", tail) and not phrase.lower().startswith("every"):
                    continue
                # Skip frequencies that describe a medicine ("monthly heartworm preventive").
                if re.search(r"^\W*(\w+\W+){0,2}(preventives?|medications?|medicines?|doses?|pills?)\b",
                             lowered[pos + len(phrase):pos + len(phrase) + 40]):
                    continue
                near = sorted((abs(tp - pos), order[t], tp, t) for tp, t in topic_hits if abs(tp - pos) <= window)
                if near:
                    _, _, best_pos, topic = near[0]
                    # A more specific topic right next to the chosen word wins
                    # ("fecal (internal parasite) exam" is a parasite exam, not a vet exam).
                    specific = [t for _, o, tp, t in near
                                if topic == "vet exam" and o < order[topic] and abs(tp - best_pos) <= 40]
                    if specific:
                        topic = specific[0]
                    stage = _stage(sentence) or _stage(f"{chunk.doc.title} {chunk.heading}")
                    claims.append(Claim(topic, days, hi, phrase, stage, sentence, chunk.id, chunk.doc.title))
    return claims


def find_conflicts(chunks: list[Chunk], ratio: float = 1.5, library: list[Chunk] | None = None) -> list[Conflict]:
    """Group claims by topic and report topics where sources give intervals that
    differ by more than `ratio` (e.g. 6 months vs 12 months).

    With `library` (every chunk in the knowledge base), each topic the retrieved
    chunks make a claim about is cross-checked against the whole library, so a
    disagreement is found even when retrieval only returned one side. A reported
    conflict always involves at least one retrieved claim."""
    retrieved = extract_claims(chunks)
    retrieved_ids = {id(c) for c in retrieved}
    by_topic: dict[str, list[Claim]] = {}
    for claim in retrieved:
        by_topic.setdefault(claim.topic, []).append(claim)
    if library is not None:
        seen = {c.id for c in chunks}
        for claim in extract_claims([c for c in library if c.id not in seen]):
            if claim.topic in by_topic:
                by_topic[claim.topic].append(claim)
    conflicts = []
    for topic, claims in by_topic.items():
        # Keep one claim per (document, interval) so repeats don't pile up.
        unique: dict[tuple[str, float], Claim] = {}
        for c in claims:
            unique.setdefault((c.source, round(c.interval_days)), c)
        claims = sorted(unique.values(), key=lambda c: c.interval_days)
        # Find the most different pair that applies to compatible life stages.
        # Ranges count as agreeing when they overlap ("every 6-12 months" vs "once a year").
        best = None
        for a in claims:
            for b in claims:
                if b.interval_days <= a.interval_days or not _compatible(a.stage, b.stage):
                    continue
                spread = b.interval_days / a.max_days
                involves_retrieved = id(a) in retrieved_ids or id(b) in retrieved_ids
                if spread > ratio and involves_retrieved and (best is None or spread > best[0]):
                    best = (spread, a, b)
        if best:
            # Includes a document contradicting itself (the clinic brochure does this).
            conflicts.append(Conflict(topic, [best[1], best[2]]))
    return conflicts


def matching_conflict(task_description: str, conflicts: list[Conflict]) -> Conflict | None:
    """The conflict, if any, whose topic this task is about."""
    lowered = task_description.lower()
    for conflict in conflicts:
        if re.search(TOPICS[conflict.topic], lowered):
            return conflict
    return None
