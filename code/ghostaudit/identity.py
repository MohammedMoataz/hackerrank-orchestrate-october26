"""Resolve a request email to a person and list every identifier that person has used.

Matching is exact after normalisation (lower-cased emails, digits-only phones). Look-alike
addresses such as `g.silva76.jr@gmail.com` versus `g.silva76@gmail.com` never match, and names
are not used because different people share them.
"""
from __future__ import annotations

from collections import defaultdict

from .loader import Dataset, norm_email, norm_phone


class IdentityIndex:
    def __init__(self, ds: Dataset):
        self.users = {u["user_id"]: u for u in ds.identities}
        self.alias_owner: dict[str, str] = {}
        self.aliases: dict[str, set[str]] = defaultdict(set)
        self.history = defaultdict(list)
        for u in ds.identities:
            uid = u["user_id"]
            self._add(uid, uid)
            self._add(uid, norm_email(u["email"]))
            self._add(uid, u["email_hash"].lower())
            if norm_phone(u["phone"]):
                self._add(uid, "tel:" + norm_phone(u["phone"]))
        for a in ds.audit_log:
            uid = a["user_id"]
            self.history[uid].append(a)
            for value in (a["old_value"], a["new_value"]):
                if a["field_name"] == "email":
                    self._add(uid, norm_email(value))
                elif a["field_name"] == "email_hash":
                    self._add(uid, value.lower())
                elif a["field_name"] == "phone" and norm_phone(value):
                    self._add(uid, "tel:" + norm_phone(value))

    def _add(self, uid: str, alias: str) -> None:
        if not alias:
            return
        self.alias_owner.setdefault(alias, uid)
        self.aliases[uid].add(alias)

    def subject(self, email: str) -> str | None:
        """The user a request email belongs to, via a current or historical address."""
        return self.alias_owner.get(norm_email(email))

    def owner(self, alias: str) -> str | None:
        return self.alias_owner.get(alias)

    def historical_only(self, uid: str) -> set[str]:
        """Identifiers the person used before but no longer has."""
        u = self.users[uid]
        current = {uid, norm_email(u["email"]), u["email_hash"].lower(), "tel:" + norm_phone(u["phone"])}
        return self.aliases[uid] - current
