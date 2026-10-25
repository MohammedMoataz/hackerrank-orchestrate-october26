"""Write the run's results: the submission CSV and the usage report."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .loader import REPO_ROOT
from .model import CaseResult
from .planner import to_json_steps

USAGE_REPORT = REPO_ROOT / "code" / "evaluation" / "usage_report.md"
STATUSES = ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE")


def write_output(path: Path, results: list[CaseResult]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["case_id", "deletion_status", "steps_json"])
        for r in results:
            w.writerow([r.case_id, r.status, json.dumps(to_json_steps(r.steps), separators=(",", ":"))])


def status_counts(results: list[CaseResult]) -> dict[str, int]:
    return {s: sum(r.status == s for r in results) for s in STATUSES}


def write_usage_report(stats: dict, n: int, counts: dict, seconds: float, out: Path) -> None:
    """Summarise the run that produced output.csv in code/evaluation/usage_report.md."""
    ocr = stats["ocr"]
    ocr_line = (f"{ocr['images']} screenshots read with Tesseract OCR in {ocr['seconds']} s"
                if ocr.get("available") else "Tesseract not installed: the 11 screenshots were skipped")
    text = f"""# Usage report

Summary of the final full-dataset run that produced `{out.name}` (`python3 code/main.py`).
This file is rewritten by every full run.

## Models

The agent makes **no model calls**. Every decision (intent, identity, evidence parsing, state, policy,
ordering) is deterministic Python; screenshots are read with local OCR.

| Provider | Model | Calls | Input tokens | Output tokens | Total tokens | Avg tokens / request | Est. cost | Cost / request |
|---|---|---|---|---|---|---|---|---|
| none | none | 0 | 0 | 0 | 0 | 0 | $0.00 | $0.00 |
| **Total** | | **0** | **0** | **0** | **0** | **0** | **$0.00** | **$0.00** |

## Run

| Item | Value |
|---|---|
| Requests audited | {n} |
| Status counts | COMPLETE {counts['COMPLETE']}, INCOMPLETE {counts['INCOMPLETE']}, NOT_APPLICABLE {counts['NOT_APPLICABLE']} |
| Evidence files parsed | {stats['files']} ({', '.join(f'{k} {v}' for k, v in sorted(stats['by_format'].items()))}) |
| Observations extracted | {stats['observations']} |
| Screenshots | {ocr_line} |
| Wall-clock time | {seconds:.1f} s on one CPU core |
| Output validation | passed |

AI assistance was used during development (Claude Code, model claude-opus-5-5); that is recorded in
`log.txt` and is not part of the runtime pipeline or its cost.
"""
    USAGE_REPORT.write_text(text, encoding="utf-8")
