"""Build the whole audit context once and run it over a list of requests."""
from __future__ import annotations

import time

from . import evidence, loader
from .identity import IdentityIndex
from .linker import Linker
from .planner import Auditor


def build(use_ocr: bool = True):
    t0 = time.time()
    ds = loader.load()
    idx = IdentityIndex(ds)
    observations, stats = evidence.parse_all(ds, use_ocr=use_ocr)
    linker = Linker(ds, idx, observations)
    files_by_time = sorted((f["captured_at"], f["file_id"]) for f in ds.evidence_files)
    account_ids = {o.file_id for o in observations if o.system_id == "account_service"}
    account_files = [(t, f) for t, f in files_by_time if f in account_ids]
    auditor = Auditor(idx, linker, files_by_time, account_files)
    stats.update(observations=len(observations), build_seconds=round(time.time() - t0, 2))
    return ds, auditor, stats
