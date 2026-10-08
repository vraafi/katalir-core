"""Verifikasi endpoint build/deploy (/health build + /version).

Tujuan: membuktikan commit yang berjalan DI PRODUCTION bisa diverifikasi dari
luar tanpa Railway API token, dan bahwa SEMUA modul fitur terdaftar ada di
image (16 per 8 Okt 2026: 11 lama + 5 penutup gap n8n).

Skenario (6):
  1. GET /health menyertakan blok `build` (tanpa secret)
  2. GET /version melaporkan semua modul fitur terdaftar
  3. /version tidak membocorkan secret apa pun
  4. `commit` mengikuti env RAILWAY_GIT_COMMIT_SHA
  5. fallback "unknown"/"local" saat env tidak ada
  6. /version & /health tidak butuh auth (dipakai monitoring)
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import api_server


@pytest.fixture
def klien():
    return TestClient(api_server.app)


def test_01_health_punya_build(klien):
    r = klien.get("/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert "build" in body, "blok build hilang"
    for k in ("commit", "branch", "service", "environment", "python"):
        assert k in body["build"], f"build.{k} hilang"
    print(f"[1] /health build = {body['build']}")


def test_02_version_melaporkan_semua_fitur(klien):
    """Semua modul terdaftar dilaporkan ADA (jumlah diturunkan dari sumber).

    Sebelumnya tes ini mengunci angka 11; angka itu usang setelah 5 fitur
    penutup gap n8n ditambahkan (guardrails/vector_store/hitl/evaluation/
    insights). Menurunkan harapan dari `_FEATURE_MODULES` membuat kontrak ini
    tetap bermakna tanpa perlu diedit setiap kali fitur bertambah.
    """
    r = klien.get("/version")
    assert r.status_code == 200, r.text
    body = r.json()
    expected = len(api_server._FEATURE_MODULES)
    assert body["features_total"] == expected, body
    assert body["features_present"] == expected, f"fitur hilang: {body['features']}"
    # Fitur penutup gap n8n (8 Okt 2026) WAJIB ada.
    for key in ("12_guardrails", "13_vector_store", "14_hitl",
                "15_evaluation", "16_insights"):
        assert body["features"].get(key) is True, f"{key} tidak ada: {body['features']}"
    print(f"[2] /version features_present={body['features_present']}/"
          f"{body['features_total']}")


def test_03_tidak_membocorkan_secret(klien):
    import os
    blob = json.dumps(klien.get("/version").json())
    bocor = [k for k in ("SUPABASE_DB_PASSWORD", "SUPABASE_SECRET_KEY",
                         "GEMINI_API_KEY", "RAILWAY_API_TOKEN", "DODO_API_KEY")
             if (os.getenv(k) or "") and os.getenv(k) in blob]
    assert not bocor, f"SECRET BOCOR di /version: {bocor}"
    print(f"[3] tidak ada secret bocor (dicek {len(blob)} byte)")


def test_04_commit_mengikuti_env(monkeypatch, klien):
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "deadbeef" * 5)
    monkeypatch.setenv("RAILWAY_GIT_BRANCH", "main")
    r = klien.get("/version")
    assert r.json()["build"]["commit"] == ("deadbeef" * 5)[:40]
    assert r.json()["build"]["branch"] == "main"
    print(f"[4] commit mengikuti env: {r.json()['build']['commit'][:12]}…")


def test_05_fallback_tanpa_env(monkeypatch, klien):
    for k in ("RAILWAY_GIT_COMMIT_SHA", "GIT_COMMIT_SHA", "RAILWAY_SERVICE_NAME",
              "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_DEPLOYMENT_ID"):
        monkeypatch.delenv(k, raising=False)
    b = klien.get("/version").json()["build"]
    assert b["commit"] == "unknown" and b["service"] == "local", b
    print(f"[5] fallback: commit={b['commit']} service={b['service']}")


def test_06_tanpa_auth(klien):
    assert klien.get("/health").status_code == 200
    assert klien.get("/version").status_code == 200
    print("[6] /health & /version dapat diakses tanpa auth (monitoring)")
