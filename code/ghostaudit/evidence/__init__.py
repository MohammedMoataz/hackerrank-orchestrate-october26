"""Turn every evidence file into Observations.

Files are routed by extension, then by the shape of their content, never by file name:
`connector_configurations_20260812.json`, for example, is a general ledger.
"""
from __future__ import annotations

import os

from ..loader import Dataset
from . import logs, records, sql, text, ocr


def parse_all(ds: Dataset, use_ocr: bool = True) -> tuple[list, dict]:
    """Return (observations, stats)."""
    observations, stats = [], {"files": 0, "by_format": {}, "ocr": {"images": 0, "seconds": 0.0, "available": None}}
    for f in ds.evidence_files:
        path = ds.root / f["file_path"]
        ext = os.path.splitext(f["file_path"])[1].lower()
        meta = (f["file_id"], f["captured_at"])
        if ext == ".json":
            obs = records.parse(path, *meta)
        elif ext == ".sql":
            obs = sql.parse(path, *meta)
        elif ext == ".log":
            obs = logs.parse(path, *meta)
        elif ext == ".txt":
            obs = text.parse_ledger_text(path, *meta)
        elif ext == ".pdf":
            obs = text.parse_pdf(path, *meta)
        elif ext == ".png":
            obs = ocr.parse(path, *meta, enabled=use_ocr, stats=stats["ocr"])
        else:
            obs = []
        stats["files"] += 1
        stats["by_format"][ext] = stats["by_format"].get(ext, 0) + 1
        observations.extend(obs)
    return observations, stats
