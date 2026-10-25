# Plan
Files: code/evidence.py (ingest), code/intent.py (request classification), code/audit.py (case reasoning),
code/main.py (CLI -> output.csv), code/evaluation/main.py (score vs sample_output.csv), README.md, evaluation reports.

1. Identity: email -> user_id (current or historical); keys = user_id, all emails, all hashes, phones (digits).
2. Candidate resources = identity-linked rids (obs in files <= audit_at; late files allowed for retained-record linking)
   + burst resources assigned per reported_at block (identity link > status match > order).
3. State per rid = latest observation <= audit_at (any copy present wins inside one file); fallback SQL scan absence.
4. Treatment from category (rules csv) with activity event_type override; state x treatment -> FINDING/REMEDIATION/VERIFICATION.
5. Status = INCOMPLETE if any finding else COMPLETE; NOT_APPLICABLE when intent is not deletion.
6. Intent: deterministic multilingual rules; optional LLM (Anthropic env key or local Ollama) as primary with cache + usage log.
Verify: code/evaluation/main.py on the 32 samples (status acc, step P/R, field acc, sequence acc); full run -> 518 rows.
