"""Specialization stretch: does the few-shot, style-constrained planner measurably
differ from the baseline prompt?

Runs the planned (non-emergency) scenarios from eval/cases.json through the
agent twice, once per planner style, and measures the output. Writes
evidence/specialization.md. Live only (it compares Claude prompts).

    python -m eval.compare_styles
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from pawpal_ai import ClaudePlanner, PawPalAgent, Retriever, setup_logging  # noqa: E402
from pawpal_ai.models import BLOCKED  # noqa: E402

from eval.run_eval import build_owner  # noqa: E402

SCENARIOS = ["dog-basic", "cat-senior", "multi-tight-budget", "meds-reminder", "existing-walk", "hard-non-english"]
VERBS = {"refresh", "scoop", "clean", "run", "walk", "give", "feed", "brush", "play", "check", "book", "bathe",
         "pick", "vacuum", "groom", "trim", "wipe", "change", "fill", "serve", "confirm", "review", "schedule",
         "take", "do", "offer", "replace", "wash", "provide", "inspect", "monitor", "rinse", "store", "keep",
         "put", "set", "prepare", "apply", "remind", "call", "measure", "weigh", "train", "practice", "examine"}
FREQ = re.compile(r"\b(daily|every day|each day|weekly|every week|monthly|every month|twice|once|annual|yearly|"
                  r"every \d|times a|a day|a week|a year|year-round)\b", re.I)


def words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z'-]*", text)


def measure(proposals, pet_names) -> dict:
    kept = [p for p in proposals if p.verdict != BLOCKED]
    if not kept:
        return {}
    d_len = [len(words(p.description)) for p in kept]
    r_len = [len(words(p.rationale)) for p in kept]
    pct = lambda xs: round(100 * sum(xs) / len(xs))  # noqa: E731
    return {
        "tasks": len(kept),
        "desc_words": round(statistics.mean(d_len), 1),
        "desc_le5": pct([n <= 5 for n in d_len]),
        "verb_first": pct([bool(words(p.description)) and words(p.description)[0].lower() in VERBS for p in kept]),
        "pet_name_in_desc": pct([any(n.lower() in p.description.lower() for n in pet_names) for p in kept]),
        "rat_words": round(statistics.mean(r_len), 1),
        "rat_le18": pct([n <= 18 for n in r_len]),
        "freq_stated": pct([bool(FREQ.search(p.rationale)) for p in kept]),
    }


def main() -> None:
    load_dotenv(ROOT / ".env")
    setup_logging()
    cases = {c["id"]: c for c in json.loads((ROOT / "eval" / "cases.json").read_text())}
    retriever = Retriever()
    results: dict[str, list[dict]] = {}
    examples: dict[str, list[str]] = {}
    for style in ("baseline", "specialized"):
        agent = PawPalAgent(planner=ClaudePlanner(style=style), retriever=retriever, emergency_check=None)
        results[style] = []
        for cid in SCENARIOS:
            owner = build_owner(cases[cid]["owner"])
            r = agent.run(owner, cases[cid]["request"])
            m = measure(r.proposals, [p.name for p in owner.pets])
            if m:
                m["rounds"] = r.rounds
                m["blocked"] = r.counts[BLOCKED]
                results[style].append(m)
            if cid == "dog-basic":
                examples[style] = [f"{p.description}  ->  {p.rationale}" for p in r.proposals if p.verdict != BLOCKED][:4]

    def avg(style, key):
        vals = [m[key] for m in results[style]]
        return round(statistics.mean(vals), 1) if vals else 0

    rows = [
        ("Task name length (words, avg)", "desc_words", "lower is tighter"),
        ("Task names of 5 words or fewer (%)", "desc_le5", "style rule"),
        ("Task names starting with a verb (%)", "verb_first", "style rule"),
        ("Task names repeating the pet name (%)", "pet_name_in_desc", "lower is better"),
        ("Explanation length (words, avg)", "rat_words", "lower is tighter"),
        ("Explanations of 18 words or fewer (%)", "rat_le18", "style rule"),
        ("Explanations stating a frequency (%)", "freq_stated", "style rule"),
        ("Tasks kept per scenario (avg)", "tasks", "context"),
        ("Planning rounds (avg)", "rounds", "context"),
        ("Tasks blocked by guardrails (avg)", "blocked", "should stay 0"),
    ]
    lines = [
        "# Specialization: few-shot, style-constrained planner vs. baseline", "",
        f"_Generated {datetime.now():%Y-%m-%d %H:%M} by `python -m eval.compare_styles` · model: "
        f"{ClaudePlanner(style='baseline').model} · {len(SCENARIOS)} planned scenarios per style_", "",
        "**Baseline:** the planner's normal system prompt. **Specialized:** the same prompt plus three few-shot "
        "example tasks and house-style rules (verb-first task names of 2–5 words with no pet name; one-sentence "
        "explanations of at most 18 words that state the source's frequency). See `SPECIALIZED_STYLE` in "
        "`pawpal_ai/planner.py`.", "",
        "| Metric | Baseline | Specialized | Note |", "|---|---|---|---|",
    ]
    for label, key, note in rows:
        lines.append(f"| {label} | {avg('baseline', key)} | {avg('specialized', key)} | {note} |")
    lines += ["", "**Example output** (`dog-basic`, first 4 kept tasks):", "", "Baseline:", "", "```text"]
    lines += examples.get("baseline", ["(none)"]) + ["```", "", "Specialized:", "", "```text"]
    lines += examples.get("specialized", ["(none)"]) + ["```", ""]
    (ROOT / "evidence").mkdir(exist_ok=True)
    (ROOT / "evidence" / "specialization.md").write_text("\n".join(lines))
    (ROOT / "evidence" / "specialization.json").write_text(json.dumps(results, indent=2))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
