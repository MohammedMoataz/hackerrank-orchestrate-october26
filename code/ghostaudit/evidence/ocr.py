"""Console screenshots read with Tesseract OCR.

The OCR text is treated like any other evidence text: resource ids, identifiers and status words
found on the screen. When Tesseract is not installed the screenshots are skipped and the run
summary says so.
"""
from __future__ import annotations

import shutil
import subprocess
import time

from ..model import RESOURCE_RE, Observation, system_of
from .common import ids_in_value, state_of_record


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def ocr_text(path) -> str:
    try:
        return subprocess.run(["tesseract", str(path), "-", "--psm", "4"], capture_output=True, text=True,
                              check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return ""


def parse(path, file_id, captured_at, enabled=True, stats=None) -> list[Observation]:
    stats = stats if stats is not None else {}
    stats["available"] = tesseract_available()
    if not enabled or not stats["available"]:
        return []
    t0 = time.time()
    text = ocr_text(path)
    stats["images"] = stats.get("images", 0) + 1
    stats["seconds"] = round(stats.get("seconds", 0.0) + time.time() - t0, 2)
    ids = ids_in_value(text)
    out = []
    for rid in sorted(set(RESOURCE_RE.findall(text))):
        system = system_of(rid)
        if not system:
            continue
        state, category = screen_state(system, text)
        out.append(Observation(file_id, captured_at, system, rid, state, category, frozenset(ids),
                               "ocr", path.name))
    return out


def screen_state(system: str, text: str) -> tuple[str, str | None]:
    """Infer a record's state from words on a console screen."""
    low = text.lower()
    rec = {"email": "x" if "@" in text else None}
    if system == "integration_service":
        rec = {"enabled": not ("disabled" in low or "stopped" in low or "paused" in low)}
    elif system == "backup_service":
        rec = {"restore_allowed": not ("blocked" in low or "restore disabled" in low or "deny" in low)}
    return state_of_record(system, rec)
