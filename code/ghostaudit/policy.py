"""Deletion policy: what each data category must look like, and the steps that get it there.

The policy is built from `dataset/deletion_rules.csv` at run time. Each rule's `required_action`
(DELETE, REDACT, ANONYMIZE, RETAIN) maps to a treatment: the compliant end state and, for a record
that is not compliant, the finding / remediation / verification operations. Adding a category to
the CSV needs no code change as long as it uses one of these actions.
"""
from __future__ import annotations

from dataclasses import dataclass

from .model import ABSENT, ANONYMIZED, BLOCKED, DISABLED, IDENTIFIABLE, PRESENT, REDACTED


@dataclass(frozen=True)
class Treatment:
    rule: str
    compliant: frozenset[str]      # observed states that satisfy the rule
    finding: str | None            # operation reporting a violation
    remediation: str | None
    verification: str              # operation proving the required end state
    retain: bool = False           # record must stay available


ACTIONS: dict[str, dict] = {
    "DELETE": dict(compliant=frozenset({ABSENT}), finding="REPORT_REMAINING_RECORD", remediation="DELETE_RECORD",
                   verification="VERIFY_RECORD_ABSENT"),
    "REDACT": dict(compliant=frozenset({REDACTED}), finding="REPORT_EXPOSED_PII", remediation="REDACT_RECORD",
                   verification="VERIFY_RECORD_REDACTED"),
    "ANONYMIZE": dict(compliant=frozenset({ANONYMIZED}), finding="REPORT_EXPOSED_PII", remediation="ANONYMIZE_RECORD",
                      verification="VERIFY_RECORD_ANONYMIZED"),
    "RETAIN": dict(compliant=frozenset({PRESENT}), finding=None, remediation=None,
                   verification="VERIFY_RECORD_PRESENT", retain=True),
}
# A retained archive whose rule condition is about restore access keeps the archive but must not be
# able to restore the person's data (rule_14: "Restore access can be blocked").
RESTORE_GUARD = dict(compliant=frozenset({BLOCKED}), finding="REPORT_RESTORE_RISK", remediation="BLOCK_RESTORE",
                     verification="VERIFY_RESTORE_BLOCKED")
# Data flows are processes, not stored records, so the rules file has no row for them; the output
# contract's flow operations define their treatment.
DATA_FLOW = Treatment("contract:data_flow", frozenset({DISABLED}), "REPORT_ACTIVE_DATA_FLOW", "DISABLE_DATA_FLOW",
                      "VERIFY_DATA_FLOW_DISABLED")

# Default category per system when the evidence does not state one.
SYSTEM_CATEGORY = {
    "account_service": "USER_PROFILE", "search_service": "SEARCH_INDEX_ENTRY", "cache_service": "CACHE_ENTRY",
    "support_platform": "SUPPORT_MESSAGE", "analytics_platform": "ANALYTICS_PROFILE", "export_service": "USER_EXPORT",
    "marketing_platform": "MARKETING_PROFILE", "email_delivery_service": "EMAIL_DELIVERY_LOG",
    "security_service": "SECURITY_AUDIT_LOG", "legal_service": "LEGAL_HOLD_RECORD", "backup_service": "BACKUP_ARCHIVE",
    "identity_service": "ACCOUNT_TOMBSTONE", "integration_service": "DATA_FLOW", "object_storage": "SUPPORT_ATTACHMENT",
}


class Policy:
    def __init__(self, rules: list[dict]):
        self.by_category: dict[str, Treatment] = {"DATA_FLOW": DATA_FLOW}
        for r in rules:
            action = r["required_action"].strip().upper()
            spec = RESTORE_GUARD if action == "RETAIN" and "restore" in r["condition"].lower() else ACTIONS.get(action)
            if spec is None:
                raise ValueError(f"{r['rule_id']}: unsupported action {action!r}")
            self.by_category[r["data_category"]] = Treatment(r["rule_id"], **spec)

    def treatment(self, category: str | None, system_id: str) -> Treatment | None:
        return self.by_category.get(category or "") or self.by_category.get(SYSTEM_CATEGORY.get(system_id, ""))


def normalise_state(state: str, t: Treatment) -> str:
    """Map an observed state onto the vocabulary of the rule (PRESENT records under a redact or
    anonymize rule still expose identifiers)."""
    if state == PRESENT and t.finding == "REPORT_EXPOSED_PII":
        return IDENTIFIABLE
    if state == IDENTIFIABLE and t.finding == "REPORT_REMAINING_RECORD":
        return PRESENT
    return state


def violates(state: str, t: Treatment) -> bool:
    if t.retain:
        return state != PRESENT
    return state not in t.compliant
