"""backup_rollback.py — backup + rollback untuk E2E sandbox.

PRINSIP DATA-MINIMIZATION
-------------------------
Test ini berjalan MODE MOCK: ia tidak menulis apa pun ke Supabase. Karena itu
backup yang diambil adalah **snapshot terarah** (hitungan baris + baris
bertanda test), BUKAN dump penuh tabel produksi.

Alasannya bukan kemalasan: menyalin baris produksi ke disk lokal — bahkan
setelah di-redact — justru menambah permukaan kebocoran, dan bertentangan
dengan prinsip zero-trust yang jadi alasan brief ini ditulis. Bila kelak
live mode dijalankan dan benar-benar menulis, `backup(full=True)` tersedia.

Rollback selalu **dry-run secara default**.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import database as db  # noqa: E402

#: Penanda baris milik test ini.
TAG = "test-2026-10-07"

BACKUP_DIR = Path(__file__).resolve().parent / "backups"


def _client():
    """Client BACA ber-privilese (service role).

    PENTING: `db._get_client()` memakai ANON key, dan RLS menyembunyikan baris
    produksi darinya — "0 baris" dari anon BUKAN bukti bahwa tabel kosong.
    Karena itu pembacaan memakai `_get_write_client()` (service role), yang
    membaca apa adanya. Operasi di sini tetap READ-ONLY.
    """
    try:
        return db._get_write_client()
    except Exception:  # noqa: BLE001
        try:
            return db._get_client()
        except Exception:  # noqa: BLE001
            return None


def is_configured() -> bool:
    return _client() is not None


def snapshot_counts() -> dict:
    """Hitungan baris per tabel (READ-ONLY, tanpa data)."""
    client = _client()
    if client is None:
        return {"configured": False}
    out: dict = {"configured": True}
    for table in ("workflows", "execution_logs", "chat_messages"):
        try:
            res = client.table(table).select("id", count="exact").limit(1).execute()
            out[table] = res.count
        except Exception as exc:  # noqa: BLE001
            out[table] = f"error: {type(exc).__name__}"
    return out


def find_test_rows(tag: str = TAG) -> dict:
    """Cari baris bertanda test. Diharapkan 0 pada mode mock."""
    client = _client()
    if client is None:
        return {"configured": False}
    out: dict = {"tag": tag, "configured": True}
    try:
        res = (client.table("workflows").select("id,name")
               .ilike("name", f"%{tag}%").limit(100).execute())
        out["workflows"] = len(res.data or [])
        out["workflow_ids"] = [r.get("id") for r in (res.data or [])]
    except Exception as exc:  # noqa: BLE001
        out["workflows"] = f"error: {type(exc).__name__}"
    try:
        # CATATAN: `execution_id` bertipe UUID — `ilike` GAGAL di PostgREST
        # ("operator does not exist: uuid ~~* unknown", kode 42883). Jadi
        # pencarian tag dilakukan di sisi klien atas kolom teksnya.
        res = (client.table("execution_logs")
               .select("execution_id,node_id,node_type,status")
               .limit(5000).execute())
        rows = res.data or []
        matches = [r for r in rows if tag in json.dumps(r, default=str)]
        out["execution_logs"] = len(matches)
        out["execution_log_rows_scanned"] = len(rows)
    except Exception as exc:  # noqa: BLE001
        out["execution_logs"] = f"error: {type(exc).__name__}"
    return out


def backup(tag: str = TAG, *, full: bool = False) -> dict:
    """Tulis snapshot ke `tests/sandbox/backups/`.

    Args:
        full: True -> dump teredaksi seluruh `workflows` (dipakai HANYA bila
            live mode benar-benar menulis). Default False: snapshot terarah.
    """
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = BACKUP_DIR / f"{tag}-{stamp}.json"

    payload: dict = {
        "tag": tag,
        "ts": stamp,
        "mode": "full" if full else "scoped",
        "counts": snapshot_counts(),
        "test_rows": find_test_rows(tag),
    }

    if full:
        client = _client()
        rows: list = []
        if client is not None:
            try:
                res = client.table("workflows").select("*").limit(5000).execute()
                # WAJIB: redaksi sebelum menyentuh disk.
                rows = db.redact_sensitive(res.data or [])
            except Exception as exc:  # noqa: BLE001
                rows = [{"error": type(exc).__name__}]
        payload["workflows"] = rows

    blob = json.dumps(payload, indent=2, default=str)
    path.write_text(blob, encoding="utf-8")
    payload["_path"] = str(path)
    payload["_sha256"] = hashlib.sha256(blob.encode()).hexdigest()[:16]
    return payload


def rollback(tag: str = TAG, *, dry_run: bool = True) -> dict:
    """Hapus baris bertanda test. Default dry-run (aman)."""
    found = find_test_rows(tag)
    if dry_run:
        return {"dry_run": True, "would_delete": found}
    client = _client()
    if client is None:
        return {"dry_run": False, "error": "Supabase tidak dikonfigurasi"}

    deleted: dict = {}
    try:
        res = (client.table("workflows").delete()
               .ilike("name", f"%{tag}%").execute())
        deleted["workflows"] = len(res.data or [])
    except Exception as exc:  # noqa: BLE001
        deleted["workflows"] = f"error: {type(exc).__name__}"
    try:
        # UUID tidak mendukung `ilike` -> kumpulkan id yang cocok lebih dulu.
        res = (client.table("execution_logs")
               .select("execution_id,node_id,node_type,status")
               .limit(5000).execute())
        ids = sorted({r["execution_id"] for r in (res.data or [])
                      if tag in json.dumps(r, default=str)})
        if ids:
            client.table("execution_logs").delete().in_("execution_id", ids).execute()
        deleted["execution_logs"] = len(ids)
    except Exception as exc:  # noqa: BLE001
        deleted["execution_logs"] = f"error: {type(exc).__name__}"
    return {"dry_run": False, "deleted": deleted}


def main() -> int:
    print("=" * 70)
    print("BAGIAN 4 — BACKUP + ROLLBACK (mode mock: tidak ada tulis produksi)")
    print("=" * 70)

    print(f"\n[4.1a] Hitungan baris (READ-ONLY):")
    counts = snapshot_counts()
    print(f"  {json.dumps(counts, indent=2)}")

    print(f"\n[4.1b] Baris bertanda test '{TAG}' (harap 0):")
    found = find_test_rows()
    print(f"  {json.dumps(found, indent=2)}")

    print(f"\n[4.1c] Snapshot backup:")
    info = backup()
    print(f"  path   : {info['_path']}")
    print(f"  sha256 : {info['_sha256']}")
    print(f"  mode   : {info['mode']}")

    print(f"\n[4.2] Rollback (DRY-RUN — tidak menghapus apa pun):")
    rb = rollback(dry_run=True)
    print(f"  {json.dumps(rb, indent=2)}")

    ok = (counts.get("configured") is True
          and found.get("workflows") == 0
          and found.get("execution_logs") == 0)
    print(f"\nVERDICT BAGIAN 4: {'PASS' if ok else 'PERIKSA'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
