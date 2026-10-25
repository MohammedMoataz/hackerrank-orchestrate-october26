# Ghost Data Still Exists: deletion-audit agent

HackerRank Orchestrate, October 2026. For every request in `dataset/deletion_requests.csv` the agent decides
whether deletion was requested, finds every copy of the person's data across systems, establishes each
copy's true state at the request's `audit_at` cutoff from evidence files, applies `dataset/deletion_rules.csv`,
and writes `output.csv` (`case_id,deletion_status,steps_json`).

The agent is deterministic: it makes no model calls. Evidence files are structured enough that rules beat a
model on exactness, which is what the grader checks; every decision can be traced with `--explain`.

## Setup

Python 3.10+ standard library only. Two optional system tools:

```bash
sudo apt install poppler-utils tesseract-ocr   # pdftotext for PDFs, tesseract for the 11 console screenshots
```

Without `tesseract` the screenshots are skipped (the run summary says so); without `pdftotext` PDFs are skipped.
No API keys or `.env` are needed.

## Run

```bash
python3 code/main.py                       # writes ./output.csv, validates it, writes code/evaluation/usage_report.md
python3 code/main.py --explain case_42     # how one case was decided: records, states, evidence, steps
python3 code/evaluation/main.py --diff     # accuracy on the 32 labelled samples, with per-case differences
python3 -m unittest discover -s code/tests -v
```

A full run takes about a second.

## How it works

```
request ──► intent rules ──► NOT_APPLICABLE + []           (access, export, correction, opt-out requests)
   │ deletion
   ▼
identity: request email ─► person ─► every current and past email, email hash, phone, user_id
   │
evidence readers (JSON ledgers / snapshot bundles / service exports, SQL replicas, 6 log syntaxes,
handover text, PDFs, OCR'd screenshots) ─► observations (file, capture time, resource, state, identifiers)
   │
linker: records ⇄ person  (identifiers inside records, positive lookups, data-catalog rows,
                           joint attribution of the deletion worker's run around reported_at)
   │
state at audit_at: latest observation captured at or before the cutoff (inclusive)
   │
policy (deletion_rules.csv) ─► violations ─► findings ─► remediation ─► verification
   │
canonical ordering, evidence ids, validator ─► output.csv
```

| Module | Responsibility |
|---|---|
| `code/main.py` | CLI, output writing, validation, usage report |
| `code/ghostaudit/intent.py` | multilingual rules: deletion vs. non-deletion requests |
| `code/ghostaudit/identity.py` | current + historical identifiers from `user_identities.csv` and `user_audit_log.csv` |
| `code/ghostaudit/evidence/` | one reader per content shape (`records`, `sql`, `logs`, `text`, `ocr`) |
| `code/ghostaudit/linker.py` | which records belong to which request |
| `code/ghostaudit/policy.py` | category → compliant state and the find / fix / verify operations |
| `code/ghostaudit/planner.py` | state at the cutoff, status, steps, evidence citations |
| `code/ghostaudit/validate.py` | the submission contract as checks |
| `code/evaluation/main.py` | sample scoring (case, row, step, field, sequence accuracy) |
| `code/tests/` | unit tests, five custom end-to-end cases, leakage guards |

## Decisions worth knowing

* **Claims are not evidence.** `reported_status` and activity `reported_result` never set a record's state.
  Activity rows are used only to find which resources a request concerns (a deleted account or an anonymized
  profile carries no identifier any more).
* **Ownership needs content.** A record belongs to a person when one of their identifiers is inside it, a
  lookup keyed by their identifier found it, or a data-catalog row says so. A lookup that returned 404 proves
  nothing, and look-alike addresses (`x.jr@…`) never match: matching is exact after lower-casing.
* **Time cutoff.** State and citations use only files captured at or before `audit_at` (inclusive). Retained
  audit records may be *identified* from later files, but are then only listed as future verification checks,
  never cited.
* **Replication drift.** A profile deleted from the primary but present in any replica is still present.
* **Files are routed by content, not name** (`connector_configurations_*.json` is a general ledger).
* **Ordering** follows the operation table, then `system_id`, then `resource_id`; this already puts data-flow
  disabling and restore blocking before record changes.
* **Never reads labels.** Only the evaluator opens `sample_output.csv`; a unit test enforces it.

Results, custom cases and the improvement log are in `code/evaluation/evaluation_report.md`; run cost in
`code/evaluation/usage_report.md`.

## Packaging

```bash
zip -r code.zip README.md code -x "*/__pycache__/*" "*/.venv/*" "*/venv/*" "*/node_modules/*" "*/.git/*" "*/.DS_Store"
```
