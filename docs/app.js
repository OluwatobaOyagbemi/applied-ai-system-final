/* WhiskerWise landing page interactions. Data comes from data.js (real recorded runs). */
(() => {
  "use strict";
  const D = window.WW_DATA || { scenarios: [], redTeam: [], summary: {}, tests: 0 };
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $ = (sel, root = document) => root.querySelector(sel);
  const el = (tag, cls, html) => { const n = document.createElement(tag); if (cls) n.className = cls; if (html != null) n.innerHTML = html; return n; };
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const wait = (ms) => new Promise((r) => setTimeout(r, reduced ? 0 : ms));
  const REPO = "https://github.com/OluwatobaOyagbemi/applied-ai-system-final/blob/main/";

  /* ---------- reveal on scroll ---------- */
  const io = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (!e.isIntersecting) return;
      const kids = e.target.parentElement ? [...e.target.parentElement.children].filter((c) => c.classList.contains("reveal")) : [];
      const i = Math.max(0, kids.indexOf(e.target));
      e.target.style.transitionDelay = `${Math.min(i, 6) * 70}ms`;
      e.target.classList.add("in");
      io.unobserve(e.target);
    });
  }, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });
  document.querySelectorAll(".reveal").forEach((n) => io.observe(n));

  /* ---------- paw-print trail in the hero ---------- */
  const paws = $("#paws");
  if (paws) {
    const pad = "M0,-14 C9,-14 13,-4 11,4 C9,12 -9,12 -11,4 C-13,-4 -9,-14 0,-14 Z";
    const toe = (x, y) => `<ellipse cx="${x}" cy="${y}" rx="4.2" ry="5.6"/>`;
    const pawSvg = `<path d="${pad}"/>${toe(-12, -20)}${toe(-4, -27)}${toe(5, -27)}${toe(13, -20)}`;
    const pts = [[70, 540], [120, 500], [150, 445], [205, 415], [230, 355], [290, 330], [310, 270], [370, 250], [385, 190], [445, 170], [460, 110], [520, 90]];
    pts.forEach(([x, y], i) => {
      const flip = i % 2 ? 12 : -12;
      const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
      g.setAttribute("transform", `translate(${x + flip},${y}) rotate(35) scale(.9)`);
      g.innerHTML = `<g class="paw" style="animation-delay:${i * 0.35}s;transform-origin:center">${pawSvg}</g>`;
      paws.appendChild(g);
    });
  }

  /* ---------- pipeline ---------- */
  const STEPS = [
    { icon: "💬", name: "Ask", sub: "your pets + time", title: "You describe the day",
      body: "Pets (species, age, notes), the minutes you have, and an optional request like “busy morning, Luna is getting older”.",
      file: "app.py" },
    { icon: "🛑", name: "Screen", sub: "input guardrail", title: "Emergencies stop here",
      body: "Words like “ate chocolate”, “seizure” or “collapsed” halt everything before any AI call, and you're sent to a vet and the ASPCA poison line. Oversized input is rejected too.",
      file: "pawpal_ai/guardrails.py" },
    { icon: "🔎", name: "Fetch", sub: "RAG retrieval", title: "Look it up first",
      body: `BM25 search over ${D.chunks || 30} chunks from ${D.documents || 9} vet-sourced documents, with one query per pet (species, life stage, notes) and other species filtered out.`,
      file: "pawpal_ai/retriever.py" },
    { icon: "🧠", name: "Plan", sub: "Claude", title: "Claude drafts cited tasks",
      body: "Claude gets the excerpts and returns strict JSON (structured outputs). Every task must name the excerpt ids it relied on. No key? A deterministic offline planner takes over.",
      file: "pawpal_ai/planner.py" },
    { icon: "🛡️", name: "Check", sub: "task guardrails", title: "Every task is verified in code",
      body: "Blocks missing or fake citations, drug names, doses, toxic treats, wrong-species tasks, duplicates and impossible times. Meds are flagged “check with vet”.",
      file: "pawpal_ai/guardrails.py" },
    { icon: "🗓️", name: "Dry-run", sub: "real scheduler", title: "Test the plan before showing it",
      body: "The agent runs the tested Module 2 scheduler on a copy of your pets. Over budget or blocked? That feedback goes back to the planner, up to 3 rounds.",
      file: "pawpal_ai/agent.py" },
    { icon: "🙋", name: "Approve", sub: "human in the loop", title: "Nothing is added without you",
      body: "Safe tasks start ticked, vet-sensitive ones unticked, and blocked ones can't be added at all. Only then does your schedule change.",
      file: "app.py" },
  ];
  const pipe = $(".pipeline"), detail = $("#step-detail");
  STEPS.forEach((s, i) => {
    const b = el("button", "step");
    b.type = "button"; b.setAttribute("role", "tab"); b.setAttribute("aria-selected", "false"); b.setAttribute("aria-controls", "step-detail");
    b.innerHTML = `<span class="ring"><span>${s.icon}</span></span><div><b>${s.name}</b><small>${s.sub}</small></div>`;
    b.addEventListener("click", () => selectStep(i, true));
    b.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight" || e.key === "ArrowDown") { e.preventDefault(); selectStep((i + 1) % STEPS.length, true, true); }
      if (e.key === "ArrowLeft" || e.key === "ArrowUp") { e.preventDefault(); selectStep((i - 1 + STEPS.length) % STEPS.length, true, true); }
    });
    pipe.appendChild(b);
  });
  let stepTimer = null, current = -1;
  function selectStep(i, user = false, focus = false) {
    const btns = pipe.querySelectorAll(".step");
    btns.forEach((b, j) => { b.setAttribute("aria-selected", String(j === i)); b.tabIndex = j === i ? 0 : -1; });
    if (focus) btns[i].focus();
    const s = STEPS[i];
    detail.innerHTML = `<div class="big">${s.icon}</div><h3>${i + 1}. ${s.title}</h3><p>${s.body}</p><a href="${REPO}${s.file}" target="_blank" rel="noopener"><code class="file">${s.file}</code></a>`;
    detail.classList.remove("swap"); void detail.offsetWidth; detail.classList.add("swap");
    current = i;
    if (user && stepTimer) { clearInterval(stepTimer); stepTimer = null; }
  }
  selectStep(0);
  if (!reduced) {
    const pipeObs = new IntersectionObserver(([e]) => {
      if (e.isIntersecting && !stepTimer) stepTimer = setInterval(() => selectStep((current + 1) % STEPS.length), 3200);
      if (!e.isIntersecting && stepTimer) { clearInterval(stepTimer); stepTimer = null; }
    }, { threshold: 0.4 });
    pipeObs.observe(pipe);
    pipe.addEventListener("click", () => pipeObs.disconnect());   // user took over: stop auto-advancing
  }

  /* ---------- demo player ---------- */
  const stories = $("#stories"), chat = $("#chat-body"), props = $("#proposals"), meters = $("#meters"), foot = $("#review-foot"), timeline = $("#timeline");
  $("#demo-mode").textContent = D.mode === "live" ? "Claude" : "offline";
  const STAGE_LABEL = { input: "🧹 input", output: "🧾 output", retrieve: "🔎 fetch", plan: "🧠 plan", guardrails: "🛡️ check", schedule: "🗓️ dry-run", revise: "↺ revise", done: "✅ ready", stop: "🛑 stop" };
  const petIcon = (sc, name) => { const p = sc.pets.find((x) => x.name === name); return p && p.species === "cat" ? "🐱" : "🐶"; };
  const scenarios = [...D.scenarios, { key: "unsafe", label: "🧪 Unsafe AI", sub: "red team", synthetic: true }];
  let runId = 0;

  scenarios.forEach((sc, i) => {
    const b = el("button", "story");
    b.type = "button"; b.setAttribute("role", "tab"); b.setAttribute("aria-selected", "false");
    const emoji = sc.label.split(" ")[0];
    b.innerHTML = `<span class="story-ring"><span>${emoji}</span></span><b>${esc(sc.label.replace(emoji, "").trim())}</b><small>${esc(sc.sub)}</small>`;
    b.addEventListener("click", () => play(i));
    stories.appendChild(b);
  });

  function scrollChat() { chat.scrollTop = chat.scrollHeight; }
  async function typing(id, ms = 650) {
    const t = el("div", "typing", "<i></i><i></i><i></i>"); chat.appendChild(t); scrollChat();
    await wait(ms); t.remove(); return id === runId;
  }

  async function play(i) {
    const id = ++runId;
    const sc = scenarios[i];
    stories.querySelectorAll(".story").forEach((b, j) => b.setAttribute("aria-selected", String(j === i)));
    chat.innerHTML = ""; props.innerHTML = ""; meters.innerHTML = ""; foot.innerHTML = ""; timeline.innerHTML = "";
    if (sc.synthetic) return playRedTeam(id);

    $("#chat-sub").textContent = `${sc.pets.map((p) => `${p.name} (${p.species}, ${p.age})`).join(" · ")} · ${sc.minutes} min`;
    chat.appendChild(el("div", "bubble user", esc(sc.request))); scrollChat();
    for (const step of sc.trace) {
      if (!(await typing(id, step.stage === "plan" ? 900 : 550))) return;
      const cls = ["stop", "revise", "done"].includes(step.stage) ? step.stage : "";
      let html = `<span class="stage">${STAGE_LABEL[step.stage] || step.stage}</span><br>${esc(step.message)}`;
      if (step.stage === "retrieve" && sc.retrieved.length) {
        html += `<div class="chips-inline">${sc.retrieved.slice(0, 6).map((c) => `<code>${esc(c)}</code>`).join("")}${sc.retrieved.length > 6 ? `<code>+${sc.retrieved.length - 6}</code>` : ""}</div>`;
      }
      chat.appendChild(el("div", `bubble bot ${cls}`, html)); scrollChat();
    }
    if (id !== runId) return;

    if (sc.stopped) {
      props.innerHTML = `<div class="empty-stop"><div class="big">🚨</div><b>Planning stopped. No tasks were suggested.</b><p class="muted">${esc(sc.stopReason)}</p></div>`;
      return;
    }
    meters.innerHTML = [
      `<span class="meter">confidence <b>${Math.round(sc.confidence * 100)}%</b></span>`,
      `<span class="meter">grounded <b>${Math.round(sc.grounded * 100)}%</b></span>`,
      `<span class="meter">rounds <b>${sc.rounds}</b></span>`,
    ].join("");
    const state = sc.proposals.map((p) => p.verdict === "ok");
    sc.proposals.forEach((p, k) => {
      const row = el("div", `prop ${p.verdict}`);
      row.style.animationDelay = `${k * 80}ms`;
      const issue = p.verdict !== "ok" && p.issues.length ? `<span class="issue">${p.verdict === "blocked" ? "⛔" : "⚠️"} ${esc(p.issues[0])}</span>` : "";
      row.innerHTML = `<span class="who" aria-hidden="true">${petIcon(sc, p.pet)}</span>
        <div class="what"><b>${esc(p.task)}</b><small>${esc(p.pet)} · ${p.min} min · ${p.priority} · cites <code>${esc(p.cites.join(", ") || "none")}</code></small>${issue}</div>`;
      const btn = el("button", "toggle-btn");
      btn.type = "button";
      btn.setAttribute("role", "switch");
      btn.setAttribute("aria-label", `Add ${p.task} for ${p.pet}`);
      btn.setAttribute("aria-checked", String(state[k]));
      btn.innerHTML = `<span class="toggle ${state[k] ? "on" : ""}"></span>`;
      if (p.verdict === "blocked") { btn.disabled = true; btn.title = "Blocked tasks can't be added"; }
      btn.addEventListener("click", () => {
        state[k] = !state[k];
        btn.setAttribute("aria-checked", String(state[k]));
        btn.firstElementChild.classList.toggle("on", state[k]);
        updateCount();
      });
      const right = el("div"); right.style.display = "flex"; right.style.alignItems = "center"; right.style.gap = "8px";
      right.appendChild(el("span", `badge ${p.verdict}`, p.verdict === "ok" ? "ok" : p.verdict === "blocked" ? "blocked" : "check with vet"));
      right.appendChild(btn);
      row.appendChild(right);
      props.appendChild(row);
    });
    const count = el("span", "muted");
    const add = el("button", "btn btn-grad", "Add approved tasks");
    add.type = "button";
    foot.append(count, add);
    function updateCount() { const n = state.filter(Boolean).length; count.textContent = `${n} of ${sc.proposals.length} ticked`; }
    updateCount();
    add.addEventListener("click", () => {
      const n = state.filter(Boolean).length;
      toast(n ? `🎉 Added ${n} task${n > 1 ? "s" : ""} to ${[...new Set(sc.proposals.filter((_, k) => state[k]).map((p) => p.pet))].join(" & ")}'s day` : "Nothing ticked, so nothing was added");
    });
    timeline.innerHTML = `<h4>🗓️ Dry-run schedule</h4>`;
    sc.schedule.forEach((s, k) => {
      const r = el("div", "slot", `<span class="tm">${s.time}</span><span class="dot"></span><span>${petIcon(sc, s.pet)} ${esc(s.task)}</span><span class="mn">${s.min} min</span>`);
      r.style.animationDelay = `${300 + k * 90}ms`;
      timeline.appendChild(r);
    });
  }

  async function playRedTeam(id) {
    $("#chat-sub").textContent = "What if the AI suggests something unsafe?";
    chat.appendChild(el("div", "bubble user", "Show me what the guardrails do with bad AI output."));
    const picks = D.redTeam.filter((r) => ["dose", "human drug", "home remedy", "toxic treat", "fake citation", "species mismatch", "prescription reminder"].includes(r.name));
    for (const r of picks) {
      if (!(await typing(id, 450))) return;
      chat.appendChild(el("div", `bubble bot ${r.verdict === "blocked" ? "stop" : ""}`,
        `<span class="stage">${r.verdict === "blocked" ? "⛔ blocked" : "⚠️ review"}</span><br>“${esc(r.task)}” → ${esc(r.reason)}`));
      scrollChat();
    }
    if (id !== runId) return;
    meters.innerHTML = `<span class="meter">caught <b>${D.summary.red_team_caught}/${D.summary.red_team}</b></span>`;
    D.redTeam.forEach((r, k) => {
      const row = el("div", `prop ${r.verdict === "ok" ? "" : r.verdict}`);
      row.style.animationDelay = `${k * 60}ms`;
      row.innerHTML = `<span class="who" aria-hidden="true">🧪</span><div class="what"><b>${esc(r.task)}</b><small>${esc(r.name)}</small><span class="issue">${esc(r.reason)}</span></div><span class="badge ${r.verdict}">${r.verdict === "blocked" ? "blocked" : "check with vet"}</span>`;
      props.appendChild(row);
    });
    foot.innerHTML = `<span class="muted">These are real guardrail verdicts from <code>eval/run_eval.py</code>. Blocked tasks can't be approved.</span>`;
  }

  // Autoplay the first scenario once the demo scrolls into view.
  const demoObs = new IntersectionObserver(([e]) => { if (e.isIntersecting) { play(0); demoObs.disconnect(); } }, { threshold: 0.3 });
  demoObs.observe($("#demo"));

  /* ---------- stats ---------- */
  const s = D.summary || {};
  const STATS = [
    { n: D.tests, of: D.tests, lbl: "automated tests passing", sub: "Retriever, guardrails, agent loop, approval + Module 2 scheduler" },
    { n: s.scenarios_passed, of: s.scenarios, lbl: "end-to-end scenarios pass", sub: `${s.checks_passed}/${s.checks} individual checks` },
    { n: s.red_team_caught, of: s.red_team, lbl: "unsafe outputs caught", sub: "Doses, human drugs, toxic treats, fake citations…" },
    { n: Math.round((s.avg_confidence || 0) * 100), suffix: "%", lbl: "average confidence", sub: "Planner self-rating blended with guardrail survival" },
    { n: 100, suffix: "%", lbl: "of kept tasks cited", sub: "No citation to a retrieved excerpt means blocked" },
    { n: s.avg_rounds, dec: 1, lbl: "planning rounds on average", sub: "The agent revised its own first draft every time" },
  ];
  const statsWrap = $("#stats");
  STATS.forEach((st) => {
    const card = el("div", "stat reveal");
    const pct = st.of ? (st.n / st.of) * 100 : st.suffix === "%" ? st.n : 100;
    card.innerHTML = `<div class="num"><span data-to="${st.n}" data-dec="${st.dec || 0}">0</span>${st.of ? `<small>/${st.of}</small>` : st.suffix ? `<small>${st.suffix}</small>` : ""}</div>
      <div class="lbl">${st.lbl}</div><div class="sub">${st.sub}</div><div class="bar"><i data-w="${pct}"></i></div>`;
    statsWrap.appendChild(card);
    io.observe(card);
  });
  const countObs = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (!e.isIntersecting) return;
      const span = e.target.querySelector("[data-to]"), bar = e.target.querySelector("[data-w]");
      const to = parseFloat(span.dataset.to) || 0, dec = +span.dataset.dec;
      const t0 = performance.now(), dur = reduced ? 1 : 1400;
      const tick = (t) => {
        const k = Math.min(1, (t - t0) / dur), eased = 1 - Math.pow(1 - k, 4);
        span.textContent = (to * eased).toFixed(dec);
        if (k < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
      bar.style.width = `${bar.dataset.w}%`;
      countObs.unobserve(e.target);
    });
  }, { threshold: 0.5 });
  statsWrap.querySelectorAll(".stat").forEach((c) => countObs.observe(c));

  /* ---------- red-team grid with stamps ---------- */
  const rt = $("#rt-grid");
  D.redTeam.forEach((r) => {
    const c = el("div", "rt");
    c.innerHTML = `<small>${esc(r.name)}</small><b>“${esc(r.task)}”</b><p>${esc(r.reason)}</p><span class="stamp ${r.verdict}">${r.verdict === "blocked" ? "Blocked" : "Review"}</span>`;
    rt.appendChild(c);
  });
  const rtObs = new IntersectionObserver(([e]) => {
    if (!e.isIntersecting) return;
    rt.querySelectorAll(".rt").forEach((c, i) => setTimeout(() => c.classList.add("stamped"), reduced ? 0 : 120 * i));
    rtObs.disconnect();
  }, { threshold: 0.25 });
  rtObs.observe(rt);

  /* ---------- toast ---------- */
  let toastTimer;
  function toast(msg) {
    const t = $("#toast"); t.textContent = msg; t.classList.add("show");
    clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
  }
})();
