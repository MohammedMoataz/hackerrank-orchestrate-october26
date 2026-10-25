# Evaluation report

Ghost Data Still Exists: a deterministic deletion-audit agent.
Reproduce every number here with:

```bash
python3 code/evaluation/main.py --diff            # metrics + per-case differences on the 32 samples
python3 -m unittest discover -s code/tests -v     # unit tests + the custom cases below
```

## How the samples are scored

`code/evaluation/main.py` runs the same pipeline as `code/main.py` on `dataset/sample_deletion_requests.csv`
and compares with `dataset/sample_output.csv`. That file is read only by the evaluator; a unit test fails if
any predictor module mentions it.

| Metric | Definition |
|---|---|
| status accuracy | share of cases whose `deletion_status` is right |
| row exact accuracy | share of cases whose status and whole `steps_json` array equal the answer |
| sequence accuracy | share of cases whose ordered list of (phase, operation, system, resource) equals the answer |
| step precision / recall / F1 | steps matched on (phase, operation, system_id, resource_id), over all cases |
| field accuracy | on matched steps, share of the 7 fields (incl. `step_no`, `state`, `evidence_id`) that are equal |
| evidence accuracy | on matched steps, share with the right `evidence_id` |

The samples are split two ways: **dev / holdout** (even / odd case numbers; rules were tuned looking at dev
diffs first and holdout was checked after each change) and **hand-built / generated** (cases 01–10 are
hand-made scenarios; 11–32 follow the generated cohort pattern that most of the 518 evaluation requests use).

## Results (final run)

<!-- metrics:start -->
| metric | all samples | dev (even) | holdout (odd) | hand-built 01-10 | generated 11-32 |
|---|---|---|---|---|---|
| cases | 32 | 16 | 16 | 10 | 22 |
| status_accuracy | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| row_exact_accuracy | 0.812 | 0.750 | 0.875 | 0.900 | 0.773 |
| sequence_accuracy | 0.812 | 0.750 | 0.875 | 0.900 | 0.773 |
| step_precision | 0.984 | 0.990 | 0.978 | 1.000 | 0.981 |
| step_recall | 0.964 | 0.950 | 0.978 | 0.968 | 0.963 |
| step_f1 | 0.974 | 0.969 | 0.978 | 0.984 | 0.972 |
| field_accuracy_matched_steps | 0.995 | 0.989 | 1.000 | 0.995 | 0.995 |
| evidence_accuracy_matched_steps | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
<!-- metrics:end -->

On the full evaluation set (`python3 code/main.py`): 518 rows, 159 COMPLETE, 349 INCOMPLETE, 10 NOT_APPLICABLE;
the built-in validator (header, order, operations, phases, states, consecutive step numbers, evidence ids that
exist and were captured at or before `audit_at`) passes.

### Remaining sample differences and why

| Case | Difference | Cause |
|---|---|---|
| case_04 | misses `VERIFY_RECORD_ABSENT account_004` | `account_004` appears in no evidence file and no activity row; nothing can identify it |
| case_18, case_20 | miss `VERIFY_RECORD_PRESENT audit_record_6645` / `audit_record_5569` | these audit records appear in no participant file |
| case_18, case_23 | pick a different deleted account | several requests reported in the same minute; their deletion runs interleave and the deleted account carries no identifier, so the choice is a tie |
| case_25, case_26 | swap two anonymized analytics profiles | same tie: both profiles are anonymized and observed in the same file |

## Custom evaluation cases

Each case is a small synthetic dataset built in `code/tests/test_custom_cases.py` and run through the real
pipeline. Shared fixture: `user_900` (current `test.person@example.com`, earlier `old.person@example.com`,
old email hash `aaaa…`), a look-alike `user_901` (`test.person.jr@example.com`), and a deletion-worker row
deleting `account_900` one hour before the request's `reported_at`.

**1. A request that is not a deletion.**
Input text: "Please send me a copy of my data. I still use the account, please don't delete anything."
Expected: `NOT_APPLICABLE`, `[]`. Checks that deletion words inside a negation do not authorise deletion.

**2. Upper-case historical email and an old email hash.**
Request email `OLD.PERSON@EXAMPLE.COM`; a snapshot (captured before the cutoff) holds `analytics_900` keyed only
by the old hash, and `audit_record_900` for `user_900`.
Expected `INCOMPLETE`:

| # | operation | resource | evidence |
|---|---|---|---|
| 1 | REPORT_EXPOSED_PII | analytics_900 | evidence_900 |
| 2 | ANONYMIZE_RECORD | analytics_900 | "" |
| 3 | VERIFY_RECORD_ABSENT | account_900 | "" |
| 4 | VERIFY_RECORD_PRESENT | audit_record_900 | "" |
| 5 | VERIFY_RECORD_ANONYMIZED | analytics_900 | "" |

**3. A look-alike address and a 404 lookup do not prove ownership.**
A log shows a 404 lookup of `account_777` keyed by the person's email, a search hit for
`test.person.jr@example.com`, and the person's audit record. Expected `COMPLETE` with
`VERIFY_RECORD_ABSENT account_900 (evidence_900)` and `VERIFY_RECORD_PRESENT audit_record_900 (evidence_900)`:
neither `account_777` nor `search_901` belongs to the request.

**4. Evidence captured after the cutoff is ignored.**
A file before the cutoff shows `search_900` still indexed; a file after the cutoff shows another entry
`search_902`. Expected `INCOMPLETE` for `search_900`; `search_902` and the later file never appear.

**5. Active sync and restore path are stopped before records are deleted.**
One snapshot shows an enabled connector, a backup that allows restore, and a search entry. Expected operations
in order: `REPORT_REMAINING_RECORD, REPORT_ACTIVE_DATA_FLOW, REPORT_RESTORE_RISK, DISABLE_DATA_FLOW,
BLOCK_RESTORE, DELETE_RECORD, VERIFY_RECORD_ABSENT ×2, VERIFY_DATA_FLOW_DISABLED, VERIFY_RESTORE_BLOCKED`.

All five pass, together with unit tests for the six log syntaxes, the ten non-deletion texts and six
multilingual deletion texts, policy coverage of every rule in `deletion_rules.csv`, canonical step ordering,
and two leakage guards (no predictor module reads `sample_output.csv`; no hard-coded case ids).

## Failures found and improvements made

Each row is one change, measured on all 32 samples (status accuracy / step F1 / row exact).

| # | Change | Failure it fixed | Status | Step F1 | Row exact |
|---|---|---|---|---|---|
| 0 | First end-to-end pipeline | (baseline) | 0.781 | 0.791 | 0.406 |
| 1 | Intent: only an explicit non-deletion signal makes a request NOT_APPLICABLE | "Please remove any remaining copy", "tell me whether it has been removed" were classed as non-deletion | 0.969 | 0.955 | 0.688 |
| 1b | Run attribution never gives a record to a request when evidence ties it to someone else | `search_428`, `export_1260` (other people's records) attached to case_12 / case_19 | (in 1) | | |
| 1c | Retained audit records may be identified from later evidence; their state and citation still come from before the cutoff | answers verify audit records only visible after the cutoff (case_09, 23, 24) | (in 1) | | |
| 2 | Joint, cost-based matching of deletion-run records to requests (content link ≫ claim consistency ≫ own evidence file ≫ timing) instead of greedy elimination in id order | `account_8491` took case_12's slot, leaving the right `account_9797` unassigned | 1.000 | 0.974 | 0.812 |
| 3 | COMPLETE verifications only for records observed before the cutoff | a retained record known only from later evidence got a citation to a file that does not mention it | 1.000 | 0.974 | 0.812 |
| 4 | Log tokenizer: separate `key=value` and JSON pair patterns; unwrap cloud `message="…"` payloads | unit test showed `event: key="v"` lines lost their resource id | 1.000 | 0.974 | 0.812 |

### Strategy comparison

Run attribution (which deleted or anonymized record belongs to which request when several requests were
reported in the same minute) was tried two ways:

| Strategy | Status | Step F1 | Row exact |
|---|---|---|---|
| Elimination: assign a record when exactly one candidate request is left, in resource-id order | 0.969 | 0.955 | 0.688 |
| Cost-based matching over all (record, request) pairs | 1.000 | 0.974 | 0.812 |

Intent was also tried two ways: deletion keywords required (status 0.781, five deletion follow-ups missed) vs.
explicit non-deletion signal required (status 1.000; the ten real non-deletion requests in the evaluation set
are still caught, see unit tests).

## Known limitations

* Screenshots: when Tesseract is not installed, the 11 PNG files are skipped and the run summary says so.
  About a dozen evaluation requests (case_33–63) rely on them.
* Ties between interleaved deletion runs are settled deterministically but can be wrong (see table above).
* Records that appear in no participant file cannot be reported.
