"""Turn every evidence file into Observations.

Files are routed by extension to a reader, then by the shape of their content inside that reader,
never by file name: `connector_configurations_20260812.json`, for example, is a general ledger.
Supporting a new format means adding one entry to the reader registry.
"""
from __future__ import annotations

import logging
import os
from functools import partial
from typing import Callable

from ..loader import Dataset
from ..model import Observation
from . import logs, ocr, records, sql, text

Reader = Callable[..., list[Observation]]    # (path, file_id, captured_at) -> observations
log = logging.getLogger(__name__)


def readers(use_ocr: bool, ocr_stats: dict) -> dict[str, Reader]:
    return {
        ".json": records.parse,
        ".sql": sql.parse,
        ".log": logs.parse,
        ".txt": text.parse_ledger_text,
        ".pdf": text.parse_pdf,
        ".png": partial(ocr.parse, enabled=use_ocr, stats=ocr_stats),
    }


def parse_all(ds: Dataset, use_ocr: bool = True) -> tuple[list[Observation], dict]:
    """Return (observations, stats). A file that cannot be read is reported, not fatal."""
    stats = {"files": 0, "by_format": {}, "errors": [],
             "ocr": {"images": 0, "seconds": 0.0, "available": None}}
    registry = readers(use_ocr, stats["ocr"])
    observations: list[Observation] = []
    for f in ds.evidence_files:
        ext = os.path.splitext(f["file_path"])[1].lower()
        reader = registry.get(ext)
        stats["files"] += 1
        stats["by_format"][ext] = stats["by_format"].get(ext, 0) + 1
        if reader is None:
            stats["errors"].append(f"{f['file_id']}: no reader for {ext}")
            continue
        try:
            observations.extend(reader(ds.root / f["file_path"], f["file_id"], f["captured_at"]))
        except Exception as exc:  # one malformed file must not stop the other 517 cases
            log.warning("could not read %s (%s): %s", f["file_id"], f["file_path"], exc)
            stats["errors"].append(f"{f['file_id']}: {type(exc).__name__}: {exc}")
    return observations, stats
