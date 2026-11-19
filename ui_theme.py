"""Visual theme for the Streamlit app, matching the WhiskerWise landing page.

Streamlit has no component-level styling API, so this injects one stylesheet
(fonts, sunset gradient, rounded cards, gradient primary buttons) plus three
HTML helpers: hero(), section() and footer(). Only static, trusted strings are
rendered as HTML here; user input never goes through these helpers.
"""

from __future__ import annotations

import streamlit as st

from pet_art import PAWS

SITE_URL = "https://oluwatobaoyagbemi.github.io/applied-ai-system-final/"
REPO_URL = "https://github.com/OluwatobaOyagbemi/applied-ai-system-final"

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,800&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');

:root {
  --ww-grad: linear-gradient(120deg, #ffb547 0%, #ff6b4a 28%, #ff3d7f 55%, #a23bec 80%, #5b4bff 100%);
  --ww-soft: linear-gradient(135deg, #fff1e3, #ffe3ef 50%, #efe4ff);
  --ww-ink: #1f1430; --ww-ink2: #5d5070; --ww-line: rgba(31,20,48,.09);
  --ww-shadow: 0 1px 2px rgba(31,20,48,.06), 0 14px 34px -14px rgba(162,59,236,.28);
}
html, body, [class*="css"], .stApp, .stMarkdown, p, label, input, textarea, button, li {
  font-family: "Plus Jakarta Sans", system-ui, sans-serif !important;
}
.stApp {
  background:
    radial-gradient(60vmax 60vmax at -10% -15%, rgba(255,181,71,.30), transparent 60%),
    radial-gradient(55vmax 55vmax at 110% 10%, rgba(255,61,127,.22), transparent 60%),
    radial-gradient(60vmax 60vmax at 40% 120%, rgba(162,59,236,.16), transparent 60%),
    __PAWS__
    #fff8f3 !important;
  background-repeat: no-repeat !important;
  background-position: __POSITIONS__ !important;
  background-size: __SIZES__ !important;
  background-attachment: fixed !important;
}
header[data-testid="stHeader"] { background: transparent !important; }
.block-container { padding-top: 2.2rem !important; max-width: 820px !important; }
h1, h2, h3, h4 { font-family: "Bricolage Grotesque", sans-serif !important; letter-spacing: -.02em; color: var(--ww-ink); }

/* hero */
.ww-top { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom: 26px; flex-wrap: wrap; }
.ww-brand { display:flex; align-items:center; gap:10px; font-family:"Bricolage Grotesque",sans-serif; font-weight:800; font-size:1.25rem; color: var(--ww-ink); text-decoration:none !important; }
.ww-mark { display:inline-grid; place-items:center; width:36px; height:36px; border-radius:12px; background:var(--ww-grad); box-shadow:0 6px 16px -6px #ff3d7f; font-size:18px; }
.ww-links { display:flex; gap:8px; flex-wrap: wrap; }
.ww-links a { text-decoration:none !important; font-weight:700; font-size:.88rem; color: var(--ww-ink) !important; background:#fff; border:1px solid var(--ww-line); padding:8px 14px; border-radius:999px; box-shadow: var(--ww-shadow); }
.ww-links a:hover { transform: translateY(-1px); }
.ww-eyebrow { display:inline-flex; align-items:center; gap:8px; font-weight:700; font-size:.82rem; padding:7px 13px; border-radius:999px; background:#fff; border:1px solid var(--ww-line); box-shadow: var(--ww-shadow); color: var(--ww-ink); }
.ww-dot { width:8px; height:8px; border-radius:50%; background:#ff3d7f; animation: wwpulse 2s infinite; }
@keyframes wwpulse { 0%{box-shadow:0 0 0 0 rgba(255,61,127,.6)} 70%{box-shadow:0 0 0 9px transparent} 100%{box-shadow:0 0 0 0 transparent} }
.ww-title { font-family:"Bricolage Grotesque",sans-serif; font-weight:800; font-size: clamp(2.3rem, 7vw, 3.6rem); line-height:1.02; margin: 16px 0 10px; color: var(--ww-ink); }
.ww-grad { background: var(--ww-grad); -webkit-background-clip:text; background-clip:text; color:transparent; }
.ww-lede { color: var(--ww-ink2); font-size: 1.06rem; max-width: 36em; margin: 0 0 6px; }

/* numbered section headers */
.ww-sec { display:flex; align-items:center; gap:14px; margin: 34px 0 14px; }
.ww-num { flex:none; display:grid; place-items:center; width:42px; height:42px; border-radius:14px; background: var(--ww-grad); color:#fff; font-family:"Bricolage Grotesque",sans-serif; font-weight:800; font-size:1.15rem; box-shadow: 0 10px 22px -10px #ff3d7f; }
.ww-sec h2 { margin:0 !important; padding:0 !important; font-size: 1.55rem !important; }
.ww-sec p { margin: 2px 0 0; color: var(--ww-ink2); font-size: .92rem; }

/* cards: forms, dataframes, metrics, expanders, status, alerts */
[data-testid="stForm"], [data-testid="stExpander"] details, [data-testid="stDataFrame"], [data-testid="stMetric"] {
  background:#fff !important; border:1px solid var(--ww-line) !important; border-radius: 22px !important; box-shadow: var(--ww-shadow);
}
[data-testid="stForm"] { padding: 1.2rem 1.2rem .6rem !important; }
[data-testid="stDataFrame"] { overflow: hidden; padding: 4px; }
[data-testid="stMetric"] { padding: 14px 16px !important; }
[data-testid="stMetricValue"] { font-family:"Bricolage Grotesque",sans-serif !important; font-weight:800 !important; background: var(--ww-grad); -webkit-background-clip:text; background-clip:text; color:transparent !important; }
[data-testid="stAlert"] { border-radius: 16px !important; border: none !important; }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]),
[data-baseweb="notification"]:has([data-testid="stAlertContentInfo"]) { background: var(--ww-soft) !important; border-radius: 16px !important; }
[data-testid="stAlertContentInfo"] { color: var(--ww-ink) !important; }
[data-testid="stAlertContentInfo"] p { color: var(--ww-ink) !important; }
a.ww-brand, a.ww-brand:visited { color: var(--ww-ink) !important; }
[data-testid="stExpander"] details { overflow:hidden; }
[data-testid="stStatusWidget"], [data-testid="stStatus"] { border-radius: 18px !important; }
hr { display:none; }

/* inputs */
[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"], [data-testid="stTimeInput"] [data-baseweb="input"] {
  border-radius: 14px !important; border-color: var(--ww-line) !important; background: #fff !important;
}
textarea { border-radius: 14px !important; }

/* buttons */
.stButton > button, .stFormSubmitButton > button, .stDownloadButton > button {
  border-radius: 999px !important; font-weight: 700 !important; padding: .55rem 1.25rem !important;
  border: 1px solid var(--ww-line) !important; background:#fff !important; color: var(--ww-ink) !important;
  box-shadow: var(--ww-shadow); transition: transform .3s cubic-bezier(.34,1.56,.64,1), box-shadow .3s;
}
.stButton > button:hover, .stFormSubmitButton > button:hover { transform: translateY(-2px) scale(1.02); }
.stButton > button[kind="primary"], [data-testid="stBaseButton-primary"], .stFormSubmitButton > button[kind="primaryFormSubmit"] {
  background: var(--ww-grad) !important; background-size: 160% auto !important; color:#fff !important; border:none !important;
  box-shadow: 0 14px 30px -12px #ff3d7f !important;
}
.stButton > button[kind="primary"] p, [data-testid="stBaseButton-primary"] p { color:#fff !important; }

/* footer */
.ww-foot { margin: 56px 0 10px; padding-top: 22px; border-top: 1px solid var(--ww-line); text-align:center; color: var(--ww-ink2); font-size:.85rem; }
.ww-foot a { color: #c81e5b !important; font-weight:700; text-decoration:none !important; }

@media (max-width: 640px) {
  .block-container { padding-left: 16px !important; padding-right: 16px !important; }
  .ww-sec h2 { font-size: 1.3rem !important; }
}
@media (max-width: 640px) { html, body, .stApp, [data-testid="stAppViewContainer"], .block-container { overflow-x: hidden !important; max-width: 100vw !important; }
  .ww-title { font-size: 2.1rem; overflow-wrap: anywhere; } }
@media (prefers-reduced-motion: reduce) { .ww-dot { animation: none; } }
</style>
"""


def apply_theme() -> None:
    layers = "".join(f'url("{uri}"), ' for uri, _, _ in PAWS)
    css = (_CSS.replace("__PAWS__", layers)
               .replace("__POSITIONS__", "0 0, 0 0, 0 0, " + ", ".join(pos for _, pos, _ in PAWS) + ", 0 0")
               .replace("__SIZES__", "auto, auto, auto, " + ", ".join(size for _, _, size in PAWS) + ", auto"))
    st.markdown(css, unsafe_allow_html=True)


def hero() -> None:
    st.markdown(f"""
<div class="ww-top">
  <a class="ww-brand" href="{SITE_URL}" target="_blank"><span class="ww-mark">🐾</span>WhiskerWise</a>
  <div class="ww-links">
    <a href="{SITE_URL}" target="_blank">← Project site</a>
    <a href="{REPO_URL}" target="_blank">GitHub</a>
  </div>
</div>
<span class="ww-eyebrow"><span class="ww-dot"></span>RAG · Agent · Guardrails · You approve</span>
<div class="ww-title">Plan your pets' day,<br><span class="ww-grad">with sources you can see.</span></div>
<p class="ww-lede">Tell WhiskerWise about your pets and your time. It looks up vet guidance, suggests cited tasks,
blocks anything unsafe, and adds nothing until you approve it.</p>
""", unsafe_allow_html=True)


def section(number: int, title: str, subtitle: str = "") -> None:
    sub = f"<p>{subtitle}</p>" if subtitle else ""
    st.markdown(f'<div class="ww-sec"><span class="ww-num">{number}</span><div><h2>{title}</h2>{sub}</div></div>',
                unsafe_allow_html=True)


def footer() -> None:
    st.markdown(f"""
<div class="ww-foot">
  🐾 <b>WhiskerWise</b> · built on PawPal+ ·
  <a href="{SITE_URL}" target="_blank">Project site</a> ·
  <a href="{REPO_URL}" target="_blank">Code</a> ·
  <a href="{REPO_URL}/blob/main/model_card.md" target="_blank">Model card</a><br>
  General pet-care reminders, not veterinary advice. Always follow your veterinarian's instructions.
</div>
""", unsafe_allow_html=True)
