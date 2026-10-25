"""Shared data types and vocabularies."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Resource id prefix -> system that owns it. Matches the system_id values used in sample_output.csv.
PREFIX_SYSTEM = {
    "account": "account_service",
    "search": "search_service",
    "analytics": "analytics_platform",
    "support": "support_platform",
    "export": "export_service",
    "data_flow": "integration_service",
    "backup": "backup_service",
    "audit_record": "security_service",
    "tombstone": "identity_service",
    "legal_hold": "legal_service",
    "cache": "cache_service",
    "email_delivery": "email_delivery_service",
    "marketing": "marketing_platform",
    "object": "object_storage",
}
RESOURCE_RE = re.compile(r"\b(?:" + "|".join(sorted(PREFIX_SYSTEM, key=len, reverse=True)) + r")_\d+\b")

# Observed record states (what evidence shows at one moment).
PRESENT = "PRESENT"            # the record exists (and, for delete-type records, that is a problem)
ABSENT = "ABSENT"              # the record does not exist
IDENTIFIABLE = "IDENTIFIABLE"  # the record exists and still carries direct identifiers
REDACTED = "REDACTED"          # the record exists with direct identifiers removed
ANONYMIZED = "ANONYMIZED"      # the record exists and is no longer attributable
ACTIVE = "ACTIVE"              # a data flow is enabled / a backup can be restored
DISABLED = "DISABLED"          # a data flow is stopped
BLOCKED = "BLOCKED"            # restore access to a backup is blocked

# Step vocabulary and canonical order (problem_statement.md, "Allowed Operations").
OPERATION_ORDER = [
    ("FINDING", "REPORT_REMAINING_RECORD", "PRESENT"),
    ("FINDING", "REPORT_EXPOSED_PII", "PRESENT"),
    ("FINDING", "REPORT_ACTIVE_DATA_FLOW", "ACTIVE"),
    ("FINDING", "REPORT_RESTORE_RISK", "ACTIVE"),
    ("REMEDIATION", "DISABLE_DATA_FLOW", "DISABLED"),
    ("REMEDIATION", "BLOCK_RESTORE", "BLOCKED"),
    ("REMEDIATION", "DELETE_RECORD", "ABSENT"),
    ("REMEDIATION", "REDACT_RECORD", "REDACTED"),
    ("REMEDIATION", "ANONYMIZE_RECORD", "ANONYMIZED"),
    ("VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT"),
    ("VERIFICATION", "VERIFY_RECORD_PRESENT", "PRESENT"),
    ("VERIFICATION", "VERIFY_RECORD_REDACTED", "REDACTED"),
    ("VERIFICATION", "VERIFY_RECORD_ANONYMIZED", "ANONYMIZED"),
    ("VERIFICATION", "VERIFY_DATA_FLOW_DISABLED", "DISABLED"),
    ("VERIFICATION", "VERIFY_RESTORE_BLOCKED", "BLOCKED"),
]
OP_RANK = {op: i for i, (_, op, _) in enumerate(OPERATION_ORDER)}
OP_PHASE = {op: phase for phase, op, _ in OPERATION_ORDER}
OP_STATE = {op: state for _, op, state in OPERATION_ORDER}


def system_of(resource_id: str) -> str | None:
    prefix = resource_id.rsplit("_", 1)[0]
    return PREFIX_SYSTEM.get(prefix)


@dataclass
class Request:
    case_id: str
    email: str
    requested_at: str
    reported_status: str
    reported_at: str
    audit_at: str
    request_text: str


@dataclass
class Activity:
    activity_id: str
    event_time: str
    event_type: str
    source_system: str
    target_system: str
    resource_id: str
    reported_result: str
    details: str


@dataclass
class Observation:
    """One fact an evidence file states about one resource.

    `ids` are identifiers found inside the record itself (proof of ownership). `keys` are values
    a lookup was keyed by (a query, which proves nothing when the lookup returned nothing).
    """
    file_id: str
    captured_at: str
    system_id: str
    resource_id: str
    state: str
    category: str | None = None
    ids: frozenset = frozenset()
    keys: frozenset = frozenset()
    source: str = ""
    detail: str = ""


@dataclass
class Step:
    phase: str
    system_id: str
    resource_id: str
    operation: str
    state: str
    evidence_id: str = ""

    def sort_key(self):
        return (OP_RANK[self.operation], self.system_id, self.resource_id)


@dataclass
class CaseResult:
    case_id: str
    status: str
    steps: list = field(default_factory=list)
    notes: list = field(default_factory=list)
