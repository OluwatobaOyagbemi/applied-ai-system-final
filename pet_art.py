"""Original SVG pet illustrations and background pattern for the app (made for this project)."""

from __future__ import annotations

import base64

DOG_SVG = """<svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <ellipse cx="30" cy="52" rx="15" ry="27" fill="#9A5B33" transform="rotate(18 30 52)"/>
  <ellipse cx="90" cy="52" rx="15" ry="27" fill="#9A5B33" transform="rotate(-18 90 52)"/>
  <circle cx="60" cy="62" r="36" fill="#E9A866"/>
  <ellipse cx="60" cy="40" rx="11" ry="9" fill="#F3C189"/>
  <ellipse cx="60" cy="80" rx="22" ry="17" fill="#FFF1E0"/>
  <circle cx="46" cy="57" r="5" fill="#1F1430"/><circle cx="74" cy="57" r="5" fill="#1F1430"/>
  <circle cx="47.6" cy="55.3" r="1.6" fill="#fff"/><circle cx="75.6" cy="55.3" r="1.6" fill="#fff"/>
  <ellipse cx="60" cy="72" rx="7.5" ry="5.5" fill="#1F1430"/>
  <path d="M60 77 v6 M60 83 q-7 6 -13 1 M60 83 q7 6 13 1" stroke="#1F1430" stroke-width="2.4" fill="none" stroke-linecap="round"/>
  <path d="M55 86 q5 13 10 0 z" fill="#FF6B8A"/>
  <circle cx="36" cy="72" r="5" fill="#FF9DB0" opacity=".55"/><circle cx="84" cy="72" r="5" fill="#FF9DB0" opacity=".55"/>
</svg>"""

CAT_SVG = """<svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <path d="M28 52 L32 14 L56 36 Z" fill="#F29E4C"/><path d="M92 52 L88 14 L64 36 Z" fill="#F29E4C"/>
  <path d="M33 44 L35 23 L49 36 Z" fill="#FFC2CF"/><path d="M87 44 L85 23 L71 36 Z" fill="#FFC2CF"/>
  <circle cx="60" cy="66" r="35" fill="#F29E4C"/>
  <path d="M60 32 v12 M50 34 l3 10 M70 34 l-3 10" stroke="#D97A28" stroke-width="4" stroke-linecap="round"/>
  <ellipse cx="60" cy="82" rx="17" ry="12" fill="#FFF1E0"/>
  <ellipse cx="46" cy="62" rx="5" ry="6.5" fill="#1F1430"/><ellipse cx="74" cy="62" rx="5" ry="6.5" fill="#1F1430"/>
  <circle cx="47.5" cy="60" r="1.7" fill="#fff"/><circle cx="75.5" cy="60" r="1.7" fill="#fff"/>
  <path d="M56 75 h8 l-4 4 z" fill="#FF7A95"/>
  <path d="M60 79 q-5 6 -10 2 M60 79 q5 6 10 2" stroke="#1F1430" stroke-width="2.2" fill="none" stroke-linecap="round"/>
  <path d="M42 78 h-18 M42 83 l-17 4 M78 78 h18 M78 83 l17 4" stroke="#1F1430" stroke-width="1.6" stroke-linecap="round" opacity=".7"/>
  <circle cx="38" cy="74" r="4.5" fill="#FF9DB0" opacity=".5"/><circle cx="82" cy="74" r="4.5" fill="#FF9DB0" opacity=".5"/>
</svg>"""

PUPPY_PAWS_SVG = """<svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <g fill="#FF3D7F" opacity=".85"><ellipse cx="60" cy="72" rx="20" ry="17"/><circle cx="38" cy="48" r="8"/>
  <circle cx="52" cy="38" r="8"/><circle cx="68" cy="38" r="8"/><circle cx="82" cy="48" r="8"/></g>
</svg>"""

_PATTERN = """<svg xmlns="http://www.w3.org/2000/svg" width="220" height="220" viewBox="0 0 220 220">
  <g fill="#A23BEC" opacity=".07">
    <g transform="translate(30 40) rotate(-20)"><ellipse cx="0" cy="8" rx="9" ry="7.5"/><circle cx="-10" cy="-4" r="3.6"/><circle cx="-3.5" cy="-9" r="3.6"/><circle cx="3.5" cy="-9" r="3.6"/><circle cx="10" cy="-4" r="3.6"/></g>
    <g transform="translate(150 140) rotate(25)"><ellipse cx="0" cy="8" rx="9" ry="7.5"/><circle cx="-10" cy="-4" r="3.6"/><circle cx="-3.5" cy="-9" r="3.6"/><circle cx="3.5" cy="-9" r="3.6"/><circle cx="10" cy="-4" r="3.6"/></g>
  </g>
  <g fill="#FF6B4A" opacity=".07">
    <g transform="translate(165 45)"><path d="M-14 -2 L-11 -18 L-3 -9 Z M14 -2 L11 -18 L3 -9 Z"/><circle cx="0" cy="2" r="13"/></g>
    <g transform="translate(55 165)"><ellipse cx="-12" cy="-2" rx="5" ry="10" transform="rotate(20 -12 -2)"/><ellipse cx="12" cy="-2" rx="5" ry="10" transform="rotate(-20 12 -2)"/><circle cx="0" cy="2" r="12"/></g>
  </g>
</svg>"""

PATTERN_URI = "data:image/svg+xml;base64," + base64.b64encode(_PATTERN.encode()).decode()

ART = {"dog": DOG_SVG, "cat": CAT_SVG, "paw": PUPPY_PAWS_SVG}
