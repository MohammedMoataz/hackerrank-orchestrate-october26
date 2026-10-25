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
from typing import Callable, NamedTuple

from .identity import IdentityIndex
from .loader import Dataset
from .model import Activity, Observation, Request, system_of

RUN_BEFORE = timedelta(hours=1.6)       # the run starts with the account, about an hour before the report
RUN_AFTER = timedelta(hours=2.6)        # failed treatments and checks follow up to about two hours after
ACCOUNT_AFTER = timedelta(hours=0.4)
CATALOG_RE = re.compile(r"(?:linked|confirmed) (\S+) \(([^)]+)\) (?:to|belongs only to) (\S+) and (user_\d+)")
CLAIM_MATCH = {"COMPLETE": "SUCCESS", "PARTIALLY_COMPLETE": "PARTIAL", "NOT_STARTED": "FAILED"}

# Matching costs for (record, request) pairs; lower is a better fit. The order of magnitude encodes
# precedence: a content link outweighs everything, then claim consistency, then shared evidence,
# and the timing distance only breaks what is left.
COST_CONTENT_LINK = -100.0
COST_OWN_EVIDENCE = -10.0
COST_CLAIM_MATCH = -20.0
COST_CLAIM_MISMATCH = 20.0
EXPECTED_ACCOUNT_OFFSET_H = -1.0


class Link(NamedTuple):
    time: str        # capture or event time of the source
    kind: str        # "content" | "catalog"
    source: str      # evidence file id or activity id


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class Linker:
    def __init__(self, ds: Dataset, idx: IdentityIndex, observations: list[Observation],
                 is_deletion: Callable[[Request], bool]):
        self.ds, self.idx = ds, idx
        self.is_deletion = is_deletion
        self.obs_by_rid: dict[str, list[Observation]] = defaultdict(list)
        self.links: dict[str, dict[str, list[Link]]] = defaultdict(lambda: defaultdict(list))   # user -> resource
        self.owners_of: dict[str, set[str]] = defaultdict(set)                                  # resource -> users
        for ob in observations:
            self.obs_by_rid[ob.resource_id].append(ob)
            for uid in {idx.owner(i) for i in ob.ids} - {None}:
                self._link(uid, ob.resource_id, Link(ob.captured_at, "content", ob.file_id))
        for a in ds.activities:
            if a.event_type == "LINK_RESOURCE_IDENTITY" and (m := CATALOG_RE.search(a.details)):
                rid, _ref, _email, uid = m.groups()
                self._link(uid, rid, Link(a.event_time, "catalog", a.activity_id))
        self.run_owner: dict[str, str] = {}          # resource -> case_id, from joint run attribution
        self.run_acts: dict[tuple[str, str], Activity] = {}   # (resource, case_id) -> action
        self.run_notes: dict[str, str] = {}
        self._attribute_runs()

    def _link(self, uid: str, rid: str, link: Link) -> None:
        self.links[uid][rid].append(link)
        self.owners_of[rid].add(uid)

    # -- per-request views -------------------------------------------------------------------
    def linked(self, uid: str, audit_at: str) -> dict[str, list[Link]]:
        """Resources tied to the person by sources available at or before the cutoff."""
        return {rid: [l for l in ls if l.time <= audit_at] for rid, ls in self.links.get(uid, {}).items()
                if any(l.time <= audit_at for l in ls)}

    def evidence_files(self, uid: str, audit_at: str) -> set[str]:
        return {l.source for ls in self.linked(uid, audit_at).values() for l in ls if l.kind == "content"}

    def run_window(self, req: Request) -> list[Activity]:
        rep = ts(req.reported_at)
        return [a for a in self.ds.activities
                if a.source_system == "deletion_worker" and rep - RUN_BEFORE <= ts(a.event_time) <= rep + RUN_AFTER]

    def run_resources(self, case_id: str) -> list[str]:
        return sorted(r for r, c in self.run_owner.items() if c == case_id)

    # -- joint attribution of workflow-run activity -------------------------------------------
    def _attribute_runs(self) -> None:
        reqs = self.ds.all_requests
        by_case = {r.case_id: r for r in reqs}
        subj = {r.case_id: self.idx.subject(r.email) for r in reqs}
        files = {r.case_id: self.evidence_files(subj[r.case_id], r.audit_at) if subj[r.case_id] else set()
                 for r in reqs}
        cands = self._candidates(reqs, subj)
        pairs = []
        for rid, cs in cands.items():
            owners = self.owners_of.get(rid, set())
            if owners and not any(subj[c] in owners for c in cs):
                continue                      # the record demonstrably belongs to someone else
            for c in cs:
                if owners and subj[c] not in owners:
                    continue
                cost = self._cost(rid, by_case[c], bool(owners), bool(files[c] & self._files_observing(rid)))
                pairs.append((cost, self.run_acts[rid, c].event_time, rid, c, len(cs)))
        self._match(pairs)

    def _candidates(self, reqs: list[Request], subj: dict) -> dict[str, set[str]]:
        """Resource -> requests whose deletion-run window contains an action on it."""
        cands: dict[str, set[str]] = defaultdict(set)
        for r in reqs:
            if not subj[r.case_id] or not self.is_deletion(r):
                continue
            rep = ts(r.reported_at)
            for a in self.run_window(r):
                if system_of(a.resource_id) == "account_service":
                    if a.event_type != "DELETE_RECORD" or ts(a.event_time) > rep + ACCOUNT_AFTER:
                        continue
                self.run_acts[a.resource_id, r.case_id] = a
                cands[a.resource_id].add(r.case_id)
        return cands

    def _files_observing(self, rid: str) -> set[str]:
        return {ob.file_id for ob in self.obs_by_rid.get(rid, [])}

    def _cost(self, rid: str, req: Request, content_link: bool, own_evidence: bool) -> float:
        a = self.run_acts[rid, req.case_id]
        cost = (COST_CONTENT_LINK if content_link else 0.0) + (COST_OWN_EVIDENCE if own_evidence else 0.0)
        if system_of(rid) == "account_service":
            # The run's result mirrors the request's reported status (a claim, used only to pair
            # records with requests), and the account goes first, about an hour before the report.
            claim = CLAIM_MATCH.get(req.reported_status) == a.reported_result
            cost += COST_CLAIM_MATCH if claim else COST_CLAIM_MISMATCH
            dt = (ts(a.event_time) - ts(req.reported_at)).total_seconds() / 3600
            cost += abs(dt - EXPECTED_ACCOUNT_OFFSET_H)
        return cost

    def _match(self, pairs: list[tuple]) -> None:
        """Greedy lowest-cost matching: each record to one request, one record per system per request."""
        taken: set[tuple[str, str]] = set()
        for cost, _, rid, c, n in sorted(pairs):
            sysid = system_of(rid)
            if rid in self.run_owner or (c, sysid) in taken:
                continue
            self.run_owner[rid] = c
            taken.add((c, sysid))
            if n > 1:
                self.run_notes[rid] = f"chosen among {n} requests (cost {cost:.1f})"
