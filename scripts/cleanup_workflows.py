#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Bersihkan workflow secara AMAN (pengganti praktik berbahaya sebelumnya).

Latar belakang: pada 2026-09-21 sesi agent menjalankan
`DELETE /workflows?name=eq.Draft Workflow` dengan service key -- TANPA filter
pemilik, TANPA dry-run, TANPA backup. Akibatnya 11 baris terhapus (8 di antaranya
bernama "Draft Workflow") dan isinya tidak bisa dipulihkan.

Aturan skrip ini (semua WAJIB, kalau tidak -> ditolak):
  1. `--owner <email>` ATAU `--owner-id <uuid>`  -> hanya milik pemilik itu.
  2. Default DRY-RUN: hanya mencetak apa yang AKAN dihapus.
  3. `--confirm` untuk benar-benar menghapus.
  4. `--backup <path>` WAJIB saat `--confirm` (JSON ditulis sebelum hapus).
  5. `--name <nama>` opsional sebagai penyaring tambahan (bukan satu-satunya
     saringan -- pemilik tetap wajib).

Contoh:
  python scripts/cleanup_workflows.py --owner user@example.com                 # dry-run
  python scripts/cleanup_workflows.py --owner user@example.com --name "L3 auto-run probe" --confirm --backup out.json
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _env():
    try:
        from dotenv import dotenv_values
    except ImportError:
        print("FATAL: python-dotenv tidak terpasang.")
        sys.exit(2)
    v = dotenv_values(os.path.join(ROOT, ".env"))
    url = (v.get("SUPABASE_URL") or "").strip().rstrip("/")
    key = (v.get("SUPABASE_SERVICE_ROLE_KEY") or v.get("SUPABASE_SERVICE_KEY") or "").strip()
    if not url or not key:
        print("FATAL: SUPABASE_URL / SUPABASE_SERVICE[_ROLE]_KEY tidak ada di .env")
        sys.exit(2)
    return url, key


def _req(url, key, path, method="GET", body=None, prefer=None):
    headers = {"apikey": key, "Authorization": "Bearer " + key,
               "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]


def resolve_owner_id(url, key, email=None, owner_id=None):
    """Email -> auth user id (workflows.user_id ber-FK ke auth.users.id)."""
    if owner_id:
        return owner_id
    st, d = _req(url, key, "/auth/v1/admin/users?per_page=200")
    if st != 200 or not isinstance(d, dict):
        print("FATAL: tidak bisa membaca auth.users (HTTP %s)" % st)
        sys.exit(2)
    for u in d.get("users", []):
        if (u.get("email") or "").lower() == email.lower():
            return u.get("id")
    print("FATAL: email %s tidak ditemukan di auth.users" % email)
    sys.exit(2)


def main():
    ap = argparse.ArgumentParser(description="Hapus workflow dengan aman (owner-scoped).")
    ap.add_argument("--owner", help="email pemilik (di-resolve ke auth.users.id)")
    ap.add_argument("--owner-id", help="uuid pemilik langsung")
    ap.add_argument("--name", help="opsional: saring nama persis")
    ap.add_argument("--confirm", action="store_true", help="benar-benar menghapus")
    ap.add_argument("--backup", help="path file backup JSON (WAJIB bila --confirm)")
    args = ap.parse_args()

    if not args.owner and not args.owner_id:
        print("DITOLAK: wajib --owner <email> atau --owner-id <uuid>.")
        print("           (menghapus tanpa filter pemilik = praktik yang merusak data)")
        sys.exit(1)
    if args.confirm and not args.backup:
        print("DITOLAK: --confirm wajib disertai --backup <path>.")
        sys.exit(1)

    url, key = _env()
    owner = resolve_owner_id(url, key, args.owner, args.owner_id)
    print("OWNER_ID=%s…%s" % (owner[:8], owner[-4:]))
    print("MODE=%s" % ("CONFIRM (menghapus)" if args.confirm else "DRY-RUN (tidak menghapus)"))

    q = "/rest/v1/workflows?select=id,name,created_at&user_id=eq." + urllib.parse.quote(owner)
    if args.name:
        q += "&name=eq." + urllib.parse.quote(args.name)
    st, rows = _req(url, key, q)
    if st != 200 or not isinstance(rows, list):
        print("FATAL: gagal list workflow (HTTP %s) %s" % (st, rows))
        sys.exit(2)

    print("KANDIDAT=%d" % len(rows))
    for r in rows:
        print("   %s | %s | %s" % (r.get("id"), (r.get("created_at") or "")[:19], r.get("name")))
    if not rows:
        print("Selesai: tidak ada yang dihapus.")
        return
    if not args.confirm:
        print("\nDRY-RUN selesai. Tidak ada baris dihapus. Tambahkan --confirm --backup <file>.")
        return

    os.makedirs(os.path.dirname(os.path.abspath(args.backup)) or ".", exist_ok=True)
    with open(args.backup, "w", encoding="utf-8") as f:
        json.dump({"ts": datetime.now(timezone.utc).isoformat(), "owner_id": owner,
                   "rows": rows}, f, ensure_ascii=False, indent=1)
    print("BACKUP=%s (%d baris)" % (args.backup, len(rows)))

    sent = 0
    for r in rows:
        # Filter ganda: id DAN user_id -> mustahil menyentuh milik orang lain.
        dq = ("/rest/v1/workflows?id=eq." + urllib.parse.quote(r["id"])
              + "&user_id=eq." + urllib.parse.quote(owner))
        st2, _ = _req(url, key, dq, method="DELETE", prefer="return=minimal")
        print("   DELETE %s -> HTTP %s" % (r["id"], st2))
        if st2 in (200, 204):
            sent += 1
    print("DIHAPUS=%d dari %d kandidat" % (sent, len(rows)))


if __name__ == "__main__":
    main()
