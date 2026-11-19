"""Health memory across days: daily check-ins, trend alerts and a vet summary.

A single request ("busy morning") can't show that a cat has eaten less three
days running. Owners log a quick check-in per pet per day; analyze() looks for
patterns over the recent days and raises alerts. Every rule is deterministic
and cites the knowledge-base chunk it comes from, so an alert can be traced to
real veterinary guidance:

    urgent    -> the agent stops planning and tells the owner to call a vet now
    call_vet  -> planning continues, with a caution and a "call the vet" reminder
    watch     -> shown to the owner; nothing else changes
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

APPETITE = ["normal", "less", "none"]
ENERGY = ["normal", "low", "very low"]
BATHROOM = ["normal", "diarrhea", "straining", "not going"]
LEVELS = {"watch": 0, "call_vet": 1, "urgent": 2}


@dataclass
class CheckIn:
    pet_name: str
    day: date
    appetite: str = "normal"
    energy: str = "normal"
    bathroom: str = "normal"
    vomited: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.day, str):
            self.day = date.fromisoformat(self.day)
        for name, value, allowed in (("appetite", self.appetite, APPETITE), ("energy", self.energy, ENERGY),
                                     ("bathroom", self.bathroom, BATHROOM)):
            if value not in allowed:
                raise ValueError(f"{name} must be one of {allowed}")
        self.notes = self.notes.strip()[:300]


@dataclass
class Alert:
    pet_name: str
    level: str          # watch | call_vet | urgent
    message: str
    source: str         # knowledge-base chunk id behind the rule

    @property
    def icon(self) -> str:
        return {"watch": "👀", "call_vet": "📞", "urgent": "🚨"}[self.level]


@dataclass
class HealthLog:
    entries: list[CheckIn] = field(default_factory=list)

    def add(self, checkin: CheckIn) -> None:
        """Add a check-in, replacing any earlier one for the same pet and day."""
        self.entries = [e for e in self.entries if not (e.pet_name == checkin.pet_name and e.day == checkin.day)]
        self.entries.append(checkin)

    def for_pet(self, pet_name: str, days: int | None = None, today: date | None = None) -> list[CheckIn]:
        rows = sorted((e for e in self.entries if e.pet_name == pet_name), key=lambda e: e.day)
        if days is not None:
            start = (today or date.today()) - timedelta(days=days - 1)
            rows = [e for e in rows if e.day >= start]
        return rows

    def to_json(self) -> str:
        return json.dumps([asdict(e) | {"day": e.day.isoformat()} for e in self.entries], indent=1)

    @classmethod
    def from_json(cls, text: str) -> "HealthLog":
        data = json.loads(text)
        if not isinstance(data, list) or len(data) > 2000:
            raise ValueError("expected a list of up to 2000 check-ins")
        return cls([CheckIn(**{k: row[k] for k in ("pet_name", "day", "appetite", "energy", "bathroom",
                                                   "vomited", "notes") if k in row}) for row in data])


def _streak(rows: list[CheckIn], test, today: date) -> int:
    """How many consecutive most-recent days (ending today or yesterday) match `test`."""
    if not rows or (today - rows[-1].day).days > 1:
        return 0
    count, expected = 0, rows[-1].day
    for row in reversed(rows):
        if row.day != expected or not test(row):
            break
        count += 1
        expected -= timedelta(days=1)
    return count


def analyze(log: HealthLog, pets: list, today: date | None = None) -> list[Alert]:
    """Look at each pet's last week of check-ins and return alerts, most serious first."""
    today = today or date.today()
    alerts: list[Alert] = []
    for pet in pets:
        rows = log.for_pet(pet.name, days=7, today=today)
        if not rows:
            continue
        cat = pet.species.lower() == "cat"
        name = pet.name
        latest = rows[-1] if (today - rows[-1].day).days <= 1 else None

        not_eating = _streak(rows, lambda r: r.appetite == "none", today)
        if cat and not_eating >= 2:
            alerts.append(Alert(name, "urgent", f"{name} hasn't eaten for {not_eating} days. Cats that stop eating "
                                "can develop a life-threatening liver problem. Call your vet today.", "cornell-cat-feeding#practical-points"))
        elif cat and not_eating == 1:
            alerts.append(Alert(name, "call_vet", f"{name} didn't eat at all on the last check-in. For cats, call your vet "
                                "if it happens again tomorrow.", "cornell-cat-feeding#practical-points"))
        elif not_eating >= 2:
            alerts.append(Alert(name, "call_vet", f"{name} hasn't eaten for {not_eating} days. Call your vet.",
                                "aspca-cat-care#vet-care-and-safety"))

        eating_less = _streak(rows, lambda r: r.appetite in ("less", "none"), today)
        if eating_less >= 3 and not any(a.pet_name == name and "eaten" in a.message for a in alerts):
            alerts.append(Alert(name, "call_vet", f"{name} has eaten less than usual {eating_less} days in a row. "
                                "That's worth a call to your vet.", "pvc-weekly-check#overview"))
        elif latest and latest.appetite == "less" and eating_less < 3:
            alerts.append(Alert(name, "watch", f"{name} ate less than usual. Keep an eye on it.", "pvc-weekly-check#overview"))

        recent = [r for r in rows if (today - r.day).days <= 2]
        upset_days = sum(r.vomited or r.bathroom == "diarrhea" for r in recent)
        if upset_days >= 2:
            alerts.append(Alert(name, "call_vet", f"{name} has had vomiting or diarrhea on {upset_days} of the last 3 days. "
                                "The ASPCA advises calling the vet when it lasts more than two days.", "aspca-cat-care#vet-care-and-safety"))
        elif latest and (latest.vomited or latest.bathroom == "diarrhea"):
            alerts.append(Alert(name, "watch", f"{name} had an upset stomach on the last check-in. Watch for a second day.",
                                "aspca-cat-care#vet-care-and-safety"))

        if latest and latest.energy == "very low":
            alerts.append(Alert(name, "call_vet", f"{name} has very low energy. Call your vet.", "pvc-weekly-check#overview"))
        else:
            low = _streak(rows, lambda r: r.energy != "normal", today)
            if low >= 2:
                alerts.append(Alert(name, "call_vet", f"{name} has had low energy {low} days in a row. Call your vet.",
                                    "pvc-weekly-check#overview"))
            elif latest and latest.energy == "low":
                alerts.append(Alert(name, "watch", f"{name} seemed a bit low on energy.", "pvc-weekly-check#overview"))

        if latest and latest.bathroom == "straining":
            level = "urgent" if cat else "call_vet"
            alerts.append(Alert(name, level, f"{name} was straining to go to the bathroom. "
                                + ("In cats this can be a urinary blockage, which is an emergency. Call your vet now."
                                   if cat else "Call your vet."), "aspca-cat-care#vet-care-and-safety"))
        elif latest and latest.bathroom == "not going":
            alerts.append(Alert(name, "call_vet", f"{name} didn't go to the bathroom. Call your vet if it continues.",
                                "pvc-weekly-check#overview"))
    alerts.sort(key=lambda a: -LEVELS[a.level])
    return alerts


def vet_summary(log: HealthLog, pet, alerts: list[Alert], tasks: list, today: date | None = None, days: int = 14) -> str:
    """A one-page markdown summary for a vet visit. Facts only, nothing generated."""
    today = today or date.today()
    rows = log.for_pet(pet.name, days=days, today=today)
    lines = [f"# Health summary: {pet.name}", "",
             f"{pet.species.capitalize()}, age {pet.age}" + (f". Notes: {pet.notes}" if pet.notes else ""),
             f"Prepared {today:%b %d, %Y} by WhiskerWise from the owner's daily check-ins (last {days} days).", ""]
    mine = [a for a in alerts if a.pet_name == pet.name]
    lines += ["## Flags", ""] + ([f"- {a.icon} {a.message}" for a in mine] or ["- None"]) + [""]
    lines += ["## Daily check-ins", "", "| Date | Appetite | Energy | Bathroom | Vomited | Notes |", "|---|---|---|---|---|---|"]
    lines += [f"| {r.day:%a %b %d} | {r.appetite} | {r.energy} | {r.bathroom} | {'yes' if r.vomited else 'no'} | {r.notes or ''} |"
              for r in rows] or ["| (no check-ins) | | | | | |"]
    current = [t for t in tasks if t.pet_name == pet.name and not t.completed]
    lines += ["", "## Current care routine", ""] + ([f"- {t.description} ({t.duration_minutes} min, {t.frequency})"
                                                    for t in current] or ["- None recorded"])
    lines += ["", "_General pet-care tracking, not a diagnosis. Questions for the vet:_", "", "1. ", "2. ", ""]
    return "\n".join(lines)


def sample_week(pet_name: str, today: date | None = None) -> list[CheckIn]:
    """A demo week where appetite drops off over the last three days."""
    today = today or date.today()
    pattern = ["normal", "normal", "normal", "normal", "less", "less", "less"]
    return [CheckIn(pet_name, today - timedelta(days=6 - i), appetite=a,
                    energy="low" if i == 6 else "normal", notes="left half her breakfast" if a == "less" else "")
            for i, a in enumerate(pattern)]
