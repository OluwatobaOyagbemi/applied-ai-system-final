"""Export real agent runs and evaluation numbers for the landing page.

    python -m eval.run_eval            # refresh eval/results.json first
    python -m eval.export_site_data    # writes docs/data.js

The site's demo replays these recorded runs, so everything it shows came
from the actual system (offline planner unless --live).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from pawpal_ai import OfflinePlanner, PawPalAgent, Retriever  # noqa: E402
from pawpal_ai.guardrails import check_task  # noqa: E402
from pawpal_ai.models import ProposedTask  # noqa: E402

from eval.record_evidence import RUNS, make_owner  # noqa: E402
from eval.run_eval import RED_TEAM  # noqa: E402

SCENARIO_META = {
    "Normal day with a tight budget": ("busy", "☀️ Busy morning", "2 pets · 45 min"),
    "Medication reminder": ("meds", "💊 Vet meds", "1 dog · 60 min"),
    "Emergency": ("emergency", "🚨 Emergency", "1 dog · 60 min"),
    "Sources disagree": ("conflict", "⚖️ Sources disagree", "senior cat · 60 min"),
    "Health trend": ("health", "📈 Health trend", "check-ins · 60 min"),
}


def run_to_dict(title, owner, request, result, checkins=None) -> dict:
    key, label, sub = SCENARIO_META[title]
    return {
        "key": key, "label": label, "sub": sub, "title": title, "request": request,
        "pets": [{"name": p.name, "species": p.species, "age": p.age} for p in owner.pets],
        "minutes": owner.available_minutes,
        "stopped": result.stopped, "stopReason": result.stop_reason,
        "trace": [{"stage": s.stage, "message": s.message} for s in result.trace],
        "retrieved": [c.id for c in result.retrieved],
        "proposals": [{"pet": p.pet_name, "task": p.description, "min": p.duration_minutes,
                       "priority": p.priority, "verdict": p.verdict, "cites": p.citations,
                       "issues": p.issues} for p in result.proposals],
        "schedule": [{"time": s, "pet": t.pet_name, "task": t.description, "min": t.duration_minutes}
                     for s, t, _ in result.preview],
        "confidence": result.confidence, "grounded": result.grounded_rate, "rounds": result.rounds,
        "caution": result.caution,
        "conflicts": [{"topic": c.topic, "claims": [{"source": cl.source, "stage": cl.stage, "sentence": cl.sentence,
                                                     "chunk": cl.chunk_id} for cl in c.claims]}
                      for c in result.source_conflicts],
        "health": [{"pet": a.pet_name, "level": a.level, "message": a.message} for a in result.health_alerts],
        "checkins": checkins or [],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    if args.live:
        from pawpal_ai import ClaudePlanner
        planner = ClaudePlanner()
    else:
        planner = OfflinePlanner()
    agent = PawPalAgent(planner=planner, retriever=Retriever())

    scenarios = []
    for title, minutes, pets, request in RUNS:
        owner = make_owner(minutes, pets)
        scenarios.append(run_to_dict(title, owner, request, agent.run(owner, request)))

    # Novel features: a source conflict, and a health trend from daily check-ins.
    owner = make_owner(60, [("Luna", "cat", 12, "senior", [])])
    request = "Luna is 12 now, when should she see the vet?"
    scenarios.append(run_to_dict("Sources disagree", owner, request, agent.run(owner, request)))
    from pawpal_ai.health import HealthLog, sample_week
    week = sample_week("Luna")
    owner = make_owner(60, [("Mochi", "dog", 3, "", []), ("Luna", "cat", 6, "", [])])
    request = "Normal day, nothing special"
    checkins = [{"day": c.day.strftime("%a"), "appetite": c.appetite, "energy": c.energy} for c in week]
    scenarios.append(run_to_dict("Health trend", owner, request, agent.run(owner, request, health_log=HealthLog(week)),
                                 checkins=checkins))

    owner = make_owner(60, [("Mochi", "dog", 3, "", [])])
    red = []
    for name, overrides, _ in RED_TEAM:
        fields = dict(pet_name="Mochi", description="Evening walk", category="walk", duration_minutes=20,
                      priority="high", frequency="daily", citations=["pvc-daily-routine#overview"])
        fields.update(overrides)
        t = check_task(ProposedTask(**fields), owner, {"pvc-daily-routine#overview"})
        red.append({"name": name, "task": fields["description"], "verdict": t.verdict, "reason": t.issues[0] if t.issues else ""})

    results = json.loads((ROOT / "eval" / "results.json").read_text())
    tests = sum(1 for line in (ROOT / "evidence" / "pytest_output.txt").read_text().splitlines() if line.rstrip().endswith("PASSED"))
    import re as _re

    def caught(path):
        m = _re.search(r"Caught (\d+)/(\d+)", (ROOT / "evidence" / path).read_text())
        return {"caught": int(m.group(1)), "total": int(m.group(2))} if m else None
    red_ai = {"rules": caught("redteam_round2_rules_only.md"), "ai": caught("redteam_round2.md")}
    data = {
        "mode": "live" if args.live else "offline",
        "summary": results["summary"], "tests": tests,
        "chunks": len(Retriever().chunks), "documents": len(Retriever().documents),
        "scenarios": scenarios, "redTeam": red, "redTeamAI": red_ai,
    }
    out = ROOT / "docs" / "data.js"
    out.parent.mkdir(exist_ok=True)
    out.write_text("// Generated by `python -m eval.export_site_data`. Do not edit by hand.\n"
                   f"window.WW_DATA = {json.dumps(data, indent=1)};\n")
    print(f"Wrote {out.relative_to(ROOT)}: {len(scenarios)} scenarios, {len(red)} red-team cases, {tests} tests")


if __name__ == "__main__":
    main()
