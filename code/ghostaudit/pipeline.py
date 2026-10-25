"""Composition root: build the audit components once and wire their dependencies."""
from __future__ import annotations

import time
from pathlib import Path
from typing import NamedTuple

from . import evidence, intent, loader, policy
from .identity import IdentityIndex
from .linker import Linker
from .loader import Dataset
from .planner import Auditor
from .state import StateResolver


class Pipeline(NamedTuple):
    ds: Dataset
    auditor: Auditor
    stats: dict


def build(use_ocr: bool = True, root: Path | None = None) -> Pipeline:
    t0 = time.time()
    ds = loader.load(root) if root else loader.load()
    idx = IdentityIndex(ds)
    observations, stats = evidence.parse_all(ds, use_ocr=use_ocr)
    linker = Linker(ds, idx, observations, is_deletion=lambda r: intent.classify(r.request_text)[0])
    account_files = {o.file_id for o in observations if o.system_id == "account_service"}
    states = StateResolver(linker.obs_by_rid, ds.evidence_files, account_files)
    auditor = Auditor(idx, linker, states, policy.Policy(ds.rules), classify=intent.classify)
    stats.update(observations=len(observations), build_seconds=round(time.time() - t0, 2))
    return Pipeline(ds, auditor, stats)
