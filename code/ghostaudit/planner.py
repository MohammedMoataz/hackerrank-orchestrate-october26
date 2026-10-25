"""Audit one request: gather its records, read their state at the cutoff, plan the steps."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import policy
from .identity import IdentityIndex
from .linker import Linker
from .model import ABSENT, OP_PHASE, OP_STATE, CaseResult, Request, Step, system_of
from .state import StateResolver

Classifier = Callable[[str], tuple[bool, str]]     # request text -> (authorises deletion, reason)
RETAINED_SYSTEMS = ("security_service", "legal_service")


@dataclass(frozen=True)
class Record:
    resource_id: str
    system_id: str
    state: str
    treatment: policy.Treatment
    evidence: str            # file id of the observation that established the state ("" if none)
    how: str                 # why the record belongs to the request


class Auditor:
    def __init__(self, idx: IdentityIndex, linker: Linker, states: StateResolver, classify: Classifier):
        self.idx, self.linker, self.states, self.classify = idx, linker, states, classify

    # -- gathering ---------------------------------------------------------------------------
    def _choose_account(self, linked: dict, run: set[str]) -> str | None:
        """The account this request's deletion run handled, else the one evidence ties to the person."""
        accounts_run = sorted(r for r in run if system_of(r) == "account_service")
        if accounts_run:
            return accounts_run[0]
        accounts_linked = [r for r in linked if system_of(r) == "account_service"]
        if accounts_linked:
            return max(sorted(accounts_linked), key=lambda r: max(l.time for l in linked[r]))
        return None

    def records(self, req: Request, uid: str) -> list[Record]:
        linked = self.linker.linked(uid, req.audit_at)
        run = set(self.linker.run_resources(req.case_id))
        how = lambda rid: "run" if rid in run else "evidence"
        out: list[Record] = []

        account = self._choose_account(linked, run)
        if account:
            ob = self.states.state_at(account, req.audit_at)
            t = policy.treatment("USER_PROFILE", "account_service")
            state = policy.normalise_state(ob.state, t) if ob else ABSENT
            out.append(Record(account, "account_service", state, t, ob.file_id if ob else "", how(account)))

        # Retained records (security audit, legal hold) may be identified from evidence captured after
        # the cutoff: that only tells us which record exists. Their state still comes from evidence at
        # or before the cutoff, and nothing captured later is ever cited.
        retained = {r for r in self.linker.links.get(uid, {}) if system_of(r) in RETAINED_SYSTEMS}
        others = {r for r in (set(linked) | run) if system_of(r) != "account_service"} | retained
        for rid in sorted(others):
            ob = self.states.state_at(rid, req.audit_at)
            if ob is None:
                later = self.states.any_observation(rid) if rid in retained else None
                if later:
                    t = policy.treatment(later.category, later.system_id)
                    if t is not None:
                        out.append(Record(rid, later.system_id, "PRESENT", t, "", "retained, identified later"))
                continue
            t = policy.treatment(ob.category, ob.system_id)
            if t is not None:
                out.append(Record(rid, ob.system_id, policy.normalise_state(ob.state, t), t, ob.file_id, how(rid)))
        return out

    # -- planning ----------------------------------------------------------------------------
    @staticmethod
    def _plan_incomplete(recs: list[Record], violations: list[Record]) -> list[Step]:
        """Findings and remediation for each violation, then checks for every remediated record,
        the account, and the records policy requires to keep."""
        steps = []
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
        return steps

    def _plan_complete(self, req: Request, recs: list[Record]) -> list[Step]:
        """Evidence-cited checks proving each record's compliant state at the cutoff."""
        steps = []
        for r in recs:
            if not r.evidence and r.system_id != "account_service":
                continue          # a COMPLETE verification must cite evidence from before the cutoff
            ev = r.evidence or self.states.absence_evidence(req.audit_at, [x.evidence for x in recs])
            steps.append(Step("VERIFICATION", r.system_id, r.resource_id, r.treatment.verification,
                              OP_STATE[r.treatment.verification], ev))
        return steps

    def audit(self, req: Request) -> CaseResult:
        ok, why = self.classify(req.request_text)
        if not ok:
            return CaseResult(req.case_id, "NOT_APPLICABLE", [], [why])
        uid = self.idx.subject(req.email)
        if uid is None:
            return CaseResult(req.case_id, "INCOMPLETE", [], ["request email matches no known identity"])
        recs = self.records(req, uid)
        violations = [r for r in recs if policy.violates(r.state, r.treatment)]
        if violations:
            status, steps = "INCOMPLETE", self._plan_incomplete(recs, violations)
        else:
            status, steps = "COMPLETE", self._plan_complete(req, recs)
            if not steps:
                # Finding nothing is not proof that the data is gone: without a single cited check the
                # deletion cannot be confirmed, so it stays open.
                status = "INCOMPLETE"
        unique = {(s.operation, s.system_id, s.resource_id): s for s in steps}
        ordered = sorted(unique.values(), key=Step.sort_key)
        if any(OP_PHASE[s.operation] != s.phase for s in ordered):
            raise ValueError(f"{req.case_id}: step phase does not match its operation")
        notes = [f"subject {uid}", why] + [
            f"{r.resource_id}: {r.state} via {r.how} ({r.evidence or 'no file'})"
            + (f"; {self.linker.run_notes[r.resource_id]}" if r.resource_id in self.linker.run_notes else "")
            for r in recs]
        return CaseResult(req.case_id, status, ordered, notes)


def to_json_steps(steps: list[Step]) -> list[dict]:
    return [{"step_no": i, "phase": s.phase, "system_id": s.system_id, "resource_id": s.resource_id,
             "operation": s.operation, "state": s.state, "evidence_id": s.evidence_id}
            for i, s in enumerate(steps, 1)]
