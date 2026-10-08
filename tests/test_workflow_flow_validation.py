"""Validasi graf pada jalur TULIS /workflows + id template yang rusak.

LATAR (temuan hard test PRODUKSI 8 Okt 2026):
  * `POST /workflows` menyimpan `flow_data` APA ADANYA. Terbukti di produksi:
    graf 5.000 node diterima (201), self-loop diterima, dan edge ke node
    "hantu" diterima. Padahal `workflow_templates.validate_flow_data` dan
    `mcp_server._validate_flow_data` sudah menegakkan aturan yang sama —
    jalur tulis utama justru yang paling longgar (permukaan DoS + data rusak).
  * `GET /templates/nonexistent-id-xyz` membalas **500** (PostgREST menolak
    sintaks uuid), padahal jawaban benar untuk "tidak ada" adalah 404.
    `DELETE` dengan id non-uuid punya cacat yang sama.

Skenario (12):
  1. graf sah -> 201
  2. 5.000 node (> MAX 500) -> 422
  3. tepat MAX node -> 201 (batas inklusif)
  4. MAX+1 node -> 422
  5. self-loop -> 422
  6. edge ke node hantu -> 422
  7. edge tanpa source/target -> 422
  8. node id duplikat -> 422
  9. node tanpa id -> 422
 10. flow_data bukan objek / nodes bukan list / edges bukan list -> 422
 11. validasi juga berlaku pada UPDATE (autosave kanvas)
 12. id template non-uuid -> 404 (GET) dan 404 (DELETE), bukan 500
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import api_server  # noqa: E402
import database as db  # noqa: E402
import rate_limit  # noqa: E402
import workflow_templates  # noqa: E402

USER_A = "11111111-1111-1111-1111-111111111111"


@pytest.fixture(autouse=True)
def memory_and_auth(monkeypatch):
    monkeypatch.setattr(db, "is_configured", lambda: False)
    monkeypatch.setattr(api_server.security, "get_current_user",
                        lambda authorization=None: {"id": USER_A, "email": "t@example.com"})
    # Limiter pembuatan workflow dimatikan: yang diuji validasi, bukan kuota.
    monkeypatch.setattr(rate_limit.workflow_build_limiter, "max_calls", 0)
    db._LWORKFLOW.clear()
    workflow_templates._LTEMPLATES.clear()
    yield
    db._LWORKFLOW.clear()
    workflow_templates._LTEMPLATES.clear()


@pytest.fixture
def client():
    return TestClient(api_server.app)


def _post(client, flow, name="V"):
    return client.post("/workflows", json={"name": name, "description": "", "flow_data": flow})


def _nodes(n, prefix="n"):
    return [{"id": f"{prefix}{i}"} for i in range(n)]


# --- 1 ---------------------------------------------------------------------
def test_1_graf_sah_diterima(client):
    r = _post(client, {"nodes": _nodes(3), "edges": [
        {"id": "e1", "source": "n0", "target": "n1"},
        {"id": "e2", "source": "n1", "target": "n2"}]})
    assert r.status_code == 201, r.text
    print(f"[1] graf sah -> 201 id={r.json()['workflow']['id']}")


# --- 2 ---------------------------------------------------------------------
def test_2_lima_ribu_node_ditolak(client):
    r = _post(client, {"nodes": _nodes(5000), "edges": []})
    assert r.status_code == 422, f"5.000 node diterima! HTTP {r.status_code} {r.text[:200]}"
    assert "Terlalu banyak node" in r.text, r.text[:200]
    print(f"[2] 5000 node -> 422 {r.json()['detail']}")


# --- 3 ---------------------------------------------------------------------
def test_3_tepat_batas_max_diterima(client):
    n = api_server.MAX_WORKFLOW_NODES
    r = _post(client, {"nodes": _nodes(n), "edges": []})
    assert r.status_code == 201, f"tepat {n} node seharusnya diterima: {r.status_code} {r.text[:150]}"
    print(f"[3] tepat {n} node -> 201 (batas inklusif)")


# --- 4 ---------------------------------------------------------------------
def test_4_max_plus_satu_ditolak(client):
    n = api_server.MAX_WORKFLOW_NODES + 1
    r = _post(client, {"nodes": _nodes(n), "edges": []})
    assert r.status_code == 422, f"{n} node seharusnya ditolak: {r.status_code}"
    print(f"[4] {n} node -> 422 {r.json()['detail']}")


# --- 5 ---------------------------------------------------------------------
def test_5_self_loop_ditolak(client):
    r = _post(client, {"nodes": [{"id": "a"}], "edges": [{"source": "a", "target": "a"}]})
    assert r.status_code == 422, f"self-loop diterima! HTTP {r.status_code} {r.text[:200]}"
    assert "self-loop" in r.text
    print(f"[5] self-loop -> 422 {r.json()['detail']}")


# --- 6 ---------------------------------------------------------------------
def test_6_edge_ke_node_hantu_ditolak(client):
    r = _post(client, {"nodes": [{"id": "a"}], "edges": [{"source": "a", "target": "hantu"}]})
    assert r.status_code == 422, f"edge hantu diterima! HTTP {r.status_code} {r.text[:200]}"
    assert "tidak ada di nodes" in r.text
    print(f"[6] edge ke node hantu -> 422 {r.json()['detail']}")


# --- 7 ---------------------------------------------------------------------
def test_7_edge_tanpa_source_target_ditolak(client):
    for bad in ({"source": "a"}, {"target": "a"}, {"source": 1, "target": "a"}, {}):
        r = _post(client, {"nodes": [{"id": "a"}], "edges": [bad]})
        assert r.status_code == 422, f"edge {bad} diterima! {r.status_code}"
    print("[7] edge tanpa source/target -> 422 (4 varian)")


# --- 8 ---------------------------------------------------------------------
def test_8_node_id_duplikat_ditolak(client):
    r = _post(client, {"nodes": [{"id": "a"}, {"id": "a"}], "edges": []})
    assert r.status_code == 422 and "duplikat" in r.text, r.text[:200]
    print(f"[8] node id duplikat -> 422 {r.json()['detail']}")


# --- 9 ---------------------------------------------------------------------
def test_9_node_tanpa_id_ditolak(client):
    for bad in ([{"type": "agent"}], [{"id": ""}], [{"id": 123}], ["bukan-objek"]):
        r = _post(client, {"nodes": bad, "edges": []})
        assert r.status_code == 422, f"nodes {bad} diterima! {r.status_code}"
    print("[9] node tanpa id / id non-string / bukan objek -> 422 (4 varian)")


# --- 10 --------------------------------------------------------------------
def test_10_bentuk_flow_salah_ditolak(client):
    kasus = [
        ("flow_data bukan objek", "bukan-objek"),
        ("nodes bukan list", {"nodes": "x"}),
        ("edges bukan list", {"nodes": [], "edges": "x"}),
    ]
    for label, flow in kasus:
        r = _post(client, flow)
        assert r.status_code == 422, f"{label} diterima! {r.status_code} {r.text[:150]}"
        print(f"[10] {label} -> 422")


# --- 11 --------------------------------------------------------------------
def test_11_validasi_juga_berlaku_saat_update(client):
    r = _post(client, {"nodes": [{"id": "a"}], "edges": []})
    assert r.status_code == 201
    wid = r.json()["workflow"]["id"]

    # Autosave kanvas = POST dengan `id` -> jalur UPDATE, tetap harus divalidasi.
    r2 = client.post("/workflows", json={
        "id": wid, "name": "V", "description": "",
        "flow_data": {"nodes": [{"id": "a"}], "edges": [{"source": "a", "target": "a"}]}})
    assert r2.status_code == 422, f"UPDATE lolos validasi! {r2.status_code} {r2.text[:200]}"
    print(f"[11] UPDATE dgn self-loop -> 422 {r2.json()['detail']}")

    # Update yang sah tetap 201 + updated=true.
    r3 = client.post("/workflows", json={
        "id": wid, "name": "V2", "description": "",
        "flow_data": {"nodes": [{"id": "a"}, {"id": "b"}],
                      "edges": [{"source": "a", "target": "b"}]}})
    assert r3.status_code == 201 and r3.json().get("updated") is True, r3.text[:200]
    print("[11] UPDATE sah -> 201 updated=True")


# --- 12 --------------------------------------------------------------------
def test_12_id_template_non_uuid_404_bukan_500(client):
    r = client.get("/templates/nonexistent-id-xyz")
    assert r.status_code == 404, f"GET id non-uuid -> {r.status_code} (harus 404) {r.text[:200]}"
    print(f"[12] GET /templates/nonexistent-id-xyz -> 404 {r.json()['detail']!r}")

    r2 = client.delete("/templates/nonexistent-id-xyz")
    assert r2.status_code == 404, f"DELETE id non-uuid -> {r2.status_code} (harus 404) {r2.text[:200]}"
    print(f"[12] DELETE /templates/nonexistent-id-xyz -> 404 {r2.json()['detail']!r}")

    # Id yang bukan uuid tapi mirip (mis. angka) juga harus 404, bukan 500.
    for tid in ("123", "not-a-uuid-but-long-enough", "tpl-", "abc-def"):
        rr = client.get(f"/templates/{tid}")
        assert rr.status_code == 404, f"GET /templates/{tid} -> {rr.status_code} {rr.text[:150]}"
    print("[12] 4 varian id rusak -> 404 (tanpa 500)")

    # Regresi: template BAWAAN tetap bisa diambil lewat endpoint yang sama.
    r3 = client.get("/templates/tpl-rss-ke-slack")
    assert r3.status_code == 200, r3.text[:200]
    print(f"[12] kontrol: /templates/tpl-rss-ke-slack -> 200 ({r3.json()['template']['name']})")
