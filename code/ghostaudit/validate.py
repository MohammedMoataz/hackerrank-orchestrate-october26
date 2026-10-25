"""Check an output file against the submission contract before it is handed in."""
from __future__ import annotations

import csv
import json

from .model import OP_PHASE, OP_RANK, OP_STATE

HEADER = ["case_id", "deletion_status", "steps_json"]
STATUSES = {"COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"}
FIELDS = {"step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id"}
PHASE_RANK = {"FINDING": 0, "REMEDIATION": 1, "VERIFICATION": 2}


def validate(output_path, requests, evidence_files) -> list[str]:
    errors = []
    captured = {f["file_id"]: f["captured_at"] for f in evidence_files}
    audit = {r.case_id: r.audit_at for r in requests}
    with open(output_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    if header != HEADER:
        errors.append(f"header is {header}")
    ids = [r[0] for r in rows]
    expected = [r.case_id for r in requests]
    if ids != expected:
        errors.append(f"case ids/order differ from input ({len(ids)} rows, {len(expected)} expected)")
    for case_id, status, raw in rows:
        if status not in STATUSES:
            errors.append(f"{case_id}: bad status {status}")
        try:
            steps = json.loads(raw)
        except json.JSONDecodeError as e:
            errors.append(f"{case_id}: steps_json not JSON ({e})")
            continue
        if status == "NOT_APPLICABLE" and steps:
            errors.append(f"{case_id}: NOT_APPLICABLE must have []")
        prev = None
        for i, s in enumerate(steps, 1):
            if set(s) != FIELDS:
                errors.append(f"{case_id}: step {i} fields {sorted(s)}")
                continue
            if s["step_no"] != i:
                errors.append(f"{case_id}: step numbers not consecutive at {i}")
            op = s["operation"]
            if op not in OP_RANK or OP_PHASE[op] != s["phase"] or OP_STATE[op] != s["state"]:
                errors.append(f"{case_id}: step {i} invalid operation/phase/state")
                continue
            key = (OP_RANK[op], s["system_id"], s["resource_id"])
            if prev and key < prev:
                errors.append(f"{case_id}: step {i} out of order")
            prev = key
            ev = s["evidence_id"]
            needs = s["phase"] == "FINDING" or status == "COMPLETE"
            if needs and not ev:
                errors.append(f"{case_id}: step {i} needs evidence")
            if not needs and ev:
                errors.append(f"{case_id}: step {i} must have empty evidence")
            if ev.startswith("evidence_"):
                if ev not in captured:
                    errors.append(f"{case_id}: step {i} unknown evidence {ev}")
                elif captured[ev] > audit.get(case_id, "9999"):
                    errors.append(f"{case_id}: step {i} cites {ev} captured after audit_at")
    return errors
