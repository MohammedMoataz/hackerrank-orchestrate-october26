"""Connect resources to people, and each deletion request to the resources it concerns.

Three kinds of link, strongest first:
1. Content: an identifier of the person appears inside the record (email, old email hash, phone,
   user_id), or a lookup keyed by the person's identifier returned the record.
2. Catalog: a data-catalog activity row states that a resource belongs to the person.
3. Workflow run: the deletion worker processes each request's records within about two hours of
   the request's `reported_at`. Records that no longer carry identifiers (a deleted account, an
   anonymized analytics profile) can only be tied to a request this way. Runs of requests reported
   at the same moment interleave, so ties are settled jointly across all requests.

Activity rows are claims about what happened; they are used here only to find which resources a
request concerns, never to decide their state.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta

from . import intent
from .identity import IdentityIndex
from .loader import Dataset
from .model import Observation, system_of

RUN_BEFORE = timedelta(hours=1.6)
RUN_AFTER = timedelta(hours=2.6)
ACCOUNT_AFTER = timedelta(hours=0.4)
CATALOG_RE = re.compile(r"(?:linked|confirmed) (\S+) \(([^)]+)\) (?:to|belongs only to) (\S+) and (user_\d+)")
CLAIM_MATCH = {"COMPLETE": "SUCCESS", "PARTIALLY_COMPLETE": "PARTIAL", "NOT_STARTED": "FAILED"}


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class Linker:
    def __init__(self, ds: Dataset, idx: IdentityIndex, observations: list[Observation]):
        self.ds, self.idx = ds, idx
        self.obs_by_rid: dict[str, list[Observation]] = defaultdict(list)
        # user -> resource -> list of (time, source, file_or_activity)
        self.links: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        self.weak: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        for ob in observations:
            self.obs_by_rid[ob.resource_id].append(ob)
            for uid in {idx.owner(i) for i in ob.ids} - {None}:
                self.links[uid][ob.resource_id].append((ob.captured_at, "content", ob.file_id))
            for uid in {idx.owner(k) for k in ob.keys} - {None}:
                self.weak[uid][ob.resource_id].append((ob.captured_at, "lookup-key", ob.file_id))
        self.docref: dict[str, str] = {}
        for a in ds.activities:
            if a.event_type == "LINK_RESOURCE_IDENTITY":
                m = CATALOG_RE.search(a.details)
                if m:
                    rid, ref, _email, uid = m.groups()
                    self.links[uid][rid].append((a.event_time, "catalog", a.activity_id))
                    self.docref[ref] = rid
        self.run_owner: dict[str, str] = {}      # resource -> case_id, from joint run attribution
        self.run_notes: dict[str, str] = {}
        self._attribute_runs()

    # -- per-request views -------------------------------------------------------------------
    def linked(self, uid: str, audit_at: str) -> dict[str, list]:
        return {rid: [l for l in ls if l[0] <= audit_at] for rid, ls in self.links.get(uid, {}).items()
                if any(l[0] <= audit_at for l in ls)}

    def evidence_files(self, uid: str, audit_at: str) -> set[str]:
        return {l[2] for ls in self.linked(uid, audit_at).values() for l in ls if l[1] == "content"}

    def run_window(self, req) -> list:
        rep = ts(req.reported_at)
        return [a for a in self.ds.activities
                if a.source_system == "deletion_worker" and rep - RUN_BEFORE <= ts(a.event_time) <= rep + RUN_AFTER]

    # -- joint attribution of workflow-run activity -------------------------------------------
    def _attribute_runs(self) -> None:
        reqs = self.ds.all_requests
        subj = {r.case_id: self.idx.subject(r.email) for r in reqs}
        files = {r.case_id: self.evidence_files(subj[r.case_id], r.audit_at) if subj[r.case_id] else set() for r in reqs}
        cands: dict[str, set[str]] = defaultdict(set)   # resource -> candidate case ids
        acts: dict[str, object] = {}
        for r in reqs:
            if not subj[r.case_id] or not intent.classify(r.request_text)[0]:
                continue
            rep = ts(r.reported_at)
            for a in self.run_window(r):
                if system_of(a.resource_id) == "account_service":
                    if a.event_type != "DELETE_RECORD" or ts(a.event_time) > rep + ACCOUNT_AFTER:
                        continue
                acts[a.resource_id] = a
                cands[a.resource_id].add(r.case_id)
        by_case = {r.case_id: r for r in reqs}
        for rid, cs in list(cands.items()):
            # A content link settles ownership: to one of the candidates' subjects, or to someone
            # else entirely, in which case no candidate may take the resource.
            owners = {uid for uid in self.links if rid in self.links[uid]}
            direct = {c for c in cs if subj[c] in owners}
            if direct:
                cands[rid] = direct
                continue
            if owners:
                del cands[rid]
                continue
            # Otherwise keep candidates whose own evidence files observed this resource.
            seen_in = {ob.file_id for ob in self.obs_by_rid.get(rid, [])}
            scoped = {c for c in cs if files[c] & seen_in}
            if scoped:
                cands[rid] = scoped
        # Claims as a tie-breaker for account deletes: the run's result mirrors the reported status.
        for rid, cs in cands.items():
            a = acts[rid]
            if len(cs) > 1 and system_of(rid) == "account_service":
                match = {c for c in cs if CLAIM_MATCH.get(by_case[c].reported_status) == a.reported_result}
                if match:
                    cands[rid] = match
        # Elimination: one resource of a system per request; repeat until stable.
        assigned: dict[str, str] = {}
        taken: set[tuple[str, str]] = set()
        changed = True
        while changed:
            changed = False
            for rid in sorted(cands):
                if rid in assigned:
                    continue
                sysid = system_of(rid)
                live = {c for c in cands[rid] if (c, sysid) not in taken}
                if len(live) == 1:
                    c = next(iter(live))
                    assigned[rid] = c
                    taken.add((c, sysid))
                    changed = True
        # Remaining ties: pair resources and requests in time order (deterministic).
        for rid in sorted(set(cands) - set(assigned), key=lambda r: (acts[r].event_time, r)):
            sysid = system_of(rid)
            live = sorted(c for c in cands[rid] if (c, sysid) not in taken)
            if live:
                assigned[rid] = live[0]
                taken.add((live[0], sysid))
                self.run_notes[rid] = f"tie between {len(live)} requests"
        self.run_owner = assigned
        self.run_acts = acts

    def run_resources(self, case_id: str) -> list[str]:
        return sorted(r for r, c in self.run_owner.items() if c == case_id)
