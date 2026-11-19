"""Record reproducible evidence for grading.

Writes:
  ai_interactions.md         full agent traces (retrieval, plans, guardrail
                             verdicts, revision feedback) for three runs
  evidence/rag_before_after.txt
                             the same request planned with only the AVMA
                             overview vs. the full multi-source knowledge base

    python -m eval.record_evidence            # offline planner
    python -m eval.record_evidence --live     # Claude planner
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from pawpal_system import Owner, Pet, Task  # noqa: E402
from pawpal_ai import OfflinePlanner, PawPalAgent, Retriever, setup_logging  # noqa: E402
from pawpal_ai.models import BLOCKED  # noqa: E402
from pawpal_ai.retriever import load_documents  # noqa: E402

RUNS = [
    ("Normal day with a tight budget", 45,
     [("Mochi", "dog", 2, "very energetic", [("Morning walk", 30, "high", "08:00", "walk")]),
      ("Luna", "cat", 11, "senior, a little stiff", [])],
     "Busy morning. Luna is getting older, keep her routine gentle."),
    ("Medication reminder", 60, [("Mochi", "dog", 4, "", [])],
     "The vet put Mochi on a monthly heartworm preventive, today is the day."),
    ("Emergency", 60, [("Mochi", "dog", 2, "", [])],
     "Mochi ate chocolate an hour ago, plan his day."),
]


def make_owner(minutes, pets) -> Owner:
    owner = Owner("Jordan", available_minutes=minutes, day_start="07:30")
    for name, species, age, notes, tasks in pets:
        pet = Pet(name, species, age=age, notes=notes)
        for desc, dur, pri, time, cat in tasks:
            pet.add_task(Task(desc, dur, pri, time=time, category=cat))
        owner.add_pet(pet)
    return owner


def trace_markdown(title, owner, request, result) -> str:
    out = [f"### {title}", "",
           f"**Input:** {len(owner.pets)} pet(s) "
           f"({', '.join(f'{p.name}: {p.species}, {p.age}' for p in owner.pets)}), "
           f"{owner.available_minutes} min. Request: _\"{request}\"_", "",
           "**Trace:**", "", "```text"]
    for step in result.trace:
        out.append(f"[{step.stage:10}] {step.message}")
        if step.stage == "retrieve":
            out.append(f"{'':13}chunks: {', '.join(step.data.get('ids', []))}")
        if step.stage == "revise":
            for fb in step.data.get("feedback", []):
                out.append(f"{'':13}feedback -> {fb}")
    out.append("```")
    if result.stopped:
        out += ["", f"**Outcome:** stopped. {result.stop_reason}", ""]
        return "\n".join(out)
    out += ["", f"**Final proposals** (planner: {result.planner_source} {result.planner_model}, "
            f"confidence {result.confidence:.2f}, grounded {result.grounded_rate:.0%}):", "",
            "| Verdict | Pet | Task | Min | Priority | Cites | Issues |", "|---|---|---|---|---|---|---|"]
    for p in result.proposals:
        out.append(f"| {p.verdict} | {p.pet_name} | {p.description} | {p.duration_minutes} | {p.priority} | "
                   f"`{', '.join(p.citations)}` | {'; '.join(p.issues) or '—'} |")
    out += ["", "**Dry-run schedule:**", "", "```text"]
    out += [f"{s}  {t.pet_name:6} {t.description} ({t.duration_minutes} min) - {why}" for s, t, why in result.preview]
    out += ["```", ""]
    return "\n".join(out)


def rag_before_after(planner) -> str:
    owner = make_owner(60, [("Luna", "cat", 11, "senior", [])])
    request = "What should Luna's daily routine include?"
    docs = load_documents()
    rows = [f"RAG before/after · {datetime.now():%Y-%m-%d %H:%M} · planner: {getattr(planner, 'source', '?')}",
            f"Owner: Luna (cat, 11), 60 min. Request: {request!r}", ""]
    for label, subset in [("BEFORE: single source (AVMA overview only)", [d for d in docs if d.id == "avma-overview"]),
                          ("AFTER: multiple sources (AVMA + 8 Premier VetCare topic files)", docs)]:
        result = PawPalAgent(planner=planner, retriever=Retriever(subset)).run(make_owner(60, [("Luna", "cat", 11, "senior", [])]), request)
        rows.append(label)
        rows.append(f"  retrieved: {len(result.retrieved)} chunks from {len({c.doc.id for c in result.retrieved})} document(s)")
        if result.stopped:
            rows.append(f"  outcome: stopped - {result.stop_reason}")
        else:
            kept = [p for p in result.proposals if p.verdict != BLOCKED]
            rows.append(f"  proposals kept: {len(kept)} · confidence {result.confidence:.2f}")
            for p in kept:
                rows.append(f"    - {p.description} ({p.duration_minutes} min, {p.frequency}) <- {', '.join(p.citations)}")
        rows.append("")
    return "\n".join(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    setup_logging()
    if args.live:
        from pawpal_ai import ClaudePlanner
        planner = ClaudePlanner()
    else:
        planner = OfflinePlanner()
    agent = PawPalAgent(planner=planner, retriever=Retriever())

    sections = []
    for title, minutes, pets, request in RUNS:
        owner = make_owner(minutes, pets)
        sections.append(trace_markdown(title, owner, request, agent.run(owner, request)))

    mode = f"live ({planner.model})" if args.live else "offline"
    md = [
        "# AI Interactions Log", "",
        "Intermediate reasoning traces from the PawPal+ planning agent (stretch feature: agentic workflow).",
        f"Generated by `python -m eval.record_evidence{' --live' if args.live else ''}` on "
        f"{datetime.now():%Y-%m-%d %H:%M} · planner mode: **{mode}**.", "",
        "Each run shows the agent's decision chain: input guardrail → retrieval (chunk ids) → plan → "
        "guardrail verdicts → dry-run schedule → revision feedback sent back to the planner → final proposals. "
        "Every run is also logged line by line to `logs/pawpal_ai.log`.", "",
        "## Agent traces", "", *sections,
        "## RAG before/after", "",
        "See [evidence/rag_before_after.txt](evidence/rag_before_after.txt).", "",
    ]
    (ROOT / "ai_interactions.md").write_text("\n".join(md))
    (ROOT / "evidence").mkdir(exist_ok=True)
    (ROOT / "evidence" / "rag_before_after.txt").write_text(rag_before_after(planner))
    print("Wrote ai_interactions.md and evidence/rag_before_after.txt")


if __name__ == "__main__":
    main()
