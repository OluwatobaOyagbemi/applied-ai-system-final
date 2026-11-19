import os
from datetime import date

import streamlit as st
from dotenv import load_dotenv

from pawpal_ai import OfflinePlanner, PawPalAgent, apply_approved, default_planner, setup_logging
from pawpal_ai.health import APPETITE, BATHROOM, ENERGY, CheckIn, HealthLog, analyze, sample_week, vet_summary
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
# --- Daily check-in (health memory across days) ------------------------------
ui.section(3, "Daily check-in", "A 20-second check per pet. WhiskerWise watches the trend across days and tells you when it's worth calling the vet.")
health: HealthLog = st.session_state.setdefault("health", HealthLog())
if not owner.pets:
    st.caption("Add a pet first, then log how they're doing each day.")
else:
    names = [p.name for p in owner.pets]
    with st.form("checkin", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            ci_pet = st.selectbox("Pet", names, key="ci_pet")
            appetite = st.radio("Appetite", APPETITE, horizontal=True)
            energy = st.radio("Energy", ENERGY, horizontal=True)
        with c2:
            ci_day = st.date_input("Day", value=date.today(), max_value=date.today())
            bathroom = st.selectbox("Bathroom / litter", BATHROOM)
            vomited = st.checkbox("Vomited")
        ci_notes = st.text_input("Anything else? (optional)", placeholder="e.g. left half her breakfast", max_chars=300)
        if st.form_submit_button("Save check-in", type="primary"):
            health.add(CheckIn(ci_pet, ci_day, appetite, energy, bathroom, vomited, ci_notes))
            st.session_state.flash_health = f"Saved {ci_pet}'s check-in for {ci_day:%a %b %d}."
            st.rerun()
    if "flash_health" in st.session_state:
        st.success(st.session_state.pop("flash_health"))

    alerts = analyze(health, owner.pets)
    for a in alerts:
        text = f"{a.icon} {a.message}"
        (st.error if a.level == "urgent" else st.warning if a.level == "call_vet" else st.info)(text)

    if health.entries:
        st.dataframe(
            [{"Day": f"{e.day:%a %b %d}", "Pet": e.pet_name, "Appetite": e.appetite, "Energy": e.energy,
              "Bathroom": e.bathroom, "Vomited": "yes" if e.vomited else "", "Notes": e.notes}
             for e in sorted(health.entries, key=lambda e: (e.day, e.pet_name), reverse=True)
             if (date.today() - e.day).days < 7],
            hide_index=True, width="stretch",
        )
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("🧪 Load a sample week", width="stretch",
                     help="Seven days of check-ins where the first pet's appetite drops off at the end"):
            for row in sample_week(names[0]):
                health.add(row)
            st.rerun()
    with c2:
        summary_pet = owner.get_pet(names[0]) if len(names) == 1 else None
        pick = summary_pet or owner.get_pet(st.session_state.get("ci_pet", names[0]))
        st.download_button("📄 Vet summary", vet_summary(health, pick, alerts, owner.get_all_tasks()),
                           file_name=f"{pick.name.lower()}_health_summary.md", width="stretch",
                           help=f"One-page summary of {pick.name}'s last 14 days, to bring to the vet")
    with c3:
        st.download_button("💾 Save history", health.to_json(), file_name="whiskerwise_checkins.json",
                           width="stretch", help="Download your check-ins; upload them next time to keep the history")
    uploaded = st.file_uploader("Restore saved check-ins", type=["json"], label_visibility="collapsed")
    if uploaded is not None and st.session_state.get("restored") != uploaded.name:
        try:
            for row in HealthLog.from_json(uploaded.read().decode("utf-8")).entries:
                if row.pet_name in names:
                    health.add(row)
            st.session_state.restored = uploaded.name
            st.rerun()
        except (ValueError, KeyError, TypeError) as err:
            st.error(f"Couldn't read that file: {err}")

ui.section(4, "Ask the AI", "Retrieves vet guidance, drafts cited tasks, checks them, and waits for your approval.")


def _code_version() -> str:
    """Changes whenever the AI code changes, so cached agents are rebuilt after a
    redeploy instead of an old agent being reused with new app code."""
    from pathlib import Path
    files = sorted((Path(__file__).parent / "pawpal_ai").glob("*.py")) + [Path(__file__).parent / "pawpal_system.py"]
    return "-".join(f"{f.name}:{f.stat().st_mtime_ns}" for f in files if f.exists())


CODE_VERSION = _code_version()


@st.cache_resource
def get_agent(key_present: bool, code_version: str) -> PawPalAgent:
    # Cached per key state and code version: adding a key in Secrets, or a new
    # deploy, rebuilds the agent instead of reusing a stale one.
    return PawPalAgent(planner=default_planner())


@st.cache_resource
def get_offline_agent(code_version: str) -> PawPalAgent:
    return PawPalAgent(planner=OfflinePlanner(), emergency_check=None, task_reviewer=None)


@st.cache_resource
def usage_counter() -> dict:
    """Claude plans used today, shared by every visitor of this app instance."""
    return {"day": date.today(), "count": 0}


usage = usage_counter()
if usage["day"] != date.today():
    usage.update(day=date.today(), count=0)
session_used = st.session_state.setdefault("ai_used", 0)

_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
agent = get_agent(_key.startswith("sk-ant-") and "..." not in _key, CODE_VERSION)
claude_available = agent.planner.source == "claude"
over_cap = usage["count"] >= DAILY_AI_LIMIT or session_used >= SESSION_AI_LIMIT
using_claude = claude_available and not over_cap
if using_claude:
    left = min(DAILY_AI_LIMIT - usage["count"], SESSION_AI_LIMIT - session_used)
    st.caption(f"Using Claude (`{agent.planner.model}`) with the vet-sourced knowledge base · "
               f"{left} AI plan(s) left for you today.")
elif claude_available:
    agent = get_offline_agent(CODE_VERSION)
    st.caption("You've reached today's Claude limit for this public demo, so suggestions now come from "
               "the offline planner (same knowledge base and guardrails, no LLM).")
else:
    agent = get_offline_agent(CODE_VERSION)
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
            result = agent.run(owner, request, health_log=st.session_state.get("health"))
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
            if result.source_conflicts:
                with st.container(border=True):
                    st.markdown("**⚖️ The sources disagree.** WhiskerWise won't pick a side; ask your vet which applies.")
                    for conflict in result.source_conflicts:
                        st.markdown(f"**{conflict.topic.capitalize()}**")
                        for claim in conflict.claims:
                            stage = f" (for {claim.stage} pets)" if claim.stage else ""
                            st.markdown(f"- *{claim.source}*{stage}: “{claim.sentence}” `{claim.chunk_id}`")

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
                st.session_state.setdefault("ai_task_ids", set()).update(id(t) for t in added)
                st.session_state.flash = (
                    f"Added {len(added)} AI-suggested task(s). They're in step 5 below, marked 🤖 AI."
                    + (f" Skipped {len(blocked_picked)} blocked task(s)." if blocked_picked else "")
                )
                del st.session_state.ai_result
                st.rerun()
            if col2.button("Discard suggestions", width="stretch"):
                del st.session_state.ai_result
                st.rerun()


# --- Tasks ------------------------------------------------------------------
ui.section(5, "Tasks", "Everything on your list: approved AI suggestions and tasks you add yourself.")
if not owner.pets:
    st.caption("Add a pet before adding tasks.")
else:
    scheduler = Scheduler(owner)
    if "flash" in st.session_state:
        st.success(st.session_state.pop("flash"))

    # --- The task list comes first, so approved AI suggestions are easy to find ---
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
    ai_added = st.session_state.setdefault("ai_task_ids", set())

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
                    "From": "🤖 AI" if id(t) in ai_added else "✍️ You",
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
        st.info("No tasks yet. Ask the AI in step 4 and click **Add approved tasks**, or add your own below.")

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
                if next_task is not None and id(done) in ai_added:
                    ai_added.add(id(next_task))
                st.session_state.flash = (
                    f"Completed '{done.description}' for {done.pet_name}. "
                    + (f"Next {done.frequency} copy is due {next_task.due_date:%a %b %d}."
                       if next_task else "One-time task, so it won't repeat.")
                )
                st.rerun()

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

    # --- Add your own task. The form clears after submit, so the pet choice is
    # remembered in session state; otherwise it would jump back to the first pet.
    pet_names = [p.name for p in owner.pets]
    last_pet = st.session_state.get("last_task_pet")
    with st.expander("➕ Add your own task", expanded=not owner.get_all_tasks()):
        with st.form("add_task", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                task_pet = st.selectbox("Pet", pet_names,
                                        index=pet_names.index(last_pet) if last_pet in pet_names else 0)
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
            if st.form_submit_button("Add task", type="primary"):
                st.session_state.last_task_pet = task_pet
                if not description.strip():
                    st.error(f"Enter a task description for {task_pet}.")
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
                        st.session_state.flash = f"Added '{description.strip()}' for {task_pet}."
                        st.rerun()
                    except ValueError as err:
                        st.error(str(err))


# --- Schedule ---------------------------------------------------------------
ui.section(6, "Today's schedule", "Fits the highest-priority tasks into your minutes, with a reason for each.")
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
