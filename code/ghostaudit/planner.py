"""Audit one request: find its records, establish their state at the cutoff, plan the steps."""
from __future__ import annotations

from dataclasses import dataclass

from . import intent, policy
from .identity import IdentityIndex
from .linker import Linker
from .model import ABSENT, OP_PHASE, OP_STATE, CaseResult, Observation, Request, Step, system_of

SEVERITY = {"IDENTIFIABLE": 3, "PRESENT": 3, "ACTIVE": 3, "REDACTED": 1, "ANONYMIZED": 1, "DISABLED": 1,
            "BLOCKED": 1, "ABSENT": 0}


@dataclass
class Record:
    resource_id: str
    system_id: str
    state: str
    treatment: policy.Treatment
    evidence: str            # file id of the observation that established the state ("" if none)
    how: str                 # why the record belongs to the request


class Auditor:
    def __init__(self, idx: IdentityIndex, linker: Linker, files_by_time: list[tuple[str, str]],
                 account_files: list[tuple[str, str]]):
        self.idx, self.linker = idx, linker
        self.files_by_time = files_by_time          # [(captured_at, file_id)] sorted
        self.account_files = account_files          # files that hold account records, sorted

    def state_at(self, rid: str, cutoff: str) -> Observation | None:
        """Latest observation captured at or before the cutoff; within one file the worst state wins."""
        obs = [o for o in self.linker.obs_by_rid.get(rid, []) if o.captured_at <= cutoff]
        if not obs:
            return None
        latest = max(o.captured_at for o in obs)
        same = [o for o in obs if o.captured_at == latest]
        return max(same, key=lambda o: (SEVERITY.get(o.state, 0), o.file_id))

    def records(self, req: Request, uid: str) -> list[Record]:
        linked = self.linker.linked(uid, req.audit_at)
        run = set(self.linker.run_resources(req.case_id))
        accounts_run = sorted(r for r in run if system_of(r) == "account_service")
        accounts_linked = sorted(r for r in linked if system_of(r) == "account_service")
        if accounts_run:
            account = accounts_run[0]
        elif accounts_linked:
            account = max(accounts_linked, key=lambda r: max(l[0] for l in linked[r]))
        else:
            account = None
        rids = {r for r in (set(linked) | run) if system_of(r) != "account_service"}
        # Retained records (security audit, legal hold) are identified even from evidence captured
        # after the cutoff: that only tells us which record exists. Their state still comes from
        # evidence at or before the cutoff, and nothing captured later is ever cited.
        retained = {r for r in self.linker.links.get(uid, {}) if system_of(r) in ("security_service", "legal_service")}
        rids |= retained
        out = []
        if account:
            ob = self.state_at(account, req.audit_at)
            t = policy.treatment("USER_PROFILE", "account_service")
            state = policy.normalise_state(ob.state, t) if ob else ABSENT
            out.append(Record(account, "account_service", state, t, ob.file_id if ob else "",
                              "run" if account in run else "evidence"))
        for rid in sorted(rids):
            ob = self.state_at(rid, req.audit_at)
            if ob is None and rid in retained:
                later = self.linker.obs_by_rid.get(rid, [])
                if later:
                    t = policy.treatment(later[0].category, later[0].system_id)
                    out.append(Record(rid, later[0].system_id, "PRESENT", t, "", "retained, identified later"))
                continue
            if ob is None:
                continue
            t = policy.treatment(ob.category, ob.system_id)
            if t is None:
                continue
            out.append(Record(rid, ob.system_id, policy.normalise_state(ob.state, t), t, ob.file_id,
                              "run" if rid in run else "evidence"))
        return out

    def absence_evidence(self, req: Request, records: list[Record]) -> str:
        """Evidence for an account no file mentions: the request's own latest evidence file, else
        the latest earlier capture of account records."""
        own = sorted((self._captured(r.evidence), r.evidence) for r in records if r.evidence)
        if own:
            return own[-1][1]
        prior = [f for t, f in self.account_files if t <= req.audit_at]
        return prior[-1] if prior else ""

    def _captured(self, file_id: str) -> str:
        for t, f in self.files_by_time:
            if f == file_id:
                return t
        return ""

    def audit(self, req: Request) -> CaseResult:
        ok, why = intent.classify(req.request_text)
        if not ok:
            return CaseResult(req.case_id, "NOT_APPLICABLE", [], [why])
        uid = self.idx.subject(req.email)
        if uid is None:
            return CaseResult(req.case_id, "INCOMPLETE", [], ["request email matches no known identity"])
        recs = self.records(req, uid)
        violations = [r for r in recs if policy.violates(r.state, r.treatment)]
        steps: list[Step] = []
        notes = [f"subject {uid}", why] + [f"{r.resource_id}: {r.state} via {r.how} ({r.evidence or 'no file'})" for r in recs]
        if violations:
            status = "INCOMPLETE"
            for r in violations:
                if r.treatment.finding:
                    steps.append(Step("FINDING", r.system_id, r.resource_id, r.treatment.finding,
                                      OP_STATE[r.treatment.finding], r.evidence))
                    steps.append(Step("REMEDIATION", r.system_id, r.resource_id, r.treatment.remediation,
                                      OP_STATE[r.treatment.remediation]))
            for r in recs:
                if r in violations or r.system_id == "account_service" or r.treatment.retain:
                    steps.append(Step("VERIFICATION", r.system_id, r.resource_id, r.treatment.verification,
                                      OP_STATE[r.treatment.verification]))
        else:
            status = "COMPLETE"
            for r in recs:
                if not r.evidence and r.system_id != "account_service":
                    continue          # a COMPLETE verification must cite evidence from before the cutoff
                ev = r.evidence or self.absence_evidence(req, recs)
                steps.append(Step("VERIFICATION", r.system_id, r.resource_id, r.treatment.verification,
                                  OP_STATE[r.treatment.verification], ev))
        unique = {(s.operation, s.system_id, s.resource_id): s for s in steps}
        ordered = sorted(unique.values(), key=Step.sort_key)
        assert all(OP_PHASE[s.operation] == s.phase for s in ordered)
        return CaseResult(req.case_id, status, ordered, notes)


def to_json_steps(steps: list[Step]) -> list[dict]:
    return [{"step_no": i, "phase": s.phase, "system_id": s.system_id, "resource_id": s.resource_id,
             "operation": s.operation, "state": s.state, "evidence_id": s.evidence_id}
            for i, s in enumerate(steps, 1)]
