"""Logging setup: everything the AI layer does goes to logs/pawpal_ai.log."""

from __future__ import annotations

import logging
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_configured = False


def setup_logging(level: int = logging.INFO, console: bool = False) -> Path:
    """Send pawpal_ai logs to logs/pawpal_ai.log (and optionally stderr).
    Safe to call more than once; Streamlit reruns the script on every click."""
    global _configured
    log_file = LOG_DIR / "pawpal_ai.log"
    if _configured:
        return log_file
    LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    logger = logging.getLogger("pawpal_ai")
    logger.setLevel(level)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    if console:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.addHandler(sh)
    _configured = True
    return log_file
