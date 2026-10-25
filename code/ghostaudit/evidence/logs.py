"""Service logs in several syntaxes, read with one tolerant tokenizer.

Supported line shapes: `key=value` / `key="value"`, JSON objects, syslog headers, `[LEVEL] [service]
[trace] event:` traces, `| LEVEL | service | trace | event |` streams, and cloud exports whose
payload is an escaped string. Lines sharing a trace id are merged: a lookup's "started" line holds
the key it searched for, the "completed" line holds the resource and the outcome.
"""
from __future__ import annotations

import json
import re
from collections import OrderedDict

from ..model import ABSENT, ACTIVE, ANONYMIZED, BLOCKED, DISABLED, IDENTIFIABLE, PRESENT, REDACTED, Observation, RESOURCE_RE, system_of
from .common import QUERY_FIELDS, RESULT_STATE, ids_in_value, is_null, truthy

PAIR_RE = re.compile(r'"?([A-Za-z_][A-Za-z0-9_]*)"?\s*[=:]\s*("([^"]*)"|[^\s,}|]+)')
TRACE_RE = re.compile(r"\b(?:tr|rb)-[A-Za-z0-9-]+")
EVENT_RES = [re.compile(r"\]\s+([a-z_]+):"), re.compile(r"\|\s*([a-z_]+)\s*\|\s*[A-Za-z_]+=")]
CONTENT_FIELDS = {"email", "customer_email", "owner_email", "requester_email", "customer_reference",
                  "subject_reference", "correlation_key", "matched_value", "email_hash", "phone",
                  "requester_phone", "subject_ref", "requester_name"}
POSITIVE, NEGATIVE = "positive", "negative"


def tokenize(line: str) -> dict:
    line = line.replace('\\"', '"')
    kv: dict = {}
    brace = line.find("{")
    if brace != -1 and line.rstrip().endswith("}"):
        try:
            kv.update({k: v for k, v in json.loads(line[brace:]).items()})
        except json.JSONDecodeError:
            pass
    for key, raw, quoted in PAIR_RE.findall(line):
        if key not in kv:
            kv[key] = quoted if raw.startswith('"') else raw
    if "event" not in kv or not kv["event"] or kv["event"] == "instance=":
        for rx in EVENT_RES:
            m = rx.search(line)
            if m:
                kv["event"] = m.group(1)
                break
    m = TRACE_RE.search(line)
    if m:
        kv["_trace"] = m.group(0)
    return kv


def _outcome(ev: dict) -> tuple[str | None, str | None, str]:
    """(state, category, polarity) for a merged lookup."""
    e = str(ev.get("event", ""))
    rows = ev.get("rows")
    http = str(ev.get("http_status", ""))
    if "record_type" in ev and "result" in ev:
        st = RESULT_STATE.get(str(ev["result"]).upper())
        return st, ev.get("record_type"), (NEGATIVE if st == ABSENT else POSITIVE)
    if e.startswith("profile_lookup"):
        absent = http == "404" or str(rows) == "0"
        return (ABSENT if absent else PRESENT), "USER_PROFILE", (NEGATIVE if absent else POSITIVE)
    if e.startswith("index_query"):
        hit = str(ev.get("result", "")).lower() == "hit" or str(ev.get("total_hits", "0")) not in ("0", "")
        return (PRESENT if hit else ABSENT), "SEARCH_INDEX_ENTRY", (POSITIVE if hit else NEGATIVE)
    if e in ("analytics_profile_read", "analytics_profile_read_completed"):
        ident = str(ev.get("direct_identifiers", "")) not in ("", "0") or any(
            not is_null(ev.get(k)) for k in ("email", "phone", "email_hash", "customer_reference"))
        return (IDENTIFIABLE if ident else ANONYMIZED), "ANALYTICS_PROFILE", POSITIVE
    if e == "analytics_identity_scan":
        return IDENTIFIABLE, "ANALYTICS_PROFILE", POSITIVE
    if e == "contact_lookup_completed":
        # A contact record keyed by an identifier hash: a secondary identifier, not a profile.
        found = str(rows) not in ("0", "")
        return (PRESENT if found else ABSENT), "SECONDARY_IDENTIFIER", (POSITIVE if found else NEGATIVE)
    if e == "message_pii_scan":
        return IDENTIFIABLE, "SUPPORT_MESSAGE", POSITIVE
    if e == "attachment_pii_scan":
        return PRESENT, "SUPPORT_ATTACHMENT", POSITIVE
    if e == "message_read":
        redacted = "[REDACTED]" in str(ev.get("message_text", "")) or is_null(ev.get("message_text"))
        return (REDACTED if redacted else IDENTIFIABLE), "SUPPORT_MESSAGE", POSITIVE
    if e == "support_ticket_read_completed":
        ident = any(not is_null(ev.get(k)) for k in ("requester_email", "requester_name", "requester_phone"))
        return (IDENTIFIABLE if ident else REDACTED), "SUPPORT_MESSAGE", POSITIVE
    if e in ("contact_query_completed",):
        found = str(rows) not in ("0", "")
        return (PRESENT if found else ABSENT), "SECONDARY_IDENTIFIER", (POSITIVE if found else NEGATIVE)
    if e == "deletion_marker_check":
        return (PRESENT if truthy(ev.get("marker_found")) is False else ABSENT), "SECONDARY_IDENTIFIER", POSITIVE
    if e.startswith("audit_record_read"):
        found = str(rows) not in ("0",)
        return (PRESENT if found else ABSENT), "SECURITY_AUDIT_LOG", (POSITIVE if found else NEGATIVE)
    if e in ("connector_config_read_completed", "connector_heartbeat", "connector_config_loaded"):
        en = truthy(ev.get("enabled"))
        return (DISABLED if en is False else ACTIVE), "DATA_FLOW", POSITIVE
    if e == "restore_policy_read_completed":
        ra = truthy(ev.get("restore_allowed"))
        return (BLOCKED if ra is False else ACTIVE), "BACKUP_ARCHIVE", POSITIVE
    if e == "restore_candidate_evaluated":
        risky = truthy(ev.get("eligible")) is not False and truthy(ev.get("deletion_block")) is not True
        return (ACTIVE if risky else BLOCKED), "BACKUP_ARCHIVE", POSITIVE
    if e == "restore_authorization_completed":
        allowed = truthy(ev.get("decision"))
        return (BLOCKED if allowed is False else ACTIVE), "BACKUP_ARCHIVE", POSITIVE
    if e in ("export_download_check_completed", "export_metadata_read_completed"):
        av = truthy(ev.get("available"))
        return (ABSENT if av is False else PRESENT), "USER_EXPORT", (NEGATIVE if av is False else POSITIVE)
    return None, None, POSITIVE


def parse(path, file_id, captured_at) -> list[Observation]:
    groups: "OrderedDict[str, list[dict]]" = OrderedDict()
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            kv = tokenize(line)
            groups.setdefault(kv.get("_trace") or f"line-{n}", []).append(kv)
    out = []
    for lines in groups.values():
        keys, content = set(), set()
        for kv in lines:
            started = str(kv.get("event", "")).endswith("_started")
            for k, v in kv.items():
                if k in QUERY_FIELDS or (started and k in CONTENT_FIELDS):
                    keys |= ids_in_value(v, k)
        for kv in lines:
            if str(kv.get("event", "")).endswith("_started"):
                continue
            rid = kv.get("resource_id")
            if not rid or not RESOURCE_RE.fullmatch(str(rid)):
                continue
            system = kv.get("system") or system_of(rid)
            if not system:
                continue
            state, category, polarity = _outcome(kv)
            if state is None:
                continue
            content = set()
            for k in CONTENT_FIELDS:
                if k in kv:
                    content |= ids_in_value(kv[k], k)
            ids = content | (keys if polarity == POSITIVE else set())
            weak = keys if polarity == NEGATIVE else set()
            out.append(Observation(file_id, captured_at, system, rid, state, category, frozenset(ids),
                                   frozenset(weak), "log", str(kv.get("event", ""))))
    return out
