"""A few decorative paw prints for the app background (original SVG, made for this project)."""

from __future__ import annotations

import base64


def _paw(color: str, opacity: float, angle: int) -> str:
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <g fill="{color}" opacity="{opacity}" transform="rotate({angle} 32 32)">
    <ellipse cx="32" cy="40" rx="13" ry="11"/><circle cx="17" cy="24" r="5.5"/>
    <circle cx="26" cy="16" r="5.5"/><circle cx="38" cy="16" r="5.5"/><circle cx="47" cy="24" r="5.5"/>
  </g>
</svg>"""
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


# (image, position, size): a handful of faint paws scattered around the page edges.
PAWS = [
    (_paw("#FF3D7F", 0.10, -20), "5% 16%", "46px"),
    (_paw("#A23BEC", 0.09, 25), "95% 34%", "40px"),
    (_paw("#FF6B4A", 0.10, -10), "7% 64%", "52px"),
    (_paw("#A23BEC", 0.08, 30), "93% 82%", "44px"),
]
