#!/usr/bin/env python
"""enterprise_secrets_env_live.py — HARD TEST Fitur #1 dengan kredensial `.env`.

Berbeda dari `enterprise_secrets_live.py` (yang memakai Vault/OpenBao dev
LOKAL), skrip ini mengikat **provider NYATA yang kredensialnya sudah ada di
`.env`** — sesuai brief "REAL credentials, zero mock":

  * Nango      (`NANGO_API_KEY`)     -> https://api.nango.dev   (OAuth secrets)
  * Metorial   (`METORIAL_API_KEY`)  -> https://api.metorial.com (MCP providers)
  * KatalirVault (`VAULT_SECRET_KEY`) -> Supabase `user_vault` + Fernet

12 skenario; tiap skenario GAGAL bila integrasi rusak.

Pakai:
    python scripts/enterprise_secrets_env_live.py
    python scripts/enterprise_secrets_env_live.py --json docs/evidence/f01-secrets-env-live.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
OWNER = "budi@acme.test"
OWNER2 = "siti@acme.test"

HASIL: list[dict] = []


def _catat(no: int, nama: str, lulus: bool, raw: str, detail: dict | None = None) -> None:
    HASIL.append({"no": no, "skenario": nama, "status": "PASS" if lulus else "FAIL",
                  "raw": raw, "detail": detail or {}})
    print("=" * 78)
    print(f"#{no:02d} [{'PASS' if lulus else 'FAIL'}] {nama}")
    print("-" * 78)
    print(raw)
    print()


def _load_env() -> dict:
    env: dict[str, str] = {}
    with open(os.path.join(HERE, ".env"), encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.lstrip().startswith("#"):
                continue
            m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
            if m:
                env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return env


def _bind_env(env: dict) -> None:
    """Sambungkan kredensial `.env` ke nama env yang dipakai modul."""
    for k, v in env.items():
        os.environ.setdefault(k, v)
    os.environ["KATALIR_NANGO_KEY"] = env["NANGO_API_KEY"]
    os.environ["KATALIR_METORIAL_KEY"] = env["METORIAL_API_KEY"]
    # Vault Fernet (KatalirVault) memakai VAULT_SECRET_KEY langsung.


def _raw(url: str, headers: dict, method: str = "GET", body: bytes | None = None):
    req = urllib.request.Request(url, data=body, method=method)
    for k, v in headers.items():
        if body is None and k.lower() == "content-type":
            continue
        req.add_header(k, v)
    try:
        with OPENER.open(req, timeout=25) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return "ERR", f"{type(e).__name__}: {e}"


def _redact(teks: str) -> str:
    """Buang nilai token apa pun dari keluaran (mis. ghp_/pde_/pcf_ panjang)."""
    return re.sub(r"(ghp_|github_pat_|sk-|metorial_sk_)[A-Za-z0-9_\-]{8,}",
                  r"\1<REDACTED>", teks)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    env = _load_env()
    _bind_env(env)
    import secrets_provider as sp
    import vault_security as vs

    nango_key = env["NANGO_API_KEY"]
    met_key = env["METORIAL_API_KEY"]

    # --- 1. Connect ke provider NYATA yang ada di .env ---------------------
    s1a, b1a = _raw("https://api.nango.dev/integrations",
                    {"Authorization": f"Bearer {nango_key}", "User-Agent": UA})
    s1b, b1b = _raw("https://api.metorial.com/provider-deployments",
                    {"Authorization": f"Bearer {met_key}", "User-Agent": UA})
    try:
        n_integ = len(json.loads(b1a).get("data", []))
    except Exception:  # noqa: BLE001
        n_integ = -1
    try:
        n_depl = len(json.loads(b1b).get("items", []))
    except Exception:  # noqa: BLE001
        n_depl = -1
    vault_ok = sp.get_provider("katalir").available()
    lulus = s1a == 200 and s1b == 200 and n_integ >= 1 and n_depl >= 1 and vault_ok
    _catat(1, "Connect ke 3 provider NYATA dari .env (Nango+Metorial+KatalirVault)",
           lulus,
           f"GET api.nango.dev/integrations        -> HTTP {s1a}  ({n_integ} integrasi)\n"
           f"GET api.metorial.com/provider-deploy. -> HTTP {s1b}  ({n_depl} deployment)\n"
           f"KatalirVault.available() (Supabase)   -> {vault_ok}\n"
           f"CEK: ketiganya hidup via kredensial .env -> {lulus}",
           {"nango": s1a, "metorial": s1b, "integrations": n_integ})

    # --- 2. Resolve rahasia NYATA (bukan mock) -----------------------------
    np_ = sp.get_provider("nango")
    mp_ = sp.get_provider("metorial")
    set_nango = np_.set("demo/oauth", "ghp_contoh_token_nyata_123", OWNER)
    get_nango = np_.get("demo/oauth", OWNER)
    res_nango = sp.resolve("secret://nango/demo/oauth", OWNER)
    ids_met = mp_.list_paths(OWNER)
    get_met = mp_.get(ids_met[0], OWNER) if ids_met else None
    set_kv = sp.get_provider("katalir").set("demo/field", "nilai-vault-nyata", OWNER)
    get_kv = sp.get_provider("katalir").get("demo/field", OWNER)
    lulus = (set_nango and get_nango == "ghp_contoh_token_nyata_123"
             and res_nango == get_nango and bool(get_met) and set_kv and get_kv)
    _catat(2, "Resolve rahasia NYATA dari 3 provider .env", lulus,
           f"Nango     set/get/resolve -> {set_nango} / {get_nango!r} / {res_nango!r}\n"
           f"Metorial  deployment id   -> {ids_met[:1]} config={get_met!r}\n"
           f"Katalir   set/get (Supabase+Fernet) -> {set_kv} / {get_kv!r}\n"
           f"CEK: nilai asli kembali dari layanan nyata -> {lulus}",
           {"nango": bool(get_nango), "metorial": bool(get_met), "katalir": bool(get_kv)})

    # --- 3. Rotasi + riwayat versi ----------------------------------------
    r1 = sp.rotate("secret://katalir/rotasi/db", "v1", OWNER)
    r2 = sp.rotate("secret://katalir/rotasi/db", "v2", OWNER)
    r3 = sp.rotate("secret://katalir/rotasi/db", "v3", OWNER)
    akhir = sp.resolve("secret://katalir/rotasi/db", OWNER)
    riwayat = sp.rotation_store().history(OWNER, "rotasi/db")
    lulus = (r1["version"] < r2["version"] < r3["version"] and akhir == "v3"
             and len(riwayat) >= 3)
    _catat(3, "Rotasi rahasia + riwayat versi (KatalirVault)", lulus,
           f"rotate#1 version={r1['version']}  #2={r2['version']}  #3={r3['version']}\n"
           f"resolve -> {akhir!r}   riwayat={len(riwayat)} entri\n"
           f"CEK: versi naik & nilai terbaru menang -> {lulus}",
           {"versions": [r1["version"], r2["version"], r3["version"]]})

    # --- 4. Failover antar provider .env (Nango mati -> Katalir) -----------
    sp.get_provider("katalir").set("fo/kunci", "hanya-di-katalir", OWNER)
    simpan = os.environ.get("KATALIR_NANGO_KEY", "")
    os.environ["KATALIR_NANGO_KEY"] = "invalid-key-sengaja"
    try:
        t0 = time.time()
        nilai_fo = sp.resolve_with_failover("secret://nango/fo/kunci", OWNER,
                                            chain=["nango", "katalir"])
        durasi = time.time() - t0
    finally:
        os.environ["KATALIR_NANGO_KEY"] = simpan
    lulus = nilai_fo == "hanya-di-katalir"
    _catat(4, "Failover antar provider .env: Nango MATI -> KatalirVault", lulus,
           f"KATALIR_NANGO_KEY = <invalid> (Nango gagal auth)\n"
           f"resolve_with_failover(chain=[nango,katalir]) -> {nilai_fo!r} "
           f"({durasi*1000:.0f} ms)\n"
           f"CEK: backend rusak dilewati, nilai dari Katalir -> {lulus}",
           {"fallback": nilai_fo})

    # --- 5. 100 resolve KONKUREN ------------------------------------------
    for i in range(100):
        sp.get_provider("katalir").set(f"conc/k{i}", f"n{i}", OWNER)
    refs = [f"secret://katalir/conc/k{i}" for i in range(100)]

    def _ambil(r):
        return sp.resolve(r, OWNER)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=32) as pool:
        hasil_konk = list(pool.map(_ambil, refs))
    durasi = time.time() - t0
    benar = sum(1 for i, v in enumerate(hasil_konk) if v == f"n{i}")
    lulus = benar == 100
    _catat(5, "100 resolve KONKUREN (32 thread) -> semua benar", lulus,
           f"refs=100  max_workers=32\n"
           f"benar = {benar}/100   durasi = {durasi*1000:.0f} ms\n"
           f"contoh = {hasil_konk[:3]}\n"
           f"CEK: 100/100 tepat di bawah konkurensi -> {lulus}",
           {"correct": benar, "ms": round(durasi * 1000)})

    # --- 6. Isolasi multi-tenant (provider NYATA: Nango) -------------------
    np_.set("tenant/rahasia", "milik-budi", OWNER)
    np_.set("tenant/rahasia", "milik-siti", OWNER2)
    vb = np_.get("tenant/rahasia", OWNER)
    vc = np_.get("tenant/rahasia", OWNER2)
    lulus = vb == "milik-budi" and vc == "milik-siti" and vb != vc
    _catat(6, "Isolasi multi-tenant di Nango (path sama, owner beda)", lulus,
           f"owner {OWNER:16s} -> {vb!r}\n"
           f"owner {OWNER2:16s} -> {vc!r}\n"
           f"connection_id = <owner>__tenant__rahasia\n"
           f"CEK: nilai tidak saling bocor -> {lulus}",
           {"budi": vb, "siti": vc})

    # --- 7. Batas ukuran 256 KB -------------------------------------------
    besar = "x" * (256 * 1024 + 1)
    tepat = "y" * (256 * 1024)
    ditolak = None
    try:
        sp.check_size(besar)
    except Exception as exc:  # noqa: BLE001
        ditolak = type(exc).__name__
    diizinkan = sp.check_size(tepat)
    tolak_rotate = None
    try:
        sp.rotate("secret://katalir/too/big", besar, OWNER)
    except Exception as exc:  # noqa: BLE001
        tolak_rotate = type(exc).__name__
    lulus = (ditolak == "SecretTooLarge" and diizinkan == 256 * 1024
             and tolak_rotate == "SecretTooLarge")
    _catat(7, "Batas ukuran 256 KB (ditolak > batas, diterima tepat batas)", lulus,
           f"MAX_SECRET_BYTES    = {sp.MAX_SECRET_BYTES}\n"
           f"check_size(256KB+1) -> RAISES {ditolak}\n"
           f"check_size(256KB)   -> OK ({diizinkan} byte)\n"
           f"rotate(256KB+1)     -> RAISES {tolak_rotate}\n"
           f"CEK: batas ditegakkan 2 lapis -> {lulus}",
           {"limit": sp.MAX_SECRET_BYTES})

    # --- 8. Path traversal DITOLAK ----------------------------------------
    jahat = ["secret://../../etc/passwd", "secret://nango/../../etc/passwd",
             "secret://nango/a/..%2Fb", "secret://nango//etc/shadow",
             "secret://nango/..\\windows\\system32", "secret://nango/x\x00y"]
    ditolak_semua, detail = [], []
    for r in jahat:
        try:
            sp.parse_ref(r)
            detail.append(f"  DITERIMA (BAHAYA): {r}")
        except Exception as exc:  # noqa: BLE001
            ditolak_semua.append(r)
            detail.append(f"  ditolak {type(exc).__name__}: {r}")
    lulus = len(ditolak_semua) == len(jahat)
    _catat(8, "Path traversal / segmen berbahaya DITOLAK", lulus,
           "\n".join(detail) + f"\nCEK: {len(ditolak_semua)}/{len(jahat)} ditolak -> {lulus}",
           {"rejected": len(ditolak_semua), "total": len(jahat)})

    # --- 9. Performa: 100 resolve < 1 detik -------------------------------
    for i in range(100):
        sp.get_provider("katalir").set(f"perf/k{i}", f"p{i}", OWNER)
    rp = [f"secret://katalir/perf/k{i}" for i in range(100)]
    t0 = time.time()
    hasil_perf = sp.resolve_many(rp, OWNER, max_workers=16)
    durasi = time.time() - t0
    ok_perf = sum(1 for v in hasil_perf.values() if v is not None)
    lulus = ok_perf == 100 and durasi < 1.0
    _catat(9, "Performa: 100 resolve paralel < 1 detik", lulus,
           f"refs=100  resolve_many(max_workers=16)\n"
           f"berhasil = {ok_perf}/100   durasi = {durasi*1000:.0f} ms (batas 1000)\n"
           f"CEK: benar DAN < 1s -> {lulus}",
           {"ms": round(durasi * 1000), "ok": ok_perf})

    # --- 10. Terenkripsi at-rest (Fernet dgn VAULT_SECRET_KEY .env) --------
    rahasia = "sk-live-abcdef1234567890"
    cipher = vs.encrypt_key(rahasia)
    pulih = vs.decrypt_key(cipher)
    lulus = (rahasia not in cipher and pulih == rahasia and cipher.startswith("gAAAAA"))
    _catat(10, "Kredensial TERENKRIPSI (Fernet + VAULT_SECRET_KEY .env)", lulus,
           f"plaintext di ciphertext? {rahasia in cipher} (harus False)\n"
           f"ciphertext = {cipher[:44]}… ({len(cipher)} char)  prefix={cipher.startswith('gAAAAA')}\n"
           f"decrypt(cipher) cocok? {pulih == rahasia}\n"
           f"CEK: nilai tidak bocor di penyimpanan -> {lulus}",
           {"cipher_len": len(cipher)})

    # --- 11. Error handling JELAS -----------------------------------------
    pesan_ref = pesan_be = pesan_nf = None
    try:
        sp.parse_ref("bukan-ref")
    except Exception as exc:  # noqa: BLE001
        pesan_ref = type(exc).__name__
    try:
        sp.get_provider("backend-hantu")
    except Exception as exc:  # noqa: BLE001
        pesan_be = type(exc).__name__
    try:
        sp.resolve("secret://nango/tidak/ada-xyz", OWNER)
    except Exception as exc:  # noqa: BLE001
        pesan_nf = type(exc).__name__
    lulus = (pesan_ref == "SecretRefError" and pesan_be == "BackendUnavailable"
             and pesan_nf in ("SecretNotFound", "BackendUnavailable"))
    _catat(11, "Error handling: ref salah / backend hantu / rahasia hilang", lulus,
           f"parse_ref('bukan-ref')        -> RAISES {pesan_ref}\n"
           f"get_provider('backend-hantu') -> RAISES {pesan_be}\n"
           f"resolve(hilang)               -> RAISES {pesan_nf}\n"
           f"CEK: galat terklasifikasi, bukan gantung -> {lulus}",
           {"ref": pesan_ref, "backend": pesan_be, "notfound": pesan_nf})

    # --- 12. RAW OUTPUT dari layanan nyata ---------------------------------
    s12a, b12a = _raw("https://api.nango.dev/connections",
                      {"Authorization": f"Bearer {nango_key}", "User-Agent": UA})
    s12b, b12b = _raw("https://api.metorial.com/provider-deployments",
                      {"Authorization": f"Bearer {met_key}", "User-Agent": UA})
    lulus = s12a == 200 and s12b == 200
    _catat(12, "RAW OUTPUT dari layanan nyata (Nango + Metorial)", lulus,
           f"GET https://api.nango.dev/connections -> HTTP {s12a}\n"
           f"  {_redact(b12a)[:220]}\n"
           f"GET https://api.metorial.com/provider-deployments -> HTTP {s12b}\n"
           f"  {_redact(b12b)[:220]}\n"
           f"CEK: respons HTTP asli dari SaaS -> {lulus}",
           {"nango_status": s12a, "metorial_status": s12b})

    lulus_n = sum(1 for h in HASIL if h["status"] == "PASS")
    print("=" * 78)
    print(f"RINGKASAN HARD TEST FITUR #1 (.env real): {lulus_n}/{len(HASIL)} PASS")
    print("=" * 78)
    for h in HASIL:
        print(f"  #{h['no']:02d} [{h['status']}] {h['skenario']}")

    if args.json:
        out = os.path.join(HERE, args.json) if not os.path.isabs(args.json) else args.json
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({"feature": "#1 External Secrets Manager (.env real)",
                       "lulus": lulus_n, "total": len(HASIL), "hasil": HASIL},
                      fh, indent=2, ensure_ascii=False)
        print(f"\nJSON -> {args.json}")
    return 0 if lulus_n == len(HASIL) else 1


if __name__ == "__main__":
    raise SystemExit(main())
