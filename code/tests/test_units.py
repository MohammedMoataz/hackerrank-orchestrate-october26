"""Unit tests for the pieces most likely to break silently. Run: python3 -m unittest discover code/tests"""
import ast
import sys
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE))

from ghostaudit import intent, policy  # noqa: E402
from ghostaudit.evidence.logs import tokenize  # noqa: E402
from ghostaudit.model import OPERATION_ORDER, Step  # noqa: E402


class IntentTest(unittest.TestCase):
    NON_DELETION = [
        "The mobile number on my profile is out of date. Please replace it with the new one and leave the account active.",
        "Please stop the promotional emails. I still need the account and my order history, so I am not asking for deletion.",
        "I'd like to download my account information in a portable format. Please keep the account as it is.",
        "I can't access my profile and need help resetting the login. Do not close the account.",
        "My surname is misspelled on the account. Can you correct it without removing any of my records?",
        "Please remove me from marketing lists only. I still want receipts and service messages for this account.",
        "Can you tell me what personal information you hold about me? This is an information request, not a request to erase it.",
        "I need a copy of last year's invoices for my records. Please leave my profile and purchase history in place.",
        "Please change the email address used for this account. I want to continue using the service.",
        "Could you send me a copy of the information held on my account? I still use it, so please don't delete or change anything.",
    ]
    DELETION = [
        "I deleted this account and received a confirmation, but the same email address is still recognized. Please remove any remaining copy of my profile.",
        "The privacy page still says my request failed. Please inspect the actual systems and tell me whether the account and identifiable analytics data have already been removed.",
        "Je demande la suppression définitive du compte associé à cette adresse e-mail.",
        "このメールアドレスに関連するアカウントの完全な削除を依頼します。",
        "이 이메일 주소에 연결된 계정의 영구 삭제를 요청합니다.",
        "Solicito a exclusão permanente da conta associada a este e-mail.",
    ]

    def test_non_deletion(self):
        for t in self.NON_DELETION:
            self.assertFalse(intent.classify(t)[0], t)

    def test_deletion(self):
        for t in self.DELETION:
            self.assertTrue(intent.classify(t)[0], t)


class LogTokenizerTest(unittest.TestCase):
    def test_shapes(self):
        lines = {
            'kv': '2026-09-26T07:49:50Z level=INFO service=account_service trace_id=rb-074950-001 event=profile_lookup_completed resource_id=account_2064 rows=0 http_status=404',
            'bracket': '2026-07-28T05:51:21Z [INFO] [account_service] [tr-6074163] profile_lookup_completed: resource_id="account_7947" rows="0" http_status="404"',
            'pipe': '2026-07-03T07:52:15Z | INFO | account_service | tr-9500772 | profile_lookup_completed | resource_id="account_4512" rows="0" http_status="404"',
            'json': '2026-09-16T08:57:34Z {"severity":"INFO","service":"account_service","trace_id":"tr-1463969","resource_id":"account_3960","event":"profile_lookup_completed","rows":0}',
            'cloud': '2026-09-30T11:51:03Z requestId=tr-2263120 level=DEBUG function=profile_service message="resource_id=\\"account_66777\\" event=\\"profile_lookup_completed\\" rows=\\"1\\" http_status=\\"200\\""',
            'syslog': '2026-08-22T10:51:52Z <14>1 node-2 account_service tr-9320077 - - level=INFO resource_id="account_9580" event="profile_lookup_completed" rows="0" http_status="404"',
        }
        for name, line in lines.items():
            kv = tokenize(line)
            self.assertEqual(kv.get("event"), "profile_lookup_completed", name)
            self.assertTrue(kv.get("resource_id", "").startswith("account_"), name)
            self.assertTrue(kv.get("_trace", "").startswith(("tr-", "rb-")), name)


class PolicyTest(unittest.TestCase):
    def test_policy_follows_rules_file(self):
        import csv
        with open(CODE.parent / "dataset" / "deletion_rules.csv", encoding="utf-8") as f:
            rules = list(csv.DictReader(f))
        pol = policy.Policy(rules)
        expected = {"DELETE": "DELETE_RECORD", "REDACT": "REDACT_RECORD", "ANONYMIZE": "ANONYMIZE_RECORD"}
        for r in rules:
            t = pol.by_category[r["data_category"]]
            if r["required_action"] == "RETAIN" and "restore" in r["condition"].lower():
                self.assertEqual(t.remediation, "BLOCK_RESTORE", r)        # archive kept, restore blocked
            elif r["required_action"] == "RETAIN":
                self.assertTrue(t.retain and t.verification == "VERIFY_RECORD_PRESENT", r)
            else:
                self.assertEqual(t.remediation, expected[r["required_action"]], r)

    def test_unknown_action_is_rejected(self):
        with self.assertRaises(ValueError):
            policy.Policy([{"rule_id": "x", "data_category": "X", "condition": "", "required_action": "SHRED"}])

    def test_canonical_order(self):
        steps = [Step("VERIFICATION", "search_service", "search_1", "VERIFY_RECORD_ABSENT", "ABSENT"),
                 Step("REMEDIATION", "search_service", "search_1", "DELETE_RECORD", "ABSENT"),
                 Step("REMEDIATION", "integration_service", "data_flow_9", "DISABLE_DATA_FLOW", "DISABLED"),
                 Step("FINDING", "analytics_platform", "analytics_1", "REPORT_EXPOSED_PII", "PRESENT"),
                 Step("FINDING", "search_service", "search_1", "REPORT_REMAINING_RECORD", "PRESENT")]
        ops = [s.operation for s in sorted(steps, key=Step.sort_key)]
        self.assertEqual(ops, ["REPORT_REMAINING_RECORD", "REPORT_EXPOSED_PII", "DISABLE_DATA_FLOW",
                               "DELETE_RECORD", "VERIFY_RECORD_ABSENT"])
        self.assertEqual(len(OPERATION_ORDER), 15)


class AttributionCostTest(unittest.TestCase):
    """The precedence encoded in the linker's costs: content link > claim consistency > own evidence > timing."""

    def test_precedence(self):
        from ghostaudit import linker as L
        self.assertLess(L.COST_CONTENT_LINK, L.COST_CLAIM_MATCH - L.COST_CLAIM_MISMATCH + L.COST_OWN_EVIDENCE)
        self.assertLess(L.COST_CLAIM_MATCH - L.COST_CLAIM_MISMATCH, L.COST_OWN_EVIDENCE)
        # timing (|offset| of at most ~3 h inside the run window) never outweighs shared evidence
        self.assertLess(3.0, -L.COST_OWN_EVIDENCE)


class LeakageTest(unittest.TestCase):
    def test_predictor_never_reads_labels(self):
        """Only code/evaluation may open sample_output.csv."""
        for path in (CODE / "ghostaudit").rglob("*.py"):
            self.assertNotIn("sample_output", path.read_text(encoding="utf-8"), path)
        self.assertNotIn("sample_output", (CODE / "main.py").read_text(encoding="utf-8"))

    def test_no_hardcoded_case_ids(self):
        for path in list((CODE / "ghostaudit").rglob("*.py")) + [CODE / "main.py"]:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    self.assertNotRegex(node.value, r"^case_\d+$", path)


if __name__ == "__main__":
    unittest.main()
