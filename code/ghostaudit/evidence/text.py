"""Plain-text handover ledgers and PDF business documents."""
from __future__ import annotations

import re
import subprocess

from ..model import RESOURCE_RE, Observation, system_of
from .common import ids_in_value, ledger_observation

HANDOVER_RE = re.compile(r"^-\s*(\S+)\s*\|\s*(\w+)\s*\|\s*(\w+)\s*\|\s*(\w+)\s*\|\s*(\w+)\s*\|\s*(.+)$")


def parse_ledger_text(path, file_id, captured_at) -> list[Observation]:
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = HANDOVER_RE.match(line.strip())
            if not m:
                continue
            _, system, rid, rtype, result, subject = m.groups()
            ob = ledger_observation(file_id, captured_at, {"system": system, "resource_id": rid, "record_type": rtype,
                                                           "result": result, "subject_reference": subject.strip()},
                                    "subject_reference", "handover")
            if ob:
                out.append(ob)
    return out


def pdf_text(path) -> str:
    try:
        return subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return ""


def parse_pdf(path, file_id, captured_at) -> list[Observation]:
    """A PDF is one business document about one subject: every resource it names is present.

    Documents that name no resource id (a statement number, an order register) yield nothing here.
    """
    text = pdf_text(path)
    ids = ids_in_value(text)
    out = []
    for rid in sorted(set(RESOURCE_RE.findall(text))):
        system = system_of(rid)
        category = None
        if system == "support_platform":
            category = "SUPPORT_ATTACHMENT"
        elif system == "security_service":
            category = "SECURITY_AUDIT_LOG"
        out.append(Observation(file_id, captured_at, system, rid, "PRESENT", category, frozenset(ids), frozenset(),
                               "pdf", "document"))
    return out
