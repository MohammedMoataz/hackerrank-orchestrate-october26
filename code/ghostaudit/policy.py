"""Deletion policy: what each data category must look like, and the steps that get it there.

Mirrors `dataset/deletion_rules.csv`. Each entry gives the compliant end state and, for a record
that is not compliant, the finding / remediation / verification operations.
"""
from __future__ import annotations

from dataclasses import dataclass

from .model import ABSENT, ACTIVE, ANONYMIZED, BLOCKED, DISABLED, IDENTIFIABLE, PRESENT, REDACTED


@dataclass(frozen=True)
class Treatment:
    rule: str
    compliant: frozenset           # observed states that satisfy the rule
    finding: str | None            # operation reporting a violation
    remediation: str | None
    verification: str              # operation proving the required end state
    retain: bool = False           # record must stay available


DELETE = dict(compliant=frozenset({ABSENT}), finding="REPORT_REMAINING_RECORD", remediation="DELETE_RECORD",
              verification="VERIFY_RECORD_ABSENT")
REDACT = dict(compliant=frozenset({REDACTED}), finding="REPORT_EXPOSED_PII", remediation="REDACT_RECORD",
              verification="VERIFY_RECORD_REDACTED")
ANONYMIZE = dict(compliant=frozenset({ANONYMIZED}), finding="REPORT_EXPOSED_PII", remediation="ANONYMIZE_RECORD",
                 verification="VERIFY_RECORD_ANONYMIZED")
RETAIN = dict(compliant=frozenset({PRESENT}), finding=None, remediation=None, verification="VERIFY_RECORD_PRESENT",
              retain=True)

POLICY: dict[str, Treatment] = {
    "USER_PROFILE": Treatment("rule_01", **DELETE),
    "SECONDARY_IDENTIFIER": Treatment("rule_02", **DELETE),
    "SEARCH_INDEX_ENTRY": Treatment("rule_03", **DELETE),
    "CACHE_ENTRY": Treatment("rule_04", **DELETE),
    "SUPPORT_MESSAGE": Treatment("rule_05", **REDACT),
    "SUPPORT_ATTACHMENT": Treatment("rule_06", **DELETE),
    "ANALYTICS_PROFILE": Treatment("rule_07", **ANONYMIZE),
    "PRODUCT_TELEMETRY": Treatment("rule_08", **ANONYMIZE),
    "USER_EXPORT": Treatment("rule_09", **DELETE),
    "MARKETING_PROFILE": Treatment("rule_10", **DELETE),
    "EMAIL_DELIVERY_LOG": Treatment("rule_11", **REDACT),
    "SECURITY_AUDIT_LOG": Treatment("rule_12", **RETAIN),
    "LEGAL_HOLD_RECORD": Treatment("rule_13", **RETAIN),
    "BACKUP_ARCHIVE": Treatment("rule_14", frozenset({BLOCKED}), "REPORT_RESTORE_RISK", "BLOCK_RESTORE",
                                "VERIFY_RESTORE_BLOCKED"),
    "ACCOUNT_TOMBSTONE": Treatment("rule_15", **REDACT),
    "DATA_FLOW": Treatment("flow", frozenset({DISABLED}), "REPORT_ACTIVE_DATA_FLOW", "DISABLE_DATA_FLOW",
                           "VERIFY_DATA_FLOW_DISABLED"),
}

# Default category per system when the evidence does not state one.
SYSTEM_CATEGORY = {
    "account_service": "USER_PROFILE", "search_service": "SEARCH_INDEX_ENTRY", "cache_service": "CACHE_ENTRY",
    "support_platform": "SUPPORT_MESSAGE", "analytics_platform": "ANALYTICS_PROFILE", "export_service": "USER_EXPORT",
    "marketing_platform": "MARKETING_PROFILE", "email_delivery_service": "EMAIL_DELIVERY_LOG",
    "security_service": "SECURITY_AUDIT_LOG", "legal_service": "LEGAL_HOLD_RECORD", "backup_service": "BACKUP_ARCHIVE",
    "identity_service": "ACCOUNT_TOMBSTONE", "integration_service": "DATA_FLOW", "object_storage": "SUPPORT_ATTACHMENT",
}


def treatment(category: str | None, system_id: str) -> Treatment | None:
    return POLICY.get(category or "") or POLICY.get(SYSTEM_CATEGORY.get(system_id, ""))


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
