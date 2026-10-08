"""Fitur #10 — Workflow Templates: hard test.

Dua lapis:
  * **Unit** (mode memori, `db.is_configured()=False`) — logika template,
    validasi, isolasi user, instantiate. Deterministik, tanpa jaringan.
  * **Endpoint** (FastAPI TestClient + auth di-patch) — kontrak HTTP.

Skenario (15):
   1. template bawaan tersedia & bentuknya sah
   2. filter kategori
   3. pencarian kata kunci (nama/deskripsi/tag)
   4. detail satu template + id tak dikenal -> None
   5. instantiate membuat workflow NYATA dengan flow_data identik
   6. CRUD template kustom
   7. isolasi antar user (template kustom A tak terlihat B)
   8. validasi flow_data rusak ditolak
   9. template bawaan tidak bisa dihapus
  10. kategori tak dikenal ditolak saat membuat kustom
  11. endpoint GET /templates + /templates/info
  12. endpoint POST /templates/{id}/use
  13. endpoint POST /templates dari workflow_id
  14. endpoint 404 untuk template tak dikenal
  15. endpoint DELETE template bawaan -> 400
"""
from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

import api_server
import database as db
import workflow_templates as wt


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def memori(monkeypatch):
    """Paksa DB ke mode memori supaya tes tidak menyentuh produksi."""
    monkeypatch.setattr(db, "is_configured", lambda: False)
    db._LWORKFLOW.clear()
    db._L_EXEC.clear()
    wt._LTEMPLATES.clear()
    yield
    db._LWORKFLOW.clear()
    db._L_EXEC.clear()
    wt._LTEMPLATES.clear()


@pytest.fixture
def klien(monkeypatch, memori):
    """TestClient + auth di-patch (JWT Supabase tidak bisa dibuat di tes)."""
    monkeypatch.setattr(api_server.security, "get_current_user",
                        lambda authorization=None: {"id": "user-A", "email": "a@t.dev"})
    return TestClient(api_server.app)


# ---------------------------------------------------------------------------
# 1. template bawaan
# ---------------------------------------------------------------------------
def test_01_builtin_tersedia_dan_sah(memori):
    items = wt.list_templates()
    assert len(items) >= 10, f"harus ada >=10 template bawaan, dapat {len(items)}"
    for t in items:
        assert t["source"] == "builtin"
        assert t["id"].startswith(wt.BUILTIN_PREFIX)
        assert t["name"] and t["description"]
        assert t["category"] in wt.CATEGORIES, t["category"]
        assert t["node_count"] >= 1, f"{t['id']} tanpa node"
        # setiap flow harus lolos validasi (tidak ada edge ke node hantu)
        wt.validate_flow_data(t["flow_data"])
    ids = [t["id"] for t in items]
    assert len(ids) == len(set(ids)), "id template duplikat"
    print(f"[1] {len(items)} template bawaan sah; contoh={ids[:3]}")


# ---------------------------------------------------------------------------
# 2. filter kategori
# ---------------------------------------------------------------------------
def test_02_filter_kategori(memori):
    semua = wt.list_templates()
    for cat in ("notification", "data", "ops"):
        subset = wt.list_templates(category=cat)
        assert subset, f"kategori {cat} kosong"
        assert all(t["category"] == cat for t in subset)
        print(f"[2] kategori {cat:14s} -> {len(subset)} template")
    assert len(wt.list_templates(category="tidak-ada")) == 0


# ---------------------------------------------------------------------------
# 3. pencarian
# ---------------------------------------------------------------------------
def test_03_pencarian_query(memori):
    assert wt.list_templates(query="telegram"), "cari 'telegram' harus ketemu"
    assert wt.list_templates(query="SHEETS"), "cari harus case-insensitive"
    assert all("telegram" in (t["name"] + t["description"] + " ".join(t["tags"])).lower()
               for t in wt.list_templates(query="telegram"))
    assert wt.list_templates(query="zzz-tidak-ada-zzz") == []
    print("[3] pencarian nama/deskripsi/tag OK (case-insensitive)")


# ---------------------------------------------------------------------------
# 4. detail
# ---------------------------------------------------------------------------
def test_04_detail_dan_unknown(memori):
    t0 = wt.list_templates()[0]
    got = wt.get_template(t0["id"])
    assert got and got["id"] == t0["id"] and got["flow_data"]
    assert wt.get_template("tpl-tidak-ada") is None
    assert wt.get_template("") is None
    print(f"[4] get_template({t0['id']}) OK; id tak dikenal -> None")


# ---------------------------------------------------------------------------
# 5. instantiate
# ---------------------------------------------------------------------------
def test_05_instantiate_membuat_workflow(memori):
    t0 = wt.list_templates()[0]
    hasil = wt.instantiate(t0["id"], "user-A")
    wf = hasil["workflow"]
    assert wf["id"] and wf["user_id"] == "user-A"
    assert wf["flow_data"] == t0["flow_data"], "flow_data harus identik"
    assert db.count_nodes(wf["flow_data"]) == t0["node_count"]
    daftar = db.list_workflows("user-A")
    assert any(w["id"] == wf["id"] for w in daftar), "workflow baru tidak muncul di list"
    print(f"[5] instantiate -> workflow {wf['id']} ({t0['node_count']} node), muncul di list")

    # Nama/deskripsi bisa dioverride.
    h2 = wt.instantiate(t0["id"], "user-A", name="Nama Kustom", description="D")
    assert h2["workflow"]["name"] == "Nama Kustom"
    assert h2["workflow"]["description"] == "D"

    with pytest.raises(wt.TemplateError):
        wt.instantiate("tpl-tidak-ada", "user-A")
    print("[5] override nama + template tak dikenal -> TemplateError")


# ---------------------------------------------------------------------------
# 6. CRUD kustom
# ---------------------------------------------------------------------------
def test_06_custom_crud(memori):
    flow = {"nodes": [{"id": "t1", "type": "trigger",
                       "data": {"kind": "trigger", "config": {}}}],
            "edges": []}
    row = wt.create_custom_template("user-A", "Templat Saya", "desk",
                                    "ops", flow, tags=["x"])
    assert row["source"] == "custom" and row["node_count"] == 1
    items = wt.list_templates(user_id="user-A")
    assert any(t["id"] == row["id"] for t in items), "template kustom tak muncul"
    print(f"[6] create -> {row['id']}; list berisi {len(items)} item")

    assert wt.delete_custom_template(row["id"], "user-A") is True
    assert wt.get_template(row["id"], "user-A") is None
    assert wt.delete_custom_template(row["id"], "user-A") is False
    print("[6] delete -> hilang; delete ulang -> False")


# ---------------------------------------------------------------------------
# 7. isolasi user
# ---------------------------------------------------------------------------
def test_07_isolasi_user(memori):
    flow = {"nodes": [{"id": "t1", "data": {"kind": "trigger", "config": {}}}],
            "edges": []}
    row = wt.create_custom_template("user-A", "Rahasia A", "", "ops", flow)
    assert wt.get_template(row["id"], "user-B") is None, "B bisa lihat template A"
    ids_b = [t["id"] for t in wt.list_templates(user_id="user-B")]
    assert row["id"] not in ids_b
    assert wt.delete_custom_template(row["id"], "user-B") is False
    assert wt.get_template(row["id"], "user-A") is not None, "template A hilang"
    print("[7] isolasi: B tidak melihat/menghapus template A")


# ---------------------------------------------------------------------------
# 8. validasi
# ---------------------------------------------------------------------------
def test_08_validasi_flow(memori):
    kasus = [
        ("nodes bukan list", {"nodes": "x"}),
        ("edge tanpa target", {"nodes": [{"id": "n1"}], "edges": [{"source": "n1"}]}),
        ("edge ke node hantu", {"nodes": [{"id": "n1"}],
                                "edges": [{"source": "n1", "target": "ghost"}]}),
        ("node tanpa id", {"nodes": [{"type": "agent"}]}),
        ("id duplikat", {"nodes": [{"id": "n1"}, {"id": "n1"}]}),
        ("self-loop", {"nodes": [{"id": "n1"}],
                       "edges": [{"source": "n1", "target": "n1"}]}),
    ]
    for label, flow in kasus:
        with pytest.raises(wt.TemplateError):
            wt.validate_flow_data(flow)
        print(f"[8] ditolak: {label}")
    sah = {"nodes": [{"id": "a"}, {"id": "b"}],
           "edges": [{"source": "a", "target": "b"}]}
    assert wt.validate_flow_data(copy.deepcopy(sah)) == sah


# ---------------------------------------------------------------------------
# 9. bawaan tidak bisa dihapus
# ---------------------------------------------------------------------------
def test_09_bawaan_tidak_bisa_dihapus(memori):
    t0 = wt.list_templates()[0]
    assert wt.delete_custom_template(t0["id"], "user-A") is False
    print("[9] delete template bawaan -> False")


# ---------------------------------------------------------------------------
# 10. kategori invalid
# ---------------------------------------------------------------------------
def test_10_kategori_invalid(memori):
    flow = {"nodes": [{"id": "t1", "data": {"kind": "trigger", "config": {}}}],
            "edges": []}
    with pytest.raises(wt.TemplateError):
        wt.create_custom_template("user-A", "X", "", "kategori-ngawur", flow)
    with pytest.raises(wt.TemplateError):
        wt.create_custom_template("user-A", "   ", "", "ops", flow)
    print("[10] kategori invalid + nama kosong -> TemplateError")


# ---------------------------------------------------------------------------
# 11. endpoint list + info
# ---------------------------------------------------------------------------
def test_11_endpoint_list_dan_info(klien):
    r = klien.get("/templates")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] >= 10 and len(body["templates"]) == body["count"]
    print(f"[11] GET /templates -> {body['count']} template")

    r2 = klien.get("/templates", params={"category": "data"})
    assert r2.status_code == 200
    assert all(t["category"] == "data" for t in r2.json()["templates"])

    r3 = klien.get("/templates/info")
    assert r3.status_code == 200 and r3.json()["builtin_count"] >= 10
    print(f"[11] /templates?category=data -> {r2.json()['count']}; "
          f"/templates/info builtin={r3.json()['builtin_count']}")


# ---------------------------------------------------------------------------
# 12. endpoint use
# ---------------------------------------------------------------------------
def test_12_endpoint_use(klien):
    t0 = klien.get("/templates").json()["templates"][0]
    r = klien.post(f"/templates/{t0['id']}/use", json={"name": "Dari Template"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["workflow"]["name"] == "Dari Template"
    assert body["workflow"]["flow_data"] == t0["flow_data"]
    print(f"[12] POST /templates/{t0['id']}/use -> workflow {body['workflow']['id']}")

    r2 = klien.post("/templates/tpl-tidak-ada/use", json={})
    assert r2.status_code == 404, r2.text
    print("[12] template tak dikenal -> 404")


# ---------------------------------------------------------------------------
# 13. endpoint create dari workflow_id
# ---------------------------------------------------------------------------
def test_13_endpoint_create_dari_workflow(klien):
    t0 = klien.get("/templates").json()["templates"][0]
    wf = klien.post(f"/templates/{t0['id']}/use", json={}).json()["workflow"]
    r = klien.post("/templates", json={"name": "Salinan", "workflow_id": wf["id"],
                                       "category": "ops"})
    assert r.status_code == 201, r.text
    row = r.json()["template"]
    assert row["source"] == "custom" and row["node_count"] == t0["node_count"]
    print(f"[13] POST /templates dari workflow_id -> {row['id']} "
          f"({row['node_count']} node)")

    # workflow_id tak dikenal -> 404
    r2 = klien.post("/templates", json={"name": "X",
                                        "workflow_id": "00000000-0000-4000-8000-0000000000ff"})
    assert r2.status_code == 404, r2.text

    # flow_data rusak -> 400
    r3 = klien.post("/templates", json={"name": "Rusak", "flow_data": {"nodes": "x"}})
    assert r3.status_code == 400, r3.text
    print("[13] workflow tak dikenal -> 404; flow rusak -> 400")


# ---------------------------------------------------------------------------
# 14. endpoint 404
# ---------------------------------------------------------------------------
def test_14_endpoint_404(klien):
    assert klien.get("/templates/tpl-nope").status_code == 404
    print("[14] GET /templates/tpl-nope -> 404")


# ---------------------------------------------------------------------------
# 15. endpoint delete bawaan
# ---------------------------------------------------------------------------
def test_15_endpoint_delete_bawaan(klien):
    t0 = klien.get("/templates").json()["templates"][0]
    r = klien.delete(f"/templates/{t0['id']}")
    assert r.status_code == 400, r.text
    print("[15] DELETE template bawaan -> 400")

    # kustom bisa dihapus
    flow = {"nodes": [{"id": "t1", "data": {"kind": "trigger", "config": {}}}], "edges": []}
    c = klien.post("/templates", json={"name": "Kustom", "flow_data": flow})
    cid = c.json()["template"]["id"]
    assert klien.delete(f"/templates/{cid}").status_code == 200
    assert klien.delete(f"/templates/{cid}").status_code == 404
    print("[15] DELETE kustom -> 200 lalu 404")
