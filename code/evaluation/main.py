"""Score the agent on the 32 labelled sample requests.

This is the only module that reads dataset/sample_output.csv; the predictor never does.

Usage:
    python3 code/evaluation/main.py            # summary metrics
    python3 code/evaluation/main.py --diff     # plus a per-case diff for every imperfect case
    python3 code/evaluation/main.py --markdown # metrics as a Markdown table (for the report)
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

from ghostaudit import pipeline  # noqa: E402
from ghostaudit.planner import to_json_steps  # noqa: E402

# Samples 01-10 are hand-built scenarios; 11-32 follow the generated cohort pattern used by
# most of the evaluation set. Odd-numbered samples are held out from rule tuning.
HAND_BUILT = {f"case_{i:02d}" for i in range(1, 11)}


def key(s):
    return (s["phase"], s["operation"], s["system_id"], s["resource_id"])


def score(pred: dict, gold: dict, cases: list[str]) -> dict:
    n = len(cases)
    status_ok = row_ok = seq_ok = 0
    tp = fp = fn = 0
    field_total = field_ok = 0
    ev_total = ev_ok = 0
    for c in cases:
        ps, pst = pred[c]
        gs, gst = gold[c]
        status_ok += ps == gs
        norm = lambda steps: [dict(s) for s in steps]
        row_ok += ps == gs and norm(pst) == norm(gst)
        pk, gk = [key(s) for s in pst], [key(s) for s in gst]
        seq_ok += pk == gk
        both = set(pk) & set(gk)
        tp += len(both); fp += len(set(pk) - set(gk)); fn += len(set(gk) - set(pk))
        pmap, gmap = {key(s): s for s in pst}, {key(s): s for s in gst}
        for k in both:
            # Matching already fixes phase, operation, system_id and resource_id; score the rest.
            for f in ("state", "evidence_id", "step_no"):
                field_total += 1
                field_ok += pmap[k][f] == gmap[k][f]
            ev_total += 1
            ev_ok += pmap[k]["evidence_id"] == gmap[k]["evidence_id"]
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {
        "cases": n,
        "status_accuracy": status_ok / n,
        "row_exact_accuracy": row_ok / n,
        "sequence_accuracy": seq_ok / n,
        "step_precision": p, "step_recall": r, "step_f1": 2 * p * r / (p + r) if p + r else 0.0,
        "field_accuracy_matched_steps": field_ok / field_total if field_total else 0.0,   # state, evidence, step_no
        "evidence_accuracy_matched_steps": ev_ok / ev_total if ev_total else 0.0,
    }


def run(use_ocr: bool = True):
    ds, auditor, _ = pipeline.build(use_ocr=use_ocr)
    gold = {}
    with open(ds.root / "sample_output.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            gold[row["case_id"]] = (row["deletion_status"], json.loads(row["steps_json"]))
    pred = {}
    for req in ds.sample_requests:
        res = auditor.audit(req)
        pred[req.case_id] = (res.status, to_json_steps(res.steps))
    return ds, pred, gold


def report(pred, gold) -> dict:
    cases = sorted(gold)
    groups = {
        "all samples": cases,
        "dev (even)": [c for c in cases if int(c.split("_")[1]) % 2 == 0],
        "holdout (odd)": [c for c in cases if int(c.split("_")[1]) % 2 == 1],
        "hand-built 01-10": [c for c in cases if c in HAND_BUILT],
        "generated 11-32": [c for c in cases if c not in HAND_BUILT],
    }
    return {g: score(pred, gold, cs) for g, cs in groups.items()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--diff", action="store_true")
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--write-report", action="store_true",
                    help="refresh the metrics table inside evaluation_report.md")
    args = ap.parse_args(argv)
    _, pred, gold = run(use_ocr=not args.no_ocr)
    rep = report(pred, gold)
    metrics = list(next(iter(rep.values())).keys())
    table = ["| metric | " + " | ".join(rep) + " |", "|---|" + "---|" * len(rep)]
    for m in metrics:
        vals = [str(v[m]) if m == "cases" else f"{v[m]:.3f}" for v in rep.values()]
        table.append(f"| {m} | " + " | ".join(vals) + " |")
    if args.write_report:
        path = Path(__file__).with_name("evaluation_report.md")
        text = path.read_text(encoding="utf-8")
        start, end = "<!-- metrics:start -->", "<!-- metrics:end -->"
        head, rest = text.split(start, 1)
        _, tail = rest.split(end, 1)
        path.write_text(head + start + "\n" + "\n".join(table) + "\n" + end + tail, encoding="utf-8")
        print(f"updated {path}")
    if args.markdown:
        print("\n".join(table))
    else:
        for g, v in rep.items():
            print(f"{g:<18} " + "  ".join(f"{m}={v[m]:.3f}" if m != "cases" else f"n={v[m]}" for m in metrics))
    if args.diff:
        for c in sorted(gold):
            ps, pst = pred[c]
            gs, gst = gold[c]
            if ps == gs and [key(s) for s in pst] == [key(s) for s in gst] and \
                    [s["evidence_id"] for s in pst] == [s["evidence_id"] for s in gst]:
                continue
            print(f"\n## {c}: predicted {ps}, expected {gs}")
            pk = {key(s): s["evidence_id"] for s in pst}
            gk = {key(s): s["evidence_id"] for s in gst}
            for k in sorted(set(pk) | set(gk), key=lambda k: (k[0] != "FINDING", k[0] == "VERIFICATION", k)):
                mark = "=" if k in pk and k in gk else ("+" if k in pk else "-")
                ev = f"{pk.get(k, '')}|{gk.get(k, '')}"
                print(f"  {mark} {k[0][:5]} {k[1]:<26} {k[2]:<20} {k[3]:<18} pred|gold ev: {ev}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
