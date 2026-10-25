"""Helpers shared by the evidence readers: identifier extraction and per-system state rules."""
from __future__ import annotations

import re

from ..loader import EMAIL_RE, HASH_RE, USER_RE, norm_email, norm_phone
from ..model import (ABSENT, ACTIVE, ANONYMIZED, BLOCKED, DISABLED, IDENTIFIABLE, PRESENT, REDACTED,
                     Observation, system_of)

NULLS = {None, "", "null", "none", "None", "NULL"}
PHONE_FIELDS = {"phone", "requester_phone", "owner_phone"}
# Fields whose value is the key a lookup was made with, not content of the record.
QUERY_FIELDS = {"lookup_key", "subject_key", "scan_key", "owner_key", "match_key", "query"}
DIRECT_ID_FIELDS = ("email", "phone", "email_hash", "full_name", "name", "display_name", "requester_email",
                    "requester_name", "requester_phone", "owner_email", "owner_phone", "customer_email")

# Ledger results -> observed state.
RESULT_STATE = {
    "FOUND": PRESENT, "NOT_FOUND": ABSENT, "IDENTIFIABLE": IDENTIFIABLE, "REDACTED": REDACTED,
    "ANONYMIZED": ANONYMIZED, "ACTIVE": ACTIVE, "DISABLED": DISABLED, "BLOCKED": BLOCKED,
}


def is_null(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip() in NULLS)


def ids_in_value(value, field: str = "") -> set[str]:
    """Normalised identifiers inside one value: emails, sha256 email hashes, user ids, phones."""
    out: set[str] = set()
    if is_null(value) or isinstance(value, bool):
        return out
    if isinstance(value, dict):
        for k, v in value.items():
            out |= ids_in_value(v, k)
        return out
    if isinstance(value, list):
        for v in value:
            out |= ids_in_value(v, field)
        return out
    s = str(value)
    out |= {norm_email(e) for e in EMAIL_RE.findall(s)}
    out |= {h.lower() for h in HASH_RE.findall(s.lower())}
    out |= set(USER_RE.findall(s))
    if field in PHONE_FIELDS and len(norm_phone(s)) >= 7:
        out.add("tel:" + norm_phone(s))
    return out


def record_ids(rec: dict, skip: set = frozenset()) -> set[str]:
    out: set[str] = set()
    for k, v in rec.items():
        if k in QUERY_FIELDS or k in skip or k == "resource_id":
            continue
        out |= ids_in_value(v, k)
    return out


def has_direct_identifiers(rec: dict) -> bool:
    return any(not is_null(rec.get(f)) for f in DIRECT_ID_FIELDS if f in rec)


def truthy(v) -> bool | None:
    if isinstance(v, bool):
        return v
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("true", "1", "yes", "allow", "allowed"):
        return True
    if s in ("false", "0", "no", "deny", "denied"):
        return False
    return None


def state_of_record(system: str, rec: dict, collection: str = "") -> tuple[str, str | None]:
    """(state, category) for a structured record of a given system.

    Presence of the record is assumed; flags and identifier fields refine the state.
    """
    col = collection.lower()
    if system == "account_service":
        status = str(rec.get("status_code", rec.get("http_status", ""))).strip()
        if status == "404" or rec.get("profile", "missing") is None:
            return ABSENT, "USER_PROFILE"
        return PRESENT, "USER_PROFILE"
    if system == "search_service":
        hits = rec.get("hits")
        if isinstance(hits, dict) and not hits.get("total"):
            return ABSENT, "SEARCH_INDEX_ENTRY"
        return PRESENT, "SEARCH_INDEX_ENTRY"
    if system == "analytics_platform":
        attributable = has_direct_identifiers(rec) or not is_null(rec.get("user_id")) or not is_null(rec.get("customer_reference"))
        return (IDENTIFIABLE if attributable else ANONYMIZED), "ANALYTICS_PROFILE"
    if system == "support_platform":
        if "attachment" in col or "file_name" in rec or rec.get("storage_class") == "ticket_attachment":
            return PRESENT, "SUPPORT_ATTACHMENT"
        text_ids = ids_in_value(rec.get("message_text"), "message_text") - set(USER_RE.findall(str(rec.get("message_text", ""))))
        identifiable = has_direct_identifiers(rec) or bool(text_ids)
        return (IDENTIFIABLE if identifiable else REDACTED), "SUPPORT_MESSAGE"
    if system == "export_service":
        avail = truthy(rec.get("download_available", rec.get("available")))
        return (ABSENT if avail is False else PRESENT), "USER_EXPORT"
    if system == "integration_service":
        en = truthy(rec.get("enabled"))
        return (DISABLED if en is False else ACTIVE), "DATA_FLOW"
    if system == "backup_service":
        ra = truthy(rec.get("restore_allowed"))
        return (BLOCKED if ra is False else ACTIVE), "BACKUP_ARCHIVE"
    if system == "security_service":
        return PRESENT, "SECURITY_AUDIT_LOG"
    if system == "identity_service":
        return (IDENTIFIABLE if has_direct_identifiers(rec) else REDACTED), "ACCOUNT_TOMBSTONE"
    if system == "legal_service":
        return PRESENT, "LEGAL_HOLD_RECORD"
    if system == "marketing_platform":
        return PRESENT, "MARKETING_PROFILE"
    if system == "email_delivery_service":
        return (IDENTIFIABLE if has_direct_identifiers(rec) else REDACTED), "EMAIL_DELIVERY_LOG"
    if system == "cache_service":
        return PRESENT, "CACHE_ENTRY"
    if system == "object_storage":
        return PRESENT, "SUPPORT_ATTACHMENT"
    return PRESENT, None


def ledger_observation(file_id, captured_at, rec: dict, id_field: str, source: str):
    """A ledger row states record type and result outright; its subject column names the person."""
    rid = rec.get("resource_id", "")
    system = rec.get("system") or system_of(rid)
    if not system:
        return None
    state = RESULT_STATE.get(str(rec.get("result", "")).upper())
    if state is None:
        return None
    category = rec.get("record_type")
    if system == "integration_service":
        category = "DATA_FLOW"
    return Observation(file_id, captured_at, system, rid, state, category,
                       frozenset(ids_in_value(rec.get(id_field), id_field)), frozenset(), source,
                       f"{rec.get('record_type')}={rec.get('result')}")
