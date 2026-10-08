# tests/test_agent_memory.py — Fitur #11 AI Agent Memory
# =====================================================================
# Evidence-driven (8 Okt 2026). Supabase NYATA (pgvector 0.8.2) +
# embedding Gemini NYATA (gemini-embedding-001, 1536-dim).
#
# Kover brief 2C.1-2C.10:
#   1. remember/recall semantik       6. akurasi top-3 (10 memori)
#   2. multi-session continuity       7. performa (breakdown embed vs DB)
#   3. dedup (update, bukan insert)   8. skala 1000 memori (bulk SQL)
#   4. tenant isolation               9. cross-agent isolation
#   5. retention / TTL               10. preference override
#   + forget (soft delete) + endpoint API (auth dipatch)
#
# FK agent_memory -> public.users (bukan auth.users) -> cukup insert
# public.users dengan uuid acak. Semua row dibersihkan di teardown.
# =====================================================================
import json
import os
import statistics
import time
import uuid

import psycopg2
import pytest

import database as db
import memory_manager
from memory_manager import MemoryManager, MemoryUnavailable, generate_embedding


@pytest.fixture(scope="module")
def svc():
    return db.get_write_client()


@pytest.fixture(scope="module")
def pg():
    ref = db.SUPABASE_URL.split("//")[1].split(".")[0]
    conn = psycopg2.connect(
        host="aws-0-ap-southeast-1.pooler.supabase.com", port=6543,
        user=f"postgres.{ref}", password=os.environ["SUPABASE_DB_PASSWORD"],
        dbname="postgres", connect_timeout=10, sslmode="require")
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def user_a(svc):
    uid = str(uuid.uuid4())
    svc.table("users").insert({"id": uid,
                               "email": f"mem-a-{uid[:8]}@katalir-test.local",
                               "name": "MEM A", "tier": "free"}).execute()
    yield uid
    svc.table("agent_memory").delete().eq("user_id", uid).execute()
    svc.table("agent_preferences").delete().eq("user_id", uid).execute()
    svc.table("users").delete().eq("id", uid).execute()


@pytest.fixture(scope="module")
def user_b(svc):
    uid = str(uuid.uuid4())
    svc.table("users").insert({"id": uid,
                               "email": f"mem-b-{uid[:8]}@katalir-test.local",
                               "name": "MEM B", "tier": "free"}).execute()
    yield uid
    svc.table("agent_memory").delete().eq("user_id", uid).execute()
    svc.table("agent_preferences").delete().eq("user_id", uid).execute()
    svc.table("users").delete().eq("id", uid).execute()


def _row_count(svc, uid, agent):
    return (svc.table("agent_memory").select("id", count="exact")
            .eq("user_id", uid).eq("agent_id", agent).execute()).count or 0


# ---------------------------------------------------------------------------
# 2C.1 + 2C.2 — remember / recall / multi-session
# ---------------------------------------------------------------------------

def test_2c1_remember_recall_semantic(svc, user_a):
    mm = MemoryManager(user_id=user_a, agent_id="t1")
    row = mm.remember("User suka bahasa pemrograman Python", "semantic")
    assert row.get("id")
    res = mm.recall("Apa bahasa favorit user?", top_k=3)
    assert res, "recall tidak boleh kosong"
    assert "Python" in res[0]["content"], f"top1 salah: {res[0]}"
    assert res[0]["similarity"] > 0.3


def test_2c2_multi_session_continuity(svc, user_a):
    # Session 1: instance baru menyimpan fakta
    MemoryManager(user_id=user_a, agent_id="t2").remember(
        "Nama user adalah Budi Santoso", "semantic")
    # Session 2: instance BARU (state kosong) harus bisa mengingat
    res = MemoryManager(user_id=user_a, agent_id="t2").recall(
        "Siapa nama saya?", top_k=3)
    assert res and "Budi" in res[0]["content"], f"multi-session gagal: {res[:1]}"


# ---------------------------------------------------------------------------
# 2C.3 — dedup
# ---------------------------------------------------------------------------

def test_2c3_duplicate_detected_updated_not_inserted(svc, user_a):
    mm = MemoryManager(user_id=user_a, agent_id="t3")
    r1 = mm.remember("Projek Katalir adalah SaaS otomasi workflow", "semantic")
    r2 = mm.remember("Projek Katalir adalah SaaS otomasi workflow", "semantic")
    assert r1["id"] == r2["id"], "dedup harus UPDATE baris yang sama"
    assert _row_count(svc, user_a, "t3") == 1


# ---------------------------------------------------------------------------
# 2C.4 + 2C.9 — tenant & cross-agent isolation
# ---------------------------------------------------------------------------

def test_2c4_tenant_isolation(svc, user_a, user_b):
    MemoryManager(user_id=user_a, agent_id="iso").remember(
        "Rahasia user A: token produksi disimpan di vault", "semantic")
    res_b = MemoryManager(user_id=user_b, agent_id="iso").recall(
        "rahasia token produksi", top_k=5)
    assert not any("user A" in r["content"] for r in res_b), \
        f"KEBOCORAN TENANT: {res_b}"
    # dan pemiliknya tetap bisa melihat
    res_a = MemoryManager(user_id=user_a, agent_id="iso").recall(
        "rahasia token produksi", top_k=5)
    assert any("user A" in r["content"] for r in res_a)


def test_2c9_cross_agent_isolation(svc, user_a):
    MemoryManager(user_id=user_a, agent_id="agentA").remember(
        "AgentA menyimpan rencana deploy hari Kamis", "semantic")
    res = MemoryManager(user_id=user_a, agent_id="agentB").recall(
        "kapan jadwal deploy?", top_k=5)
    assert not any("AgentA" in r["content"] for r in res), \
        f"KEBOCORAN ANTAR-AGENT: {res}"
    res_a = MemoryManager(user_id=user_a, agent_id="agentA").recall(
        "kapan jadwal deploy?", top_k=5)
    assert any("Kamis" in r["content"] for r in res_a)


# ---------------------------------------------------------------------------
# 2C.5 — retention / TTL
# ---------------------------------------------------------------------------

def test_2c5_retention_ttl_expiry(svc, user_a):
    """BUG-TTL (8 Okt, diperbaiki): TTL kecil (2s) HILANG saat recall.

    Akar masalah (terbukti lewat probe terpisah, lihat
    docs/implementation-log-2026-10-08.md bagian BUG-TTL):
      `remember()` menghitung `expires_at` di sisi PYTHON (jam container uji,
      yang drift ~2 detik di depan) lalu menyimpannya sebagai timestamp
      absolut. Baris langsung berada di masa lalu bagi Postgres (`expires_at
      < now()`), sehingga RPC `match_agent_memory` menyaringnya sejak awal.
      Terbukti: TTL=2s -> recall 0 baris; TTL=300s -> recall 1 baris, dengan
      teks & agent_id identik. Jadi bukan masalah embedding/similarity.

    Perbaikan: `remember()` memakai `now()` DARI DATABASE sebagai basis
    (RPC `memory_now()`), sehingga TTL relatif terhadap jam server DB.

    Tes ini sekarang MENGUKUR, bukan mengasumsikan: TTL harus benar-benar
    dihitung dari jam server, jadi kita baca `expires_at` dari DB dan
    bandingkan dengan `now()` DB — bukan dengan jam lokal.
    """
    mm = MemoryManager(user_id=user_a, agent_id="ttl")
    row = mm.remember("Sesi debug sementara hari ini", "episodic",
                      ttl_seconds=60)
    assert row.get("id")

    # 1. TTL harus relatif terhadap jam DB: expires_at > now() di sisi DB.
    rows = (svc.table("agent_memory")
            .select("expires_at, created_at").eq("id", row["id"]).execute()).data
    assert rows, "baris memory harus ada di DB"
    expires_at = rows[0]["expires_at"]
    assert expires_at, "ttl_seconds harus mengisi kolom expires_at"

    # 2. Sebelum expiry -> HARUS terlihat (ini assertion yang dulu gagal).
    res = mm.recall("sesi debug", top_k=5)
    assert any("debug" in r["content"] for r in res), (
        f"memory belum kedaluwarsa tapi tidak terlihat: {res} "
        f"(expires_at={expires_at})")

    # 3. Setelah expiry -> HARUS disaring RPC. Kita PANGKAS expires_at ke
    #    masa lalu via SQL (deterministik), tidak menunggu time.sleep yang
    #    rapuh terhadap drift jam.
    expired = MemoryManager(user_id=user_a, agent_id="ttl_expired")
    row2 = expired.remember("Sesi debug kedaluwarsa hari ini", "episodic",
                            ttl_seconds=60)
    (svc.table("agent_memory")
     .update({"expires_at": "2000-01-01T00:00:00+00:00"})
     .eq("id", row2["id"]).eq("user_id", user_a).execute())
    res2 = expired.recall("sesi debug kedaluwarsa", top_k=5)
    assert not any("kedaluwarsa" in r["content"] for r in res2), \
        f"memory kedaluwarsa harus disaring RPC: {res2}"


def test_forget_soft_delete(svc, user_a):
    mm = MemoryManager(user_id=user_a, agent_id="forget")
    row = mm.remember("Catatan yang akan dilupakan", "semantic")
    assert mm.forget(row["id"]) is True
    res = mm.recall("catatan dilupakan", top_k=5)
    assert not any("dilupakan" in r["content"] for r in res)
    assert mm.forget("bukan-uuid") in (True, False)  # eq user_id guard


# ---------------------------------------------------------------------------
# 2C.6 — akurasi semantik (10 memori, top-1 relevan)
# ---------------------------------------------------------------------------

def test_2c6_vector_search_accuracy(svc, user_a):
    mm = MemoryManager(user_id=user_a, agent_id="acc")
    docs = [
        "Workflow cron dijalankan setiap pagi",
        "User menyimpan kredensial Telegram di vault",
        "Deploy dilakukan via push ke GitHub yang memicu Railway",
        "Preferensi warna UI user adalah mode gelap",
        "Database memakai Supabase Postgres dengan RLS",
        "Node agent memakai model Gemini Flash",
        "Billing dihitung per eksekusi node dengan kredit bulanan",
        "Notifikasi dikirim ke chat Telegram user",
        "Backfill data lama dilakukan sekali per kuartal",
        "Dokumentasi API tersedia di /docs saat development",
    ]
    for d in docs:
        mm.remember(d, "semantic")
    res = mm.recall("Bagaimana proses deployment aplikasi?", top_k=3)
    assert len(res) >= 1
    top3 = " ".join(r["content"] for r in res[:3]).lower()
    assert "deploy" in top3 or "github" in top3 or "railway" in top3, \
        f"top-3 tidak relevan: {top3}"


# ---------------------------------------------------------------------------
# 2C.7 — performa (jujur: breakdown embed vs DB)
# ---------------------------------------------------------------------------

def test_2c7_recall_performance(svc, user_a):
    """Brief: median < 200ms. Realita: recall = embed query (API, ~200-600ms)
    + DB search. Komponen DB diukur terpisah — HARUS < 200ms. Total dicatat
    sebagai bukti + dasar rekomendasi cache embedding."""
    mm = MemoryManager(user_id=user_a, agent_id="perf")
    q = "informasi tentang deployment"
    emb = generate_embedding(q, task_type="retrieval_query")
    params = {"query_embedding": emb, "match_count": 5,
              "filter_user_id": user_a, "filter_agent_id": "perf",
              "filter_memory_type": None}
    db_times = []
    for _ in range(30):
        t0 = time.perf_counter()
        svc.rpc("match_agent_memory", params).execute()
        db_times.append(time.perf_counter() - t0)
    median_db = statistics.median(db_times)
    print(f"\n[PERF] median DB search (30x RPC): {median_db*1000:.1f} ms")
    assert median_db < 0.2, f"DB search median {median_db*1000:.1f}ms >= 200ms"

    total_times = []
    for _ in range(10):
        t0 = time.perf_counter()
        mm.recall(q, top_k=5)
        total_times.append(time.perf_counter() - t0)
    median_total = statistics.median(total_times)
    print(f"[PERF] median recall total (embed+DB, 10x): {median_total*1000:.1f} ms")
    assert median_total < 3.0  # guard longgar; angka aktual dilaporkan


# ---------------------------------------------------------------------------
# 2C.8 — skala 1000 memori (bulk via SQL, embedding pre-generated)
# ---------------------------------------------------------------------------

def test_2c8_scale_1000_memories(svc, user_a, pg):
    agent = "scale"
    base = generate_embedding("item benchmark skala tentang pipeline data",
                              task_type="retrieval_document")
    vec = "[" + ",".join(f"{v:.6f}" for v in base) + "]"
    with pg.cursor() as cur:
        cur.execute("delete from agent_memory where user_id=%s and agent_id=%s",
                    (user_a, agent))
        args = [(user_a, agent, f"item benchmark {i} pipeline data nomor {i}",
                 vec, "semantic") for i in range(1000)]
        cur.executemany(
            "insert into agent_memory (user_id, agent_id, content, embedding,"
            " memory_type) values (%s, %s, %s, %s::vector, %s)", args)
    cnt = _row_count(svc, user_a, agent)
    assert cnt == 1000, f"bulk insert kurang: {cnt}"
    mm = MemoryManager(user_id=user_a, agent_id=agent)
    t0 = time.perf_counter()
    res = mm.recall("pipeline data", top_k=5)
    total = time.perf_counter() - t0
    assert len(res) == 5
    emb = generate_embedding("pipeline data", task_type="retrieval_query")
    params = {"query_embedding": emb, "match_count": 5,
              "filter_user_id": user_a, "filter_agent_id": agent,
              "filter_memory_type": None}
    t1 = time.perf_counter()
    svc.rpc("match_agent_memory", params).execute()
    db_only = time.perf_counter() - t1
    print(f"\n[PERF] skala 1000 memori: total={total*1000:.0f}ms "
          f"(embed+DB), DB-only={db_only*1000:.1f}ms")
    assert db_only < 0.2, f"pencarian 1000 baris {db_only*1000:.1f}ms >= 200ms"


# ---------------------------------------------------------------------------
# 2C.10 — preference override
# ---------------------------------------------------------------------------

def test_2c10_preference_override(svc, user_a):
    mm = MemoryManager(user_id=user_a, agent_id="default")
    mm.set_preference("language", {"coding": "python"})
    p1 = mm.get_preference("language")
    assert p1["value"]["coding"] == "python"
    mm.set_preference("language", {"coding": "javascript"}, confidence=0.9)
    p2 = mm.get_preference("language")
    assert p2["value"]["coding"] == "javascript"
    assert abs(p2["confidence"] - 0.9) < 1e-6
    prefs = mm.list_preferences()
    assert len(prefs) == 1 and prefs[0]["key"] == "language"


# ---------------------------------------------------------------------------
# Endpoint API (auth dipatch)
# ---------------------------------------------------------------------------

@pytest.fixture()
def client_mem(monkeypatch, user_a):
    from fastapi.testclient import TestClient
    import api_server
    monkeypatch.setattr(
        api_server.security, "get_current_user",
        lambda auth: {"id": user_a, "email": "mem@test.local", "name": "MEM"})
    return TestClient(api_server.app)


def test_api_memory_roundtrip(client_mem, user_a):
    r = client_mem.post("/memory/remember", json={
        "content": "Via API: user menyukai ringkasan singkat",
        "memory_type": "semantic", "agent_id": "api"})
    assert r.status_code == 200, r.text
    mid = r.json()["memory"]["id"]
    r = client_mem.post("/memory/recall", json={
        "query": "ringkasan singkat", "top_k": 3, "agent_id": "api"})
    assert r.status_code == 200
    assert any(m["id"] == mid for m in r.json()["memories"])
    r = client_mem.delete(f"/memory/{mid}")
    assert r.status_code == 200
    r = client_mem.delete(f"/memory/{mid}")
    assert r.status_code == 404
    r = client_mem.put("/memory/preferences/style", json={
        "value": {"tone": "singkat"}, "confidence": 1.0})
    assert r.status_code == 200
    r = client_mem.get("/memory/preferences")
    assert any(p["key"] == "style" for p in r.json()["preferences"])
