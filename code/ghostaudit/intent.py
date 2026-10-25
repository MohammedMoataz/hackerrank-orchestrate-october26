"""Decide whether a request text authorises deletion.

Rules, not a model: the request texts come in six languages, and the non-deletion requests say so
explicitly ("not asking for deletion", "do not close the account", "marketing lists only").
An explicit non-deletion signal wins over deletion words that appear in a negated or limited sense.
"""
from __future__ import annotations

import re

DELETION = [
    r"\bdelet", r"\beras", r"\bremove (?:my|the) (?:account|profile)", r"\bclose (?:my|this|the) account",
    r"\bclose the account completely", r"account-deletion", r"\bpermanent(?:ly)? (?:account )?delet",
    r"suppression", r"supprim", r"exclus[aã]o", r"elimina", r"borra", r"削除", r"삭제", r"\bwipe\b",
    r"\bno longer need this account", r"\bdeleting my account",
]
NON_DELETION = [
    r"not (?:a request|asking) (?:to erase|for deletion)", r"\bdon'?t (?:delete|close)", r"\bdo not (?:delete|close)",
    r"without removing", r"leave (?:the|my) (?:account|profile)", r"keep the account", r"marketing lists only",
    r"stop the promotional", r"\bcopy of\b", r"download my account information", r"portable format",
    r"\bcorrect it\b", r"misspelled", r"reset(?:ting)? the login", r"change the email address",
    r"replace it with the new one", r"what personal information you hold", r"continue using the service",
    r"\bstill use it\b", r"\bstill need the account\b",
]
_DEL = [re.compile(p, re.I) for p in DELETION]
_NON = [re.compile(p, re.I) for p in NON_DELETION]


def classify(text: str) -> tuple[bool, str]:
    """(authorises_deletion, reason)."""
    non = [p.pattern for p in _NON if p.search(text)]
    if non:
        return False, "non-deletion signal: " + non[0]
    dels = [p.pattern for p in _DEL if p.search(text)]
    if dels:
        return True, "deletion signal: " + dels[0]
    return False, "no deletion signal"
