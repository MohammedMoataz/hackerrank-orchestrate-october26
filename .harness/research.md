# Research — Ghost Data Still Exists

## Data facts (verified against sample_output.csv)
- 518 eval cases; 10 are non-deletion (explicit "keep account / not deletion" text) -> NOT_APPLICABLE.
- Every case's answer centres on: account (VERIFY_RECORD_ABSENT always), security audit record (VERIFY_RECORD_PRESENT),
  plus search / support / analytics / data_flow / backup / export / tombstone resources.
- Evidence formats: SQL snapshots (primary + replica tables, inventory tables, snapshot_scope), JSON bundles/exports
  (nested captured_at/observed_at/recorded_at), 6 log dialects (kv, JSON payload, syslog, pipe, bracket, cloud),
  handover txt, 4 PDFs (pdftotext), 11 PNG screenshots (OCR via rapidocr).
- Identity links: lookup_key / correlation_key / subject_reference / customer_reference / emails in text / email_hash
  (sha256 of lower-cased email; history in user_audit_log).
- Deleted accounts and anonymized analytics carry no identifiers; they are tied to a case only through the
  deletion_worker burst around reported_at (window ~ -2h .. +2.5h). Account result tracks reported_status
  (COMPLETE~SUCCESS, PARTIALLY_COMPLETE~PARTIAL, NOT_STARTED~FAILED). Within a burst events are sorted by id -> ambiguous.
- Some expected resources (e.g. audit_record_6645) exist nowhere in participant data -> unreachable.
- INCOMPLETE answers often include audit records only visible in evidence captured after audit_at (linking only).
- Activity event_type is the workflow's intended treatment (analytics_9914 DELETE_RECORD -> expected DELETE).
- Image facts are mirrored by LINK_RESOURCE_IDENTITY activity rows logged ~7 min after the screenshot capture.
- Ordering: phase, then operation table order, then system_id, resource_id.
- Citation: latest observation at/before audit_at (file captured_at <= audit_at); SQL full-table scans prove absence.
