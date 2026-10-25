# Usage report

Summary of the final full-dataset run that produced `output.csv` (`python3 code/main.py`).
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
| Requests audited | 518 |
| Status counts | COMPLETE 149, INCOMPLETE 359, NOT_APPLICABLE 10 |
| Evidence files parsed | 94 (.json 28, .log 26, .pdf 4, .png 11, .sql 24, .txt 1) |
| Observations extracted | 2894 |
| Screenshots | Tesseract not installed: the 11 screenshots were skipped |
| Wall-clock time | 3.3 s on one CPU core |
| Output validation | passed |

AI assistance was used during development (Claude Code, model claude-opus-5-5); that is recorded in
`log.txt` and is not part of the runtime pipeline or its cost.
