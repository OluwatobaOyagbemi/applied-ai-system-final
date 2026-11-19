"""Terminal demo of the AI planner.

    python -m pawpal_ai                                  # built-in sample request
    python -m pawpal_ai "Busy morning, Luna is getting older"
    python -m pawpal_ai --offline "..."                  # force the offline planner
"""

from __future__ import annotations

import argparse

from dotenv import load_dotenv

from pawpal_system import Owner, Pet, Task

from . import OfflinePlanner, PawPalAgent, apply_approved, default_planner, setup_logging
from .models import BLOCKED, NEEDS_REVIEW


def sample_owner() -> Owner:
    owner = Owner("Jordan", available_minutes=90, day_start="07:30")
    owner.add_pet(Pet("Mochi", "dog", age=2, notes="very energetic"))
    owner.add_pet(Pet("Luna", "cat", age=11, notes="senior, a little stiff"))
    owner.get_pet("Mochi").add_task(Task("Morning walk", 30, "high", time="08:00", category="walk"))
    return owner


def main() -> None:
    parser = argparse.ArgumentParser(description="PawPal+ AI planner demo")
    parser.add_argument("request", nargs="?", default="Busy morning. Luna is getting older, keep her routine gentle.")
    parser.add_argument("--offline", action="store_true", help="use the offline planner even if an API key is set")
    parser.add_argument("--approve", action="store_true", help="auto-approve tasks marked ok and print the final schedule")
    args = parser.parse_args()

    load_dotenv()
    log_file = setup_logging()
    owner = sample_owner()
    agent = PawPalAgent(planner=OfflinePlanner() if args.offline else default_planner())

    print(f"Request: {args.request!r}")
    print(f"Pets: {', '.join(f'{p.name} ({p.species}, {p.age})' for p in owner.pets)} · "
          f"{owner.available_minutes} min from {owner.day_start}\n")
    result = agent.run(owner, args.request)
    for step in result.trace:
        print(f"  [{step.stage:10}] {step.message}")
    if result.stopped:
        print(f"\n⛔ {result.stop_reason}")
        return

    print(f"\nPlanner: {result.planner_source} {result.planner_model} · confidence {result.confidence:.2f} · "
          f"grounded {result.grounded_rate:.0%}")
    if result.planner_notes:
        print(f"Notes: {result.planner_notes}")
    print("\nProposals:")
    mark = {BLOCKED: "⛔ blocked", NEEDS_REVIEW: "⚠️  review"}
    for p in result.proposals:
        print(f"  {mark.get(p.verdict, '✅ ok'):11} {p.pet_name:6} {p.description:38} {p.duration_minutes:3} min "
              f"{p.priority:6} ← {', '.join(p.citations)}")
        for issue in p.issues:
            print(f"  {'':11} ↳ {issue}")

    if args.approve:
        ok = [i for i, p in enumerate(result.proposals) if p.verdict == "ok"]
        apply_approved(owner, result.proposals, ok)
        from pawpal_system import Scheduler
        print("\n" + Scheduler(owner).explain_plan())
    print("\nLog: logs/pawpal_ai.log")


if __name__ == "__main__":
    main()
