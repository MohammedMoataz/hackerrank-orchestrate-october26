"""SQL snapshot exports, loaded into an in-memory SQLite database.

Captures can hold a primary next to read, regional, reporting or failover replicas. A record found
in any table is present: a profile deleted from the primary but still on a replica is replication
drift and still exposes the person.
"""
from __future__ import annotations

import json
import sqlite3

from ..model import Observation, system_of
from .common import record_ids, state_of_record

# Table name fragment -> collection name used by state_of_record.
TABLE_COLLECTION = {
    "support_records": "support_records",
    "customer_exports": "customer_exports",
}


def parse(path, file_id, captured_at) -> list[Observation]:
    con = sqlite3.connect(":memory:")
    with open(path, encoding="utf-8") as f:
        con.executescript(f.read())
    out = []
    tables = [t for (t,) in con.execute("select name from sqlite_master where type='table'")]
    for table in tables:
        cur = con.execute(f'select * from "{table}"')
        cols = [d[0] for d in cur.description]
        for row in cur.fetchall():
            rec = dict(zip(cols, row))
            if "record_json" in rec:
                inner = json.loads(rec["record_json"])
                collection = rec.get("collection_name", "")
                rec = inner
            else:
                collection = TABLE_COLLECTION.get(table, table)
            rid = rec.get("resource_id")
            system = system_of(rid or "")
            if not system:
                continue
            if "account_status" in rec and str(rec["account_status"]).upper() == "DELETED" and system == "account_service":
                continue
            state, category = state_of_record(system, rec, collection)
            out.append(Observation(file_id, captured_at, system, rid, state, category,
                                   frozenset(record_ids(rec)), "sql", table))
    con.close()
    return out
