import os
from datetime import date

import streamlit as st
from dotenv import load_dotenv

from pawpal_ai import OfflinePlanner, PawPalAgent, apply_approved, default_planner, setup_logging
from pawpal_ai.models import BLOCKED, NEEDS_REVIEW
from pawpal_system import Owner, Pet, Scheduler, Task
import ui_theme as ui

load_dotenv()
# On Streamlit Community Cloud the key lives in the app's Secrets, never in the repo.
def _key_from_secrets() -> str:
    """Find ANTHROPIC_API_KEY at the top level of Secrets or inside any [section]."""
    try:
        if "ANTHROPIC_API_KEY" in st.secrets:
            return str(st.secrets["ANTHROPIC_API_KEY"]).strip().strip('"').strip("'")
        for value in st.secrets.values():
            if hasattr(value, "get") and value.get("ANTHROPIC_API_KEY"):
                return str(value["ANTHROPIC_API_KEY"]).strip().strip('"').strip("'")
    except Exception:   # no secrets file (local run) or unreadable TOML
        pass
    return ""


_secret_key = _key_from_secrets()
if _secret_key and os.getenv("ANTHROPIC_API_KEY", "").strip() in ("", "sk-ant-..."):
    os.environ["ANTHROPIC_API_KEY"] = _secret_key
setup_logging()

# Usage caps for the public demo (CODE guardrail on cost). After either cap is
# hit, the app keeps working with the offline planner.
DAILY_AI_LIMIT = int(os.getenv("WW_DAILY_AI_LIMIT", "30"))
SESSION_AI_LIMIT = int(os.getenv("WW_SESSION_AI_LIMIT", "5"))

st.set_page_config(page_title="WhiskerWise", page_icon="🐾", layout="centered")

ui.apply_theme()
ui.hero()

# --- App memory -------------------------------------------------------------
# Streamlit reruns this whole script on every click. Store the Owner in
# st.session_state (a dict that survives reruns) and only create it once.
if "owner" not in st.session_state:
    st.session_state.owner = Owner("Jordan")

owner: Owner = st.session_state.owner


def load_sample_pets() -> None:
    """One-click sample data so first-time visitors can try the AI planner."""
    sample = Owner("Jordan", available_minutes=60, day_start="07:30")
    sample.add_pet(Pet("Mochi", "dog", age=2, notes="very energetic"))
    sample.add_pet(Pet("Luna", "cat", age=11, notes="senior, a little stiff"))
    sample.get_pet("Mochi").add_task(Task("Morning walk", 30, "high", time="08:00", category="walk"))
    st.session_state.owner = sample
    st.session_state.pop("ai_result", None)


if not owner.pets:
    st.info("👋 New here? Load two sample pets and try the AI planner in one click.")
    if st.button("🐶🐱 Load sample pets", type="primary"):
        load_sample_pets()
        st.rerun()

# --- Owner ------------------------------------------------------------------
ui.section(1, "Your day", "Who's planning, how much time you have, and when the day starts.")
col1, col2, col3 = st.columns(3)
with col1:
    owner.name = st.text_input("Owner name", value=owner.name)
with col2:
    owner.available_minutes = int(
        st.number_input("Minutes available today", min_value=0, max_value=1440,
                        value=owner.available_minutes, step=5)
    )
with col3:
    day_start = st.time_input("Day starts at", value=owner.day_start, step=900)
    owner.day_start = day_start.strftime("%H:%M")


# --- Pets -------------------------------------------------------------------
ui.section(2, "Your pets", "Add each pet. Notes help the AI, e.g. “senior, a little stiff”.")
with st.form("add_pet", clear_on_submit=True):
    col1, col2, col3 = st.columns(3)
    with col1:
        pet_name = st.text_input("Pet name")
    with col2:
        species = st.selectbox("Species", ["dog", "cat", "other"])
    with col3:
        age = st.number_input("Age", min_value=0, max_value=40, value=0)
    notes = st.text_input("Notes for the AI (optional)", placeholder="e.g. arthritis, very energetic, indoor only")
    if st.form_submit_button("Add pet"):
        if not pet_name.strip():
            st.error("Enter a pet name.")
        else:
            try:
                owner.add_pet(Pet(pet_name.strip(), species, age=int(age), notes=notes.strip()))
                st.success(f"Added {pet_name.strip()}.")
            except ValueError as err:
                st.error(str(err))

if owner.pets:
    st.dataframe(
        [{"Name": p.name, "Species": p.species, "Age": p.age, "Tasks": len(p.tasks)}
         for p in owner.pets],
        hide_index=True, width="stretch",
    )
else:
    st.info("No pets yet. Add one above.")


# --- AI Care Planner ----------------------------------------------------------
# Retrieve guidelines -> Claude proposes cited tasks -> guardrails check them ->
# dry-run schedule -> revise. Nothing is added until the owner approves it here.
ui.section(3, "Ask the AI", "Retrieves vet guidance, drafts cited tasks, checks them, and waits for your approval.")


@st.cache_resource
def get_agent(key_present: bool) -> PawPalAgent:
    # Cached per key state, so adding a key in Secrets later rebuilds the agent
    # instead of reusing the offline one cached before the key existed.
    return PawPalAgent(planner=default_planner())


@st.cache_resource
def get_offline_agent() -> PawPalAgent:
    return PawPalAgent(planner=OfflinePlanner(), emergency_check=None)


@st.cache_resource
def usage_counter() -> dict:
    """Claude plans used today, shared by every visitor of this app instance."""
    return {"day": date.today(), "count": 0}


usage = usage_counter()
if usage["day"] != date.today():
    usage.update(day=date.today(), count=0)
session_used = st.session_state.setdefault("ai_used", 0)

_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
agent = get_agent(_key.startswith("sk-ant-") and "..." not in _key)
claude_available = agent.planner.source == "claude"
over_cap = usage["count"] >= DAILY_AI_LIMIT or session_used >= SESSION_AI_LIMIT
using_claude = claude_available and not over_cap
if using_claude:
    left = min(DAILY_AI_LIMIT - usage["count"], SESSION_AI_LIMIT - session_used)
    st.caption(f"Using Claude (`{agent.planner.model}`) with the vet-sourced knowledge base · "
               f"{left} AI plan(s) left for you today.")
elif claude_available:
    agent = get_offline_agent()
    st.caption("You've reached today's Claude limit for this public demo, so suggestions now come from "
               "the offline planner (same knowledge base and guardrails, no LLM).")
else:
    agent = get_offline_agent()
    st.caption("Running in offline mode (no Claude key configured): suggestions come straight from the "
               "vet-sourced knowledge base, with the same guardrails. Running it yourself? Add "
               "`ANTHROPIC_API_KEY` to `.env` to use Claude.")

if not owner.pets:
    st.caption("Add a pet first, then ask the AI to suggest a care plan.")
else:
    request = st.text_area(
        "Anything the AI should know today? (optional)",
        placeholder="e.g. Busy morning, Luna is getting older, Mochi's vet started a monthly heartworm preventive",
        max_chars=2000,
    )
    if st.button("✨ Suggest a plan", type="primary"):
        with st.status("Planning…", expanded=True) as status:
            result = agent.run(owner, request)
            if using_claude:   # every Claude-backed run counts, including emergency stops
                usage["count"] += 1
                st.session_state.ai_used = session_used + 1
            for step in result.trace:
                st.write(f"**{step.stage}** · {step.message}")
            status.update(label="Stopped" if result.stopped else "Plan ready for your review",
                          state="error" if result.stopped else "complete", expanded=False)
        st.session_state.ai_result = result

    result = st.session_state.get("ai_result")
    if result is not None:
        if result.stopped:
            st.error(result.stop_reason)
        if result.caution:
            st.warning(f"⚠️ {result.caution}")
        elif not result.proposals:
            st.info("The AI didn't find anything new to suggest.")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Confidence", f"{result.confidence:.0%}")
            c2.metric("Planning rounds", result.rounds)
            c3.metric("Grounded in sources", f"{result.grounded_rate:.0%}")
            if result.planner_notes:
                st.caption(f"Planner notes: {result.planner_notes}")

            icon = {BLOCKED: "⛔ blocked", NEEDS_REVIEW: "⚠️ check with vet"}
            rows = [
                {
                    "Add": p.verdict == "ok",
                    "Pet": p.pet_name,
                    "Task": p.description,
                    "Min": p.duration_minutes,
                    "Priority": p.priority,
                    "Frequency": p.frequency,
                    "Status": icon.get(p.verdict, "✅ ok"),
                    "Why": p.rationale + (f" [{'; '.join(p.issues)}]" if p.issues else ""),
                    "Sources": ", ".join(p.citations),
                }
                for p in result.proposals
            ]
            st.markdown("**Review the suggestions.** Tick the ones to add. Vet-sensitive tasks start "
                        "unticked, and blocked tasks can't be added.")
            edited = st.data_editor(
                rows, hide_index=True, width="stretch", key="ai_review",
                disabled=["Pet", "Task", "Min", "Priority", "Frequency", "Status", "Why", "Sources"],
                column_config={"Add": st.column_config.CheckboxColumn(width="small")},
            )
            with st.expander(f"📚 {len(result.retrieved)} guideline excerpts the AI used"):
                for c in result.retrieved:
                    st.markdown(f"**`{c.id}`** · {c.doc.title} — {c.heading}")
                    st.caption(f"{c.doc.source}\n\n{c.text[:400]}{'…' if len(c.text) > 400 else ''}")

            col1, col2 = st.columns(2)
            if col1.button("Add approved tasks", width="stretch"):
                picked = [i for i, row in enumerate(edited) if row["Add"]]
                blocked_picked = [i for i in picked if result.proposals[i].verdict == BLOCKED]
                added = apply_approved(owner, result.proposals, picked)
                st.session_state.flash = (
                    f"Added {len(added)} AI-suggested task(s)."
                    + (f" Skipped {len(blocked_picked)} blocked task(s)." if blocked_picked else "")
                )
                del st.session_state.ai_result
                st.rerun()
            if col2.button("Discard suggestions", width="stretch"):
                del st.session_state.ai_result
                st.rerun()


# --- Tasks ------------------------------------------------------------------
ui.section(4, "Tasks", "Approved AI suggestions and your own tasks. Mark done, filter, sort.")
if not owner.pets:
    st.caption("Add a pet before adding tasks.")
else:
    with st.form("add_task", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            task_pet = st.selectbox("Pet", [p.name for p in owner.pets])
            description = st.text_input("Task", placeholder="e.g. Morning walk")
            category = st.selectbox(
                "Category", ["walk", "feeding", "meds", "enrichment", "grooming", "cleaning", "general"]
            )
        with col2:
            duration = st.number_input("Duration (minutes)", min_value=1, max_value=240, value=20)
            priority = st.selectbox("Priority", ["high", "medium", "low"])
            frequency = st.selectbox("Frequency", ["daily", "weekly", "once"])
        has_time = st.checkbox("Set a preferred time")
        preferred = st.time_input("Preferred time", value="08:00", step=900)
        if st.form_submit_button("Add task"):
            if not description.strip():
                st.error("Enter a task description.")
            else:
                try:
                    owner.get_pet(task_pet).add_task(
                        Task(
                            description.strip(),
                            int(duration),
                            priority,
                            frequency=frequency,
                            time=preferred.strftime("%H:%M") if has_time else None,
                            category=category,
                        )
                    )
                    st.success(f"Added '{description.strip()}' for {task_pet}.")
                except ValueError as err:
                    st.error(str(err))

    scheduler = Scheduler(owner)

    # --- Mark complete (recurring tasks get their next copy automatically) ---
    due_now = scheduler.sort_by_time(scheduler.collect_tasks())
    if due_now:
        col1, col2 = st.columns([3, 1], vertical_alignment="bottom")
        with col1:
            labels = [
                f"{t.pet_name}: {t.description} ({t.time or 'flexible'}, {t.frequency})"
                for t in due_now
            ]
            pick = st.selectbox("Mark a task complete", labels)
        with col2:
            if st.button("Complete", width="stretch"):
                done = due_now[labels.index(pick)]
                next_task = scheduler.mark_task_complete(done)
                st.session_state.flash = (
                    f"Completed '{done.description}' for {done.pet_name}. "
                    + (f"Next {done.frequency} copy is due {next_task.due_date:%a %b %d}."
                       if next_task else "One-time task, so it won't repeat.")
                )
                st.rerun()
    if "flash" in st.session_state:
        st.success(st.session_state.pop("flash"))

    # --- Filter and sort the task list ---
    col1, col2, col3 = st.columns(3)
    with col1:
        pet_filter = st.selectbox("Show pet", ["All pets"] + [p.name for p in owner.pets])
    with col2:
        status_filter = st.selectbox("Status", ["All", "Not done", "Done"])
    with col3:
        sort_by = st.selectbox("Sort by", ["Time", "Priority"])

    shown = scheduler.filter_tasks(
        pet_name=None if pet_filter == "All pets" else pet_filter,
        completed={"All": None, "Not done": False, "Done": True}[status_filter],
    )
    shown = scheduler.sort_by_time(shown) if sort_by == "Time" else scheduler.sort_by_priority(shown)

    if shown:
        st.dataframe(
            [
                {
                    "Time": t.time or "flexible",
                    "Pet": t.pet_name,
                    "Task": t.description,
                    "Min": t.duration_minutes,
                    "Priority": t.priority,
                    "Frequency": t.frequency,
                    "Status": "done" if t.completed
                    else "due" if t.is_due_today() else f"next due {t.due_date:%a %b %d}",
                }
                for t in shown
            ],
            hide_index=True, width="stretch",
        )
    elif owner.get_all_tasks():
        st.info("No tasks match these filters.")
    else:
        st.info("No tasks yet. Add one above.")

    # --- Conflicts: shown live, in one block, with what happens and how to fix it ---
    conflicts = scheduler.detect_conflicts()
    if conflicts:
        count = f"{len(conflicts)} time conflict" + ("s" if len(conflicts) > 1 else "")
        st.warning(
            f"**⚠️ {count}.** You can't do two things at once, so the schedule will start "
            "the later task when the earlier one ends. To keep both at their preferred "
            "times, change one task's time.\n\n"
            + "\n".join(f"- {c}" for c in conflicts)
        )


# --- Schedule ---------------------------------------------------------------
ui.section(5, "Today's schedule", "Fits the highest-priority tasks into your minutes, with a reason for each.")
if st.button("Generate schedule", type="primary"):
    scheduler = Scheduler(owner)
    plan = scheduler.generate_plan()

    if not plan:
        st.info("Nothing to schedule. Add tasks, or check your available minutes.")
    else:
        used = sum(task.duration_minutes for _, task, _ in plan)
        moved = sum("moved" in reason for _, _, reason in plan)
        c1, c2, c3 = st.columns(3)
        c1.metric("Tasks planned", len(plan))
        c2.metric("Minutes used", f"{used} / {owner.available_minutes}")
        c3.metric("Moved for conflicts", moved)
        st.dataframe(
            [
                {"Time": start, "Pet": task.pet_name, "Task": task.description,
                 "Min": task.duration_minutes, "Priority": task.priority, "Why": reason}
                for start, task, reason in plan
            ],
            hide_index=True, width="stretch",
        )
        if not scheduler.skipped:
            st.success("Everything due today fits in your available time.")

    if scheduler.skipped:
        st.warning(
            f"**{len(scheduler.skipped)} task(s) didn't fit** in {owner.available_minutes} minutes. "
            "Add more time or lower another task's priority to fit them in.\n\n"
            + "\n".join(f"- {t.description} ({t.pet_name}): {r}" for t, r in scheduler.skipped)
        )

ui.footer()
