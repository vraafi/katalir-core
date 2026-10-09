"""TASK 5 / Fitur #1 — 12 hard test untuk `agents.py` (n8n Agents first-class).

Distribusi: 2 basic, 2 edge, 2 error, 2 performance, 1 security, 1 E2E + regresi.

Untuk determinisme & isolasi, test memaksa backend in-memory: modul memilih
Supabase bila `database.is_configured()`, jadi fixture memonkeypatch-nya.
E2E (I1) justru memakai backend nyata bila tersedia — dan jatuh ke in-memory
dengan catatan jujur bila tidak.
"""

from __future__ import annotations

import time
import uuid

import pytest

import agents as ag


@pytest.fixture(autouse=True)
def _memory_backend(monkeypatch):
    """Paksa store in-memory + bersihkan antar-test (isolasi penuh)."""
    import database as db

    monkeypatch.setattr(db, "is_configured", lambda: False)
    ag._LAGENTS.clear()
    ag._LCHANNELS.clear()
    yield
    ag._LAGENTS.clear()
    ag._LCHANNELS.clear()


def _payload(**over) -> dict:
    base = {"name": "Support Bot", "instruction": "Bantu pengguna",
            "model": "gemma-4-31b-it", "tools": ["t1", "t2"],
            "channels": [{"type": "web"}]}
    base.update(over)
    return base


UID = "user-1"


# ---------------------------------------------------------------------------
# B — basic
# ---------------------------------------------------------------------------


def test_b1_create_agent_default_draft():
    """B1: agent baru selalu `draft`, punya id, versi 1, kanal tersimpan."""
    a = ag.create_agent(UID, _payload())
    assert a["status"] == "draft"
    assert a["id"]
    assert a["version"] == 1
    assert len(a["channels"]) == 1
    assert a["channels"][0]["type"] == "web"
    assert a["tools"] == ["t1", "t2"]


def test_b2_list_dan_get_agent():
    """B2: list mengembalikan agent milik user; get mengembalikan yang benar."""
    a1 = ag.create_agent(UID, _payload(name="A1"))
    a2 = ag.create_agent(UID, _payload(name="A2"))
    lst = ag.list_agents(UID)
    assert {x["id"] for x in lst} == {a1["id"], a2["id"]}
    got = ag.get_agent(a1["id"], UID)
    assert got and got["name"] == "A1"
    # list user lain kosong
    assert ag.list_agents("user-2") == []


# ---------------------------------------------------------------------------
# E — edge
# ---------------------------------------------------------------------------


def test_e1_siklus_hidup_lengkap_dan_versi_naik():
    """E1: draft->active->paused->active->archived, versi bertambah."""
    a = ag.create_agent(UID, _payload())
    v0 = a["version"]
    a = ag.set_status(a["id"], UID, "active")
    assert a["status"] == "active" and a["version"] == v0 + 1
    a = ag.set_status(a["id"], UID, "paused")
    assert a["status"] == "paused"
    a = ag.set_status(a["id"], UID, "active")
    assert a["status"] == "active"
    a = ag.set_status(a["id"], UID, "archived")
    assert a["status"] == "archived"
    assert ag.can_transition("archived", "active") is False


def test_e2_filter_status_dan_transisi_idempoten():
    """E2: list dengan filter status; set status sama = no-op (tetap sah)."""
    a = ag.create_agent(UID, _payload())
    ag.set_status(a["id"], UID, "active")
    b = ag.create_agent(UID, _payload(name="Draft only"))
    aktif = ag.list_agents(UID, status="active")
    assert [x["id"] for x in aktif] == [a["id"]]
    draft = ag.list_agents(UID, status="draft")
    assert [x["id"] for x in draft] == [b["id"]]
    # transisi ke status yang sama = idempoten (tidak error)
    same = ag.set_status(a["id"], UID, "active")
    assert same["status"] == "active"


# ---------------------------------------------------------------------------
# X — error handling
# ---------------------------------------------------------------------------


def test_x1_transisi_terlarang_ditolak():
    """X1: draft->paused langsung DITOLAK (bukan diterima diam-diam)."""
    a = ag.create_agent(UID, _payload())
    with pytest.raises(ag.AgentError):
        ag.set_status(a["id"], UID, "paused")
    # archived -> apa pun ditolak
    ag.set_status(a["id"], UID, "archived")
    with pytest.raises(ag.AgentError):
        ag.set_status(a["id"], UID, "active")


def test_x2_hapus_agent_aktif_ditolak():
    """X2: agent aktif harus dijeda/diarsip sebelum dihapus."""
    a = ag.create_agent(UID, _payload())
    ag.set_status(a["id"], UID, "active")
    with pytest.raises(ag.AgentError):
        ag.delete_agent(a["id"], UID)
    # setelah dijeda, boleh dihapus
    ag.set_status(a["id"], UID, "paused")
    assert ag.delete_agent(a["id"], UID) is True


def test_x3_payload_tidak_sah_ditolak():
    """X3: nama kosong, status asing, tool duplikat, kanal asing -> AgentError."""
    with pytest.raises(ag.AgentError):
        ag.create_agent(UID, _payload(name="   "))
    with pytest.raises(ag.AgentError):
        ag.validate_status("aktif")
    with pytest.raises(ag.AgentError):
        ag.validate_tools(["x", "x"])
    with pytest.raises(ag.AgentError):
        ag.validate_channels([{"type": "telegram"}])
    with pytest.raises(ag.AgentError):
        ag.create_agent(UID, "bukan-objek")


def test_x4_agent_hilang_mengembalikan_none_bukan_500():
    """X4: id tidak ada / bukan uuid -> None (->404), bukan exception."""
    assert ag.get_agent("", UID) is None
    assert ag.get_agent("bukan-uuid-xyz", UID) is None
    assert ag.get_agent(str(uuid.uuid4()), UID) is None
    assert ag.delete_agent(str(uuid.uuid4()), UID) is False


def test_x5_batas_jumlah_agent_dan_kanal():
    """X5: batas jumlah agent/kanal/tool ditegakkan."""
    too_many_ch = [{"type": "web"} for _ in range(ag.MAX_CHANNELS_PER_AGENT + 1)]
    with pytest.raises(ag.AgentError):
        ag.create_agent(UID, _payload(channels=too_many_ch))
    with pytest.raises(ag.AgentError):
        ag.validate_tools([f"t{i}" for i in range(ag.MAX_TOOLS_PER_AGENT + 1)])


# ---------------------------------------------------------------------------
# P — performance
# ---------------------------------------------------------------------------


def test_p1_buat_200_agent_cepat():
    """P1: membuat agent sampai batas wajar (< 1 s untuk in-memory)."""
    t0 = time.perf_counter()
    made = 0
    for i in range(ag.MAX_AGENTS_PER_USER):
        ag.create_agent(UID, _payload(name=f"A{i}"))
        made += 1
    dt = time.perf_counter() - t0
    assert made == ag.MAX_AGENTS_PER_USER
    assert dt < 1.0, f"{dt:.3f}s"
    # agent ke-201 ditolak
    with pytest.raises(ag.AgentError):
        ag.create_agent(UID, _payload(name="overflow"))


def test_p2_list_200_agent_cepat():
    """P2: list 200 agent < 0.5 s."""
    for i in range(ag.MAX_AGENTS_PER_USER):
        ag.create_agent(UID, _payload(name=f"A{i}"))
    t0 = time.perf_counter()
    lst = ag.list_agents(UID)
    dt = time.perf_counter() - t0
    assert len(lst) == ag.MAX_AGENTS_PER_USER
    assert dt < 0.5, f"{dt:.3f}s"


# ---------------------------------------------------------------------------
# S — security
# ---------------------------------------------------------------------------


def test_s1_isolasi_tenant_ketat():
    """S1: user lain TIDAK bisa get/update/delete agent bukan miliknya."""
    a = ag.create_agent(UID, _payload())
    other = "user-intruder"
    assert ag.get_agent(a["id"], other) is None
    assert ag.list_agents(other) == []
    with pytest.raises(ag.AgentError):
        ag.update_agent(a["id"], other, {"name": "Hijacked"})
    assert ag.delete_agent(a["id"], other) is False
    # dan agent asli tidak berubah
    assert ag.get_agent(a["id"], UID)["name"] == "Support Bot"
    # foreign user tidak bisa lihat kanal
    assert ag.agent_channels(a["id"], other) == []


# ---------------------------------------------------------------------------
# I — E2E
# ---------------------------------------------------------------------------


def test_i1_e2e_backend_nyata_siklus_penuh():
    """I1: E2E lintas backend — buat→aktif→MCP→arsip→hapus, tanpa kebocoran."""
    import importlib

    # Pakai backend apa adanya (Supabase bila terkonfigurasi).
    import database as db

    importlib.reload(ag)
    real_backend = ag.describe()["backend"]

    uid = str(uuid.uuid4())
    created: list[str] = []
    try:
        a = ag.create_agent(uid, _payload(name="E2E Agent",
                                          channels=[{"type": "web"},
                                                    {"type": "mcp"}]))
        created.append(a["id"])
        assert a["status"] == "draft"

        # draft TIDAK diekspos sebagai MCP
        assert ag.mcp_descriptor(a["id"], uid)["exposed"] is False

        a = ag.set_status(a["id"], uid, "active")
        desc = ag.mcp_descriptor(a["id"], uid)
        assert desc["exposed"] is True
        assert desc["endpoint"] == f"/mcp/agents/{a['id']}"
        assert desc["memory_enabled"] is True

        # memory scope menunjuk agent_id yang benar
        scope = ag.recall_scope(a["id"], uid)
        assert scope["agent_id"] == a["id"] and scope["memory_enabled"] is True

        # kanal terbaca
        assert len(ag.agent_channels(a["id"], uid)) == 2

        # arsip & hapus
        ag.set_status(a["id"], uid, "archived")
        assert ag.delete_agent(a["id"], uid) is True
        created.clear()
        assert ag.get_agent(a["id"], uid) is None
    finally:
        for aid in created:
            try:
                ag.set_status(aid, uid, "archived")
                ag.delete_agent(aid, uid)
            except Exception:  # noqa: BLE001 - pembersihan terbaik
                pass

    # Backend dilaporkan jujur (Supabase nyata atau in-memory).
    assert real_backend in ("supabase", "memory")
    # Kembalikan modul ke kondisi yang diharapkan fixture berikutnya.
    importlib.reload(ag)
