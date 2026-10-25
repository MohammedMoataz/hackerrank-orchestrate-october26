"""JSON evidence: ledgers, snapshot bundles, service resource exports and single-collection captures."""
from __future__ import annotations

import json

from ..model import Observation, system_of
from .common import ledger_observation, record_ids, state_of_record


def parse(path, file_id, captured_at) -> list[Observation]:
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    out: list[Observation] = []
    if isinstance(doc.get("snapshots"), list):                       # snapshot bundle
        for snap in doc["snapshots"]:
            out += _collection(snap.get("records", []), snap.get("collection", ""), file_id, captured_at, "snapshot_bundle")
    elif isinstance(doc.get("service_exports"), dict):               # service resource export
        for _service, lists in doc["service_exports"].items():
            for name, recs in lists.items():
                out += _collection(recs, name, file_id, captured_at, "service_export")
    elif isinstance(doc.get("records"), list):                       # ledger or single collection
        out += _collection(doc["records"], doc.get("collection", ""), file_id, captured_at, "records")
    return out


def _collection(recs, collection, file_id, captured_at, source) -> list[Observation]:
    out = []
    for rec in recs:
        if not isinstance(rec, dict) or "resource_id" not in rec:
            continue
        if "record_type" in rec and "result" in rec:                 # explicit ledger row
            id_field = "subject_reference" if "subject_reference" in rec else "lookup_value"
            ob = ledger_observation(file_id, captured_at, rec, id_field, source + ":ledger")
            if ob:
                out.append(ob)
            continue
        rid = rec["resource_id"]
        system = system_of(rid)
        if not system:
            continue
        state, category = state_of_record(system, rec, collection)
        ids = record_ids(rec)
        hits = rec.get("hits")
        if isinstance(hits, dict):                                   # index query: the documents are the content
            ids = record_ids({"documents": hits.get("documents", [])})
        out.append(Observation(file_id, captured_at, system, rid, state, category, frozenset(ids), frozenset(),
                               source, collection))
    return out
