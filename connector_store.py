"""Persistensi ledger aktivasi & kesehatan connector ke Supabase.

Latar belakang
--------------
`mcp_registry.save_activation_ledger()` menulis ke `connector_activation.json`
yang **ada di `.gitignore:126`**. Akibatnya ledger tidak pernah ikut deploy dan
`coverage()['executable']` selalu reset ke 23 di setiap lingkungan baru.
(lihat `docs/audit/connector-connection-honest-audit.md` §5).

Modul ini memindahkan sumber kebenaran ledger ke Supabase (tabel
`connector_activation`), dengan berkas lokal hanya sebagai **cache/fallback**
saat DB tidak tersedia. Jadi:

    DB tersedia   -> DB adalah sumber kebenaran; berkas lokal disegarkan.
    DB tidak ada  -> jatuh ke berkas lokal (perilaku lama), log jelas.

Desain sengaja **tanpa dependensi baru** dan memakai `database.py` yang sudah
terpasang, supaya tidak ada jalur koneksi kedua yang perlu dirawat.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

TABLE_ACTIVATION = "connector_activation"
TABLE_HEALTH = "connector_health"

VERDICTS = ("ALIVE", "AUTH", "DEAD", "UNKNOWN")

_ON = ("1", "true", "True", "yes")
_OFF = ("0", "false", "False", "no")


def db_enabled() -> bool:
    """True bila DB boleh dipakai. Kill-switch untuk isolasi test.

    `mcp_registry._activated_ids()` memprioritaskan DB, sehingga menyetel
    `ACTIVATION_PATH` saja **tidak cukup** untuk mengisolasi satu test: id
    produksi tetap terbaca dan `added` selalu 0. Set
    `CONNECTOR_STORE_DISABLED=1` supaya jalur DB dimatikan dan berkas lokal
    menjadi sumber tunggal (dipakai fixture autouse di `tests/conftest.py`,
    sehingga tes tidak pernah menulis ke DB produksi).
    """
    return os.getenv("CONNECTOR_STORE_DISABLED", "").strip() not in _ON

_LOCAL_PATH = Path(__file__).with_name("connector_activation.json")


class ConnectorStoreError(RuntimeError):
    """Dilempar ketika operasi store gagal dan pemanggil perlu tahu."""


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _db():
    """Impor `database` secara malas supaya modul ini bisa diuji tanpa DB."""
    import database as db
    return db


def available() -> bool:
    """True bila Supabase terkonfigurasi (bukan berarti tabel sudah ada)."""
    if not db_enabled():
        return False
    try:
        return bool(_db().is_configured())
    except Exception:  # noqa: BLE001
        return False


def _write_client():
    """Client tulis (service role, bypass RLS). Raise bila belum di-set."""
    return _db().get_write_client()


def _read_client():
    return _db()._get_client()


# --------------------------------------------------------------------------
# connector_activation
# --------------------------------------------------------------------------

def load_activation_ids() -> set[str]:
    """Himpunan id yang aktif. DB lebih diutamakan; berkas = fallback."""
    if available():
        try:
            rows = _read_client().table(TABLE_ACTIVATION).select("connector_id").execute()
            ids = {str(r["connector_id"]) for r in (rows.data or [])}
            if ids:
                return ids
            # DB ada tapi masih kosong: mungkin migrasi belum dijalankan dari
            # berkas. Jangan menelan kegagalan — laporkan lewat log.
            print("[connector-store] tabel connector_activation kosong; cek migrasi.")
            return set()
        except Exception as exc:  # noqa: BLE001
            print(f"[connector-store] DB gagal dibaca ({type(exc).__name__}); "
                  f"fallback ke berkas lokal.")
    return _load_local_ids()


def _load_local_ids() -> set[str]:
    legacy = _legacy_path()
    if not legacy.exists():
        return set()
    try:
        data = json.loads(legacy.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    rows = data.get("activated") if isinstance(data, dict) else None
    if isinstance(rows, dict):
        return {str(k) for k in rows}
    if isinstance(rows, list):
        return {str(k) for k in rows}
    return set()


def _legacy_path() -> Path:
    """Berkas lokal. Selalu sama dengan yang dipakai `mcp_registry`."""
    return _LOCAL_PATH


def upsert_activation(records: Iterable[dict], *, batch: int = 200) -> dict:
    """Tulis/perbarui baris aktivasi ke DB. Idempoten (upsert by connector_id).

    `records` = iterable of dict dengan minimal `connector_id`.
    Mengembalikan {"written": n, "batches": n, "backend": "db"|"file"}.
    """
    rows = [dict(r) for r in records]
    for r in rows:
        r.setdefault("runtime_verified", True)
    if not rows:
        return {"written": 0, "batches": 0, "backend": "db" if available() else "file"}

    if not available():
        _write_local(rows)
        return {"written": len(rows), "batches": 0, "backend": "file"}

    client = _write_client()
    written = 0
    n = 0
    for i in range(0, len(rows), batch):
        chunk = rows[i:i + batch]
        res = client.table(TABLE_ACTIVATION).upsert(
            chunk, on_conflict="connector_id").execute()
        written += len(res.data or chunk)
        n += 1
    return {"written": written, "batches": n, "backend": "db"}


def _write_local(rows: list[dict]) -> None:
    """Tulis berkas lokal dalam format lama (dipakai sebagai cache)."""
    ids = sorted({str(r["connector_id"]) for r in rows})
    payload = {"version": 1, "count": len(ids), "activated": {i: True for i in ids}}
    tmp = _LOCAL_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_LOCAL_PATH)


def migrate_file_to_db(*, prune_file: bool = False) -> dict:
    """Pindahkan ledger berkas lama -> Supabase. Mengembalikan ringkasan.

    `prune_file=True` menghapus berkas lama setelah sukses (opt-in, supaya
    menghapus data tidak pernah terjadi tanpa diminta).
    """
    ids = _load_local_ids()
    if not ids:
        return {"migrated": 0, "reason": "berkas lokal kosong/tidak ada"}
    if not available():
        return {"migrated": 0, "reason": "Supabase tidak terkonfigurasi"}

    # Kumpulkan metadata dari katalog agar baris tidak kosong.
    meta: dict[str, dict] = {}
    try:
        import mcp_registry as mr
        cache = mr.load_cached()
        for cid in ids:
            entry = cache.get(cid)
            if not isinstance(entry, dict):
                continue
            ic = entry.get("install_config") or {}
            meta[cid] = {
                "connector_id": cid,
                "transport": ic.get("transport"),
                "endpoint_url": entry.get("endpoint_url") or ic.get("package"),
                "call_verified": bool(entry.get("runtime_verified")),
                "source": entry.get("source"),
            }
    except Exception as exc:  # noqa: BLE001
        print(f"[connector-store] katalog tidak terbaca saat migrasi: {exc}")

    rows = [meta.get(cid, {"connector_id": cid}) for cid in sorted(ids)]
    res = upsert_activation(rows)
    if prune_file and res["written"]:
        try:
            _legacy_path().unlink()
        except OSError as exc:
            print(f"[connector-store] gagal hapus berkas lama: {exc}")
    return {"migrated": res["written"], "total_ids": len(ids),
            "backend": res["backend"], "pruned": prune_file}


# --------------------------------------------------------------------------
# connector_health  (FASE 2)
# --------------------------------------------------------------------------

def record_health(records: Iterable[dict], *, batch: int = 200) -> dict:
    """Simpan hasil probe kesehatan. Idempoten per connector_id."""
    rows = [dict(r) for r in records]
    if not rows:
        return {"written": 0, "backend": "db" if available() else "file"}
    if not available():
        return {"written": 0, "backend": "file",
                "reason": "Supabase tidak terkonfigurasi"}
    client = _write_client()
    written = 0
    for i in range(0, len(rows), batch):
        chunk = rows[i:i + batch]
        res = client.table(TABLE_HEALTH).upsert(
            chunk, on_conflict="connector_id").execute()
        written += len(res.data or chunk)
    return {"written": written, "backend": "db"}


def health_summary() -> dict:
    """Ringkasan verdict: {ALIVE: n, AUTH: n, DEAD: n, UNKNOWN: n, total: n}."""
    out = {v: 0 for v in VERDICTS}
    out["total"] = 0
    if not available():
        return out
    try:
        rows = _read_client().table(TABLE_HEALTH).select("verdict").execute()
    except Exception as exc:  # noqa: BLE001
        print(f"[connector-store] health_summary gagal: {exc}")
        return out
    for r in (rows.data or []):
        v = r.get("verdict")
        if v in out:
            out[v] += 1
        out["total"] += 1
    return out


def classify(http_status: int | None, *, tools_count: int | None = None,
             error: str | None = None) -> str:
    """Terjemahkan sinyal mentah -> verdict. Satu tempat, satu aturan.

    Aturan (konsisten dengan audit jujur):
      * `tools_count` terbaca (bukan None) -> ALIVE. Ini satu-satunya bukti
        bahwa server benar-benar mengirim data.
      * 401/403, atau pesan auth     -> AUTH (server hidup, butuh kredensial)
      * 5xx / timeout / ProxyError   -> DEAD
      * 200 TAPI ada error RPC/parse -> UNKNOWN, **bukan** ALIVE. Kode HTTP
        200 hanya berarti transport hidup; tanpa `tools/list` yang valid kita
        tidak punya bukti data mengalir.
      * selain itu                   -> UNKNOWN

    Catatan: `tools_count` diperiksa lebih dulu dan sengaja memakai `is not
    None` (bukan truthiness) supaya server dengan 0 tool tetap dihitung ALIVE.
    """
    if tools_count is not None:
        return "ALIVE"

    low = (error or "").lower()
    if http_status in (401, 403):
        return "AUTH"
    if any(k in low for k in ("missing_bearer", "unauthorized", "auth required",
                              "api key", "invalid_token", "401", "403")):
        return "AUTH"
    if http_status is not None and 500 <= http_status <= 599:
        return "DEAD"
    if any(k in low for k in ("proxyerror", "timeout", "timed out",
                              "bad gateway", "connection refused",
                              "nodename nor servname", "name resolution",
                              "connecterror")):
        return "DEAD"
    if http_status == 200 and error:
        # Transport hidup, tapi payload tidak memberi data -> jangan mengklaim.
        return "UNKNOWN"
    if http_status == 200:
        return "ALIVE"
    return "UNKNOWN"


def describe() -> dict:
    """Ringkasan untuk endpoint /health."""
    return {
        "db_available": available(),
        "activation_rows": len(load_activation_ids()) if available() else len(_load_local_ids()),
        "health": health_summary() if available() else {v: 0 for v in VERDICTS},
        "tables": [TABLE_ACTIVATION, TABLE_HEALTH],
        "local_cache": str(_LOCAL_PATH),
    }
