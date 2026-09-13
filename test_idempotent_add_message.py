# -*- coding: utf-8 -*-
"""Unit test idempoten add_message (openclaw #69266).

Bukti: bila client_request_id sudah tercatat untuk role=user -> add_message
return False dan TIDAK insert dua kali. Bila fresh -> insert (row berisi
client_request_id) dan return True. Semua via mock write client — tanpa DB.
"""
import sys
import importlib

import database as db


class FakeR:
    def __init__(self, data):
        self.data = data


class Builder:
    def __init__(self, client, table):
        self._client = client
        self._table = table
        self._filters = []
        self._op = "select"

    def select(self, *a):
        self._op = "select"
        return self

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def limit(self, n):
        return self

    def order(self, *a):
        return self

    def insert(self, rows):
        self._op = "insert"
        self._rows = rows
        return self

    def execute(self):
        if self._op == "insert":
            self._client.rows.append(self._rows)
            return FakeR([])
        cols = [c for c, _ in self._filters]
        filt = dict(self._filters)
        if "client_request_id" in cols:          # idempotency check
            return FakeR([{"id": "old"}] if filt["client_request_id"] in self._client.known else [])
        if "id" in cols and "user_id" in cols:   # ownership check
            return FakeR([{"id": "sid"}])
        if self._table == "users":
            return FakeR([{"id": "uid-test", "email": "x@y.z"}])
        return FakeR([])


class FakeClient:
    def __init__(self):
        self.known = set()
        self.rows = []

    def table(self, name):
        return Builder(self, name)


def _install(fake, known=None):
    db._req_key = {"checked": True, "enabled": True}
    db.is_configured = lambda: True
    db._get_write_client = lambda: fake
    db._resolve_user_id = lambda owner, auth_id=None: "uid-test"
    db._request_key_enabled = lambda: True
    if known is not None:
        fake.known = set(known)


def test_duplicate_request_is_skipped():
    fake = FakeClient()
    _install(fake, known=["req-A"])
    # Ownership check + idem check: req-A sudah ada -> JANGAN insert, return False.
    got = db.add_message(
        "owner@x.y", "sid", "user", "halo",
        auth_id="uid-test", client_request_id="req-A",
    )
    assert got is False, f"expected False, got {got}"
    # Tidak ada insert duplikat untuk req-A.
    inserted = [r for r in fake.rows if r.get("client_request_id") == "req-A"]
    assert inserted == [], f"expected no insert for req-A, got {inserted}"
    print("test_duplicate_request_is_skipped OK")


def test_fresh_request_inserts_with_key():
    fake = FakeClient()
    _install(fake, known=[])
    got = db.add_message(
        "owner@x.y", "sid", "user", "halo",
        auth_id="uid-test", client_request_id="req-B",
    )
    assert got is True, f"expected True, got {got}"
    row = fake.rows[-1]
    assert row["role"] == "user"
    assert row["client_request_id"] == "req-B"
    print("test_fresh_request_inserts_with_key OK")


def test_assistant_not_idempotency_gated():
    fake = FakeClient()
    _install(fake, known=["req-A"])
    # role assistant dengan client_request_id sama -> JANGAN blocked (insert).
    got = db.add_message(
        "owner@x.y", "sid", "assistant", "reply",
        auth_id="uid-test", client_request_id="req-A",
    )
    assert got is True, f"expected True (assistant bypass guard), got {got}"
    assert fake.rows[-1]["role"] == "assistant"
    print("test_assistant_not_idempotency_gated OK")


if __name__ == "__main__":
    test_duplicate_request_is_skipped()
    test_fresh_request_inserts_with_key()
    test_assistant_not_idempotency_gated()
    print("ALL_PASS")