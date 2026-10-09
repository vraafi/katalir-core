"""FASE 5 — federation discovery (connector_federation).

Tes memakai data palsu; tidak memanggil registry nyata kecuali ditandai.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import connector_federation as cf  # noqa: E402


def _item(name, url, ver="1.0.0", status="active"):
    return {"server": {"name": name, "description": f"desc {name}",
                       "title": name, "version": ver,
                       "remotes": [{"type": "streamable-http", "url": url}]},
            "_meta": {"io.modelcontextprotocol.registry/official":
                      {"status": status, "publishedAt": "2026-01-01T00:00:00Z"}}}


# --------------------------------------------------------------------------
# B — BASIC
# --------------------------------------------------------------------------

def test_b1_entry_from_official_shape():
    e = cf._entry_from_official(_item("ac.snag/snag", "https://mcp.snag.ac/mcp"))
    assert e["slug"] == "ac.snag/snag"
    assert e["endpoint_url"] == "https://mcp.snag.ac/mcp"
    assert e["transport"] == "streamable_http"
    assert e["status"] == "active"


def test_b2_normalize_consistent():
    assert cf._norm("ac.snag/snag") == cf._norm("ac.snag/snag")


# --------------------------------------------------------------------------
# E — EDGE
# --------------------------------------------------------------------------

def test_e1_entry_without_name_is_none():
    assert cf._entry_from_official({"server": {"description": "x"}}) is None


def test_e2_entry_without_remotes_has_no_url():
    e = cf._entry_from_official({"server": {"name": "x/y", "title": "X"}})
    assert e is not None
    assert e["endpoint_url"] is None
    assert e["transport"] is None


def test_e3_duplicate_names_collapse_within_batch():
    items = [cf._entry_from_official(_item("a/b", "https://a/mcp")),
             cf._entry_from_official(_item("a/b", "https://a/mcp"))]
    res = cf.dedup_against_catalog(items, known=set())
    assert len(res["fresh"]) == 1
    assert len(res["duplicates"]) == 1


# --------------------------------------------------------------------------
# X — ERROR
# --------------------------------------------------------------------------

def test_x1_dedup_against_known():
    items = [cf._entry_from_official(_item("a/b", "https://a/mcp")),
             cf._entry_from_official(_item("c/d", "https://c/mcp"))]
    known = {cf._norm("a/b")}
    res = cf.dedup_against_catalog(items, known=known)
    assert [e["slug"] for e in res["fresh"]] == ["c/d"]
    assert len(res["duplicates"]) == 1


def test_x2_http_error_returns_empty(monkeypatch):
    class Boom:
        def __init__(self, *a, **k):
            pass

        def get(self, *a, **k):
            return type("R", (), {"status_code": 500, "json": lambda s: {}})()
    got = cf.fetch_official(client=Boom())
    assert got == []


def test_x3_non_200_breaks_without_raising(monkeypatch):
    class R404:
        status_code = 404

        def json(self):
            return {}
    class C:
        def __init__(self, *a, **k):
            pass

        def get(self, *a, **k):
            return R404()
    assert cf.fetch_official(client=C()) == []


# --------------------------------------------------------------------------
# P — PERFORMANCE
# --------------------------------------------------------------------------

def test_p1_dedup_large_batch_fast():
    import time
    # Nama harus benar-benar berbeda setelah normalisasi: `mcp_dedup`
    # membuang kata noise ('api', 'server', 'mcp') DAN segmen setelah '/',
    # jadi "api0.io/x" akan runtuh ke kunci yang sama dengan "api1.io/y".
    items = [{"slug": f"vendor{i}.com/{i}", "name": f"Vendor{i}"}
             for i in range(3000)]
    t0 = time.time()
    res = cf.dedup_against_catalog(items, known=set())
    assert len(res["fresh"]) == 3000
    assert time.time() - t0 < 5.0


def test_p2_pagination_respects_pages(monkeypatch):
    calls = {"n": 0}

    class Page:
        status_code = 200

        def __init__(self, i):
            self.i = i

        def json(self):
            return {"servers": [_item(f"vendor{self.i}.com/svc", f"https://a{self.i}/mcp")],
                    "metadata": {"nextCursor": f"c{self.i}"}}

    class C:
        def __init__(self, *a, **k):
            pass

        def get(self, *a, **k):
            calls["n"] += 1
            return Page(calls["n"])
    got = cf.fetch_official(pages=3, client=C(), sleep=0)
    assert calls["n"] == 3
    assert len(got) == 3


# --------------------------------------------------------------------------
# S — SECURITY / HONESTY
# --------------------------------------------------------------------------

def test_s1_sources_report_real_status():
    """Sumber yang butuh kunci / 404 harus dilaporkan apa adanya."""
    s = cf.SOURCES
    assert s["glama"]["auth"] is True
    assert "401" in s["glama"]["status"]
    assert "404" in s["smithery"]["status"]
    assert s["official"]["auth"] is False


def test_s2_describe_records_missing_repo():
    d = cf.describe()
    assert "404" in d["missing_from_brief"]


# --------------------------------------------------------------------------
# I — INTEGRATION
# --------------------------------------------------------------------------

def test_i1_discover_shape(monkeypatch):
    monkeypatch.setattr(cf, "fetch_official",
                        lambda **k: [cf._entry_from_official(_item("z/z", "https://z/mcp"))])
    monkeypatch.setattr(cf, "existing_keys", lambda: set())
    res = cf.discover()
    assert res["fetched"] == 1
    assert res["fresh"] == 1
    assert res["with_endpoint"] == 1


def test_i2_discover_respects_existing(monkeypatch):
    monkeypatch.setattr(cf, "fetch_official",
                        lambda **k: [cf._entry_from_official(_item("z/z", "https://z/mcp"))])
    monkeypatch.setattr(cf, "existing_keys", lambda: {cf._norm("z/z")})
    res = cf.discover()
    assert res["fresh"] == 0
    assert res["duplicates"] == 1


def test_i3_persist_writes_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cf, "fetch_official",
                        lambda **k: [cf._entry_from_official(_item("q/q", "https://q/mcp"))])
    monkeypatch.setattr(cf, "existing_keys", lambda: set())
    res = cf.discover(persist=True)
    p = tmp_path / "federation_discovered.json"
    assert p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert len(data) == 1
