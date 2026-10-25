"""Ghost Data Still Exists: audit every deletion request and write output.csv.

Usage:
    python3 code/main.py                    # audit dataset/deletion_requests.csv -> ./output.csv
    python3 code/main.py --explain case_42  # show how one case was decided
    python3 code/main.py --no-ocr           # skip screenshots even if Tesseract is installed
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ghostaudit import pipeline  # noqa: E402
from ghostaudit.loader import REPO_ROOT  # noqa: E402
from ghostaudit.planner import to_json_steps  # noqa: E402
from ghostaudit.validate import validate  # noqa: E402


def write_output(path: Path, results) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["case_id", "deletion_status", "steps_json"])
        for r in results:
            w.writerow([r.case_id, r.status, json.dumps(to_json_steps(r.steps), separators=(",", ":"))])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--output", default=str(REPO_ROOT / "output.csv"))
    ap.add_argument("--explain", metavar="CASE_ID")
    ap.add_argument("--no-ocr", action="store_true")
    args = ap.parse_args(argv)

    t0 = time.time()
    ds, auditor, stats = pipeline.build(use_ocr=not args.no_ocr)
    if args.explain:
        req = next((r for r in ds.all_requests if r.case_id == args.explain), None)
        if req is None:
            print(f"unknown case {args.explain}")
            return 1
        res = auditor.audit(req)
        print(f"{req.case_id} {res.status}  email={req.email} audit_at={req.audit_at}")
        for n in res.notes:
            print("  -", n)
        for s in to_json_steps(res.steps):
            print(f"  {s['step_no']:>2} {s['phase']:<12} {s['operation']:<26} {s['system_id']:<20} {s['resource_id']:<18} {s['evidence_id']}")
        return 0

    results = [auditor.audit(r) for r in ds.requests]
    out = Path(args.output)
    write_output(out, results)
    errors = validate(out, ds.requests, ds.evidence_files)
    counts = {s: sum(r.status == s for r in results) for s in ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE")}
    print(f"wrote {out} ({len(results)} rows) in {time.time() - t0:.1f}s: {counts}")
    print(f"evidence files {stats['files']}, observations {stats['observations']}, OCR {stats['ocr']}")
    print("model calls: 0 (deterministic pipeline)")
    if errors:
        print(f"VALIDATION FAILED ({len(errors)}):", *errors[:20], sep="\n  ")
        return 2
    print("validation passed")
    write_usage_report(stats, len(results), counts, time.time() - t0, out)
    return 0


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
    (Path(__file__).resolve().parent / "evaluation" / "usage_report.md").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
