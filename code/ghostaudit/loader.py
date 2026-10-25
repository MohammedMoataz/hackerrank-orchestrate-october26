"""Load the participant dataset and normalise identifiers."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from .model import Activity, Request

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "dataset"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
HASH_RE = re.compile(r"\b[0-9a-f]{64}\b")
USER_RE = re.compile(r"\buser_\d+\b")


def norm_email(value: str) -> str:
    return value.strip().strip('"').lower()


def norm_phone(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@dataclass
class Dataset:
    root: Path
    requests: list[Request]
    sample_requests: list[Request]
    identities: list[dict]
    audit_log: list[dict]
    activities: list[Activity]
    rules: list[dict]
    evidence_files: list[dict]

    @property
    def all_requests(self) -> list[Request]:
        """Every request in the world, labelled or not. Used only for joint account attribution."""
        return self.requests + self.sample_requests


def load(root: Path = DATASET_DIR) -> Dataset:
    def requests(name):
        return [Request(**{k: r[k] for k in Request.__dataclass_fields__}) for r in read_csv(root / name)]

    return Dataset(
        root=root,
        requests=requests("deletion_requests.csv"),
        sample_requests=requests("sample_deletion_requests.csv"),
        identities=read_csv(root / "user_identities.csv"),
        audit_log=read_csv(root / "user_audit_log.csv"),
        activities=[Activity(**r) for r in read_csv(root / "system_activity.csv")],
        rules=read_csv(root / "deletion_rules.csv"),
        evidence_files=read_csv(root / "evidence_files.csv"),
    )
