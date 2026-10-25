"""Custom end-to-end evaluation cases, run through the real pipeline on small synthetic datasets.

Each case targets one trap from the real data. The same cases are written out, with inputs and
expected steps, in code/evaluation/evaluation_report.md.
"""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE))

from ghostaudit import pipeline  # noqa: E402
from ghostaudit.planner import to_json_steps  # noqa: E402

RULES = CODE.parent / "dataset" / "deletion_rules.csv"
H_OLD = "a" * 64
H_NEW = "b" * 64
USERS = [
    {"user_id": "user_900", "name": "Test Person", "email": "test.person@example.com", "phone": "+1 555 0100",
     "email_hash": H_NEW, "updated_at": "2026-01-01T00:00:00Z"},
    {"user_id": "user_901", "name": "Other Person", "email": "test.person.jr@example.com", "phone": "+1 555 0101",
     "email_hash": "c" * 64, "updated_at": "2026-01-01T00:00:00Z"},
]
AUDIT_LOG = [
    {"audit_id": "audit_900", "user_id": "user_900", "event_time": "2026-05-01T00:00:00Z", "field_name": "email",
     "old_value": "old.person@example.com", "new_value": "test.person@example.com"},
    {"audit_id": "audit_901", "user_id": "user_900", "event_time": "2026-05-01T00:00:00Z", "field_name": "email_hash",
     "old_value": H_OLD, "new_value": H_NEW},
]


def write_csv(path, rows, header):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)


def run_case(request, activities=(), files=()):
    """files: (file_id, relative_path, captured_at, content)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_csv(root / "deletion_requests.csv", [request], list(request))
        write_csv(root / "sample_deletion_requests.csv", [], list(request))
        write_csv(root / "user_identities.csv", USERS, list(USERS[0]))
        write_csv(root / "user_audit_log.csv", AUDIT_LOG, list(AUDIT_LOG[0]))
        acts = [dict(a) for a in activities]
        write_csv(root / "system_activity.csv", acts, ["activity_id", "event_time", "event_type", "source_system",
                                                      "target_system", "resource_id", "reported_result", "details"])
        (root / "deletion_rules.csv").write_text(RULES.read_text(encoding="utf-8"), encoding="utf-8")
        manifest = []
        for fid, rel, cap, content in files:
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            manifest.append({"file_id": fid, "file_path": rel, "origin": "test", "captured_at": cap})
        write_csv(root / "evidence_files.csv", manifest, ["file_id", "file_path", "origin", "captured_at"])
        ds, auditor, _ = pipeline.build(use_ocr=False, root=root)
        res = auditor.audit(ds.requests[0])
        return res.status, [(s["operation"], s["resource_id"], s["evidence_id"]) for s in to_json_steps(res.steps)]


def req(text, email="test.person@example.com", status="COMPLETE"):
    return {"case_id": "case_900", "email": email, "requested_at": "2026-09-01T12:00:00Z", "reported_status": status,
            "reported_at": "2026-09-03T12:00:00Z", "audit_at": "2026-09-15T12:00:00Z", "request_text": text}


def account_delete(result="SUCCESS"):
    return {"activity_id": "activity_900", "event_time": "2026-09-03T11:00:00Z", "event_type": "DELETE_RECORD",
            "source_system": "deletion_worker", "target_system": "account_service", "resource_id": "account_900",
            "reported_result": result, "details": "Deletion worker submitted primary profile account_900."}


def bundle(collections):
    return json.dumps({"exported_at": "x", "source": "test", "snapshots": [
        {"captured_at": "x", "data_store": ds, "collection": col, "records": recs} for ds, col, recs in collections]})


class CustomCases(unittest.TestCase):
    def test_1_non_deletion_request(self):
        status, steps = run_case(req("Please send me a copy of my data. I still use the account, please don't delete anything."))
        self.assertEqual((status, steps), ("NOT_APPLICABLE", []))

    def test_2_uppercase_historical_email_and_old_hash(self):
        files = [("evidence_900", "evidence/records/b.json", "2026-09-10T00:00:00Z", bundle([
            ("analytics_platform", "customer_analytics_reports",
             [{"resource_id": "analytics_900", "user_id": None, "email": None, "phone": None, "email_hash": H_OLD}]),
            ("security_service", "security_audit_events", [{"resource_id": "audit_record_900", "subject_reference": "user_900"}]),
        ]))]
        status, steps = run_case(req("Please delete my account.", email="OLD.PERSON@EXAMPLE.COM"), [account_delete()], files)
        self.assertEqual(status, "INCOMPLETE")
        self.assertEqual(steps, [
            ("REPORT_EXPOSED_PII", "analytics_900", "evidence_900"),
            ("ANONYMIZE_RECORD", "analytics_900", ""),
            ("VERIFY_RECORD_ABSENT", "account_900", ""),
            ("VERIFY_RECORD_PRESENT", "audit_record_900", ""),
            ("VERIFY_RECORD_ANONYMIZED", "analytics_900", ""),
        ])

    def test_3_lookalike_and_404_lookup_are_not_ownership(self):
        log = "\n".join([
            "2026-09-10T00:00:00Z level=DEBUG service=account_service trace_id=rb-1 event=profile_lookup_started resource_id=account_777 lookup_key=test.person@example.com",
            "2026-09-10T00:00:01Z level=INFO service=account_service trace_id=rb-1 event=profile_lookup_completed resource_id=account_777 rows=0 http_status=404",
            "2026-09-10T00:00:02Z level=INFO service=search_service trace_id=rb-2 event=index_query_completed resource_id=search_901 result=hit email=test.person.jr@example.com",
            "2026-09-10T00:00:03Z level=INFO service=security_service trace_id=rb-3 event=audit_record_read_completed resource_id=audit_record_900 rows=1 subject_reference=user_900",
        ])
        files = [("evidence_900", "evidence/logs/t.log", "2026-09-10T00:00:05Z", log)]
        status, steps = run_case(req("Please delete my account."), [account_delete()], files)
        self.assertEqual(status, "COMPLETE")
        self.assertEqual(steps, [("VERIFY_RECORD_ABSENT", "account_900", "evidence_900"),
                                 ("VERIFY_RECORD_PRESENT", "audit_record_900", "evidence_900")])

    def test_4_evidence_after_cutoff_is_ignored(self):
        early = bundle([("search_service", "customer_search_documents",
                         [{"resource_id": "search_900", "document": {"email": None, "customer_reference": "user_900"}}])])
        late = bundle([("search_service", "customer_search_documents",
                        [{"resource_id": "search_902", "document": {"email": "test.person@example.com"}}])])
        files = [("evidence_900", "evidence/records/a.json", "2026-09-10T00:00:00Z", early),
                 ("evidence_901", "evidence/records/b.json", "2026-09-20T00:00:00Z", late)]
        status, steps = run_case(req("Please delete my account."), [account_delete()], files)
        self.assertNotIn("search_902", [r for _, r, _ in steps])
        self.assertTrue(all(ev != "evidence_901" for _, _, ev in steps))
        self.assertEqual(status, "INCOMPLETE")    # search_900 is still present at the cutoff

    def test_5_active_sync_and_restore_are_stopped_first(self):
        files = [("evidence_900", "evidence/records/b.json", "2026-09-10T00:00:00Z", bundle([
            ("integration_service", "connector_configurations",
             [{"resource_id": "data_flow_900", "subject_selector": "test.person@example.com", "enabled": True}]),
            ("backup_service", "backup_catalog",
             [{"resource_id": "backup_900", "subject_reference": "user_900", "restore_allowed": True}]),
            ("search_service", "customer_search_documents",
             [{"resource_id": "search_900", "document": {"email": "test.person@example.com"}}]),
        ]))]
        status, steps = run_case(req("Please delete my account."), [account_delete()], files)
        self.assertEqual(status, "INCOMPLETE")
        self.assertEqual([op for op, _, _ in steps], [
            "REPORT_REMAINING_RECORD", "REPORT_ACTIVE_DATA_FLOW", "REPORT_RESTORE_RISK",
            "DISABLE_DATA_FLOW", "BLOCK_RESTORE", "DELETE_RECORD",
            "VERIFY_RECORD_ABSENT", "VERIFY_RECORD_ABSENT", "VERIFY_DATA_FLOW_DISABLED", "VERIFY_RESTORE_BLOCKED"])


if __name__ == "__main__":
    unittest.main()
