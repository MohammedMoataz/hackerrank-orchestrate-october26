"""Ghost Data Still Exists: audit every deletion request and write output.csv.

Usage:
    python3 code/main.py                    # audit dataset/deletion_requests.csv -> ./output.csv
    python3 code/main.py --explain case_42  # show how one case was decided
    python3 code/main.py --no-ocr           # skip screenshots even if Tesseract is installed
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ghostaudit import pipeline  # noqa: E402
from ghostaudit.loader import REPO_ROOT  # noqa: E402
from ghostaudit.planner import to_json_steps  # noqa: E402
from ghostaudit.report import status_counts, write_output, write_usage_report  # noqa: E402
from ghostaudit.validate import validate  # noqa: E402


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
    counts = status_counts(results)
    print(f"wrote {out} ({len(results)} rows) in {time.time() - t0:.1f}s: {counts}")
    print(f"evidence files {stats['files']}, observations {stats['observations']}, OCR {stats['ocr']}")
    print("model calls: 0 (deterministic pipeline)")
    for err in stats["errors"]:
        print("  evidence warning:", err)
    if errors:
        print(f"VALIDATION FAILED ({len(errors)}):", *errors[:20], sep="\n  ")
        return 2
    print("validation passed")
    write_usage_report(stats, len(results), counts, time.time() - t0, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
