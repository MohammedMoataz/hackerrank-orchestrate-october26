"""The state of a record at an audit cutoff, established only from evidence captured by then."""
from __future__ import annotations

from .model import Observation

# When one file shows a record twice (a primary and a replica table, say), the worse state wins:
# a profile gone from the primary but still on a replica is still present.
SEVERITY = {"IDENTIFIABLE": 3, "PRESENT": 3, "ACTIVE": 3, "REDACTED": 1, "ANONYMIZED": 1, "DISABLED": 1,
            "BLOCKED": 1, "ABSENT": 0}


class StateResolver:
    def __init__(self, obs_by_rid: dict[str, list[Observation]], evidence_files: list[dict],
                 account_file_ids: set[str]):
        self.obs_by_rid = obs_by_rid
        self.captured = {f["file_id"]: f["captured_at"] for f in evidence_files}
        self.account_files = sorted((self.captured[f], f) for f in account_file_ids if f in self.captured)

    def state_at(self, rid: str, cutoff: str) -> Observation | None:
        """Latest observation captured at or before the cutoff (inclusive)."""
        obs = [o for o in self.obs_by_rid.get(rid, []) if o.captured_at <= cutoff]
        if not obs:
            return None
        latest = max(o.captured_at for o in obs)
        return max((o for o in obs if o.captured_at == latest), key=lambda o: (SEVERITY.get(o.state, 0), o.file_id))

    def any_observation(self, rid: str) -> Observation | None:
        """Any observation, regardless of time: used only to identify a record, never for its state."""
        obs = self.obs_by_rid.get(rid)
        return obs[0] if obs else None

    def absence_evidence(self, cutoff: str, own_files: list[str]) -> str:
        """Evidence for an account that no file mentions any more: the request's own latest evidence
        file, else the latest capture of account records before the cutoff."""
        own = sorted((self.captured.get(f, ""), f) for f in own_files if f)
        if own:
            return own[-1][1]
        prior = [f for t, f in self.account_files if t <= cutoff]
        return prior[-1] if prior else ""
