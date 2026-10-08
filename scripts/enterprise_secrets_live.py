#!/usr/bin/env python
"""enterprise_secrets_live.py — Hard test Fitur #1 (External Secrets Manager).

Menjalankan 12 skenario WAJIB terhadap **3 provider NYATA** yang berjalan
sebagai proses sungguhan (bukan seam yang disuntik):

  * HashiCorp Vault 2.1.2   -> http://127.0.0.1:8200   (dev server, KV v2)
  * OpenBao 2.7.1           -> http://127.0.0.1:8210   (fork Vault, LF)
  * AWS Secrets Manager     -> http://127.0.0.1:4566   (MiniStack, boto3)

Pakai:
    python scripts/enterprise_secrets_live.py
    python scripts/enterprise_secrets_live.py --json docs/evidence/f01-secrets-live.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

VAULT_ADDR = "http://127.0.0.1:8200"
VAULT_TOKEN = "katalir-dev-root"
OPENBAO_ADDR = "http://127.0.0.1:8210"
OPENBAO_TOKEN = "openbao-dev-root"
AWS_ENDPOINT = "http://127.0.0.1:4566"
DEAD_ADDR = "http://127.0.0.1:8299"          # tidak ada yang mendengarkan

HASIL: list[dict] = []


def _catat(no: int, nama: str, lulus: bool, raw: str, detail: dict | None = None) -> None:
    HASIL.append({"no": no, "skenario": nama, "status": "PASS" if lulus else "FAIL",
                  "raw": raw, "detail": detail or {}})
    print("=" * 78)
    print(f"#{no:02d} [{'PASS' if lulus else 'FAIL'}] {nama}")
    print("-" * 78)
    print(raw)
    print()


def _setup_env() -> None:
    os.environ["KATALIR_VAULT_ADDR"] = VAULT_ADDR
    os.environ["KATALIR_VAULT_TOKEN"] = VAULT_TOKEN
    os.environ["KATALIR_VAULT_MOUNT"] = "secret"
    os.environ["KATALIR_OPENBAO_ADDR"] = OPENBAO_ADDR
    os.environ["KATALIR_OPENBAO_TOKEN"] = OPENBAO_TOKEN
    os.environ["KATALIR_OPENBAO_MOUNT"] = "secret"
    os.environ["KATALIR_AWS_ENDPOINT_URL"] = AWS_ENDPOINT
    os.environ["KATALIR_AWS_REGION"] = "us-east-1"
    os.environ["KATALIR_AWS_ACCESS_KEY_ID"] = "katalir-local"
    os.environ["KATALIR_AWS_SECRET_ACCESS_KEY"] = "katalir-local"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    _setup_env()

    import secrets_provider as sp
    import vault_security as vs

    OWNER = "budi@acme.test"
    OWNER2 = "siti@acme.test"

    # --- 1. Vault NYATA: connect + resolve ---------------------------------
    p = sp.get_provider("hashicorp")
    info = p.info()
    ok = p.set("demo/db", "vault-pass-2026", OWNER)
    v = p.get("demo/db", OWNER)
    ref = sp.resolve("secret://hashicorp/demo/db", OWNER)
    lulus = (info.get("version", "").startswith("2.")
             and info.get("sealed") is False and v == "vault-pass-2026"
             and ref == "vault-pass-2026")
    _catat(1, "HashiCorp Vault 2.1.2 NYATA: connect + resolve (KV v2)", lulus,
           f"addr        = {info.get('addr')}\n"
           f"version     = {info.get('version')}   sealed={info.get('sealed')}\n"
           f"cluster     = {info.get('cluster_name')}\n"
           f"SET demo/db -> {ok}\n"
           f"GET demo/db -> {v!r}\n"
           f"resolve secret://hashicorp/demo/db -> {ref!r}\n"
           f"CEK: server 2.x, unsealed, nilai benar -> {lulus}",
           {"version": info.get("version"), "sealed": info.get("sealed")})

    # --- 2. OpenBao NYATA: connect + resolve -------------------------------
    p2 = sp.get_provider("openbao")
    info2 = p2.info()
    p2.set("demo/db", "openbao-pass-2026", OWNER)
    v2 = p2.get("demo/db", OWNER)
    ref2 = sp.resolve("secret://openbao/demo/db", OWNER)
    lulus = (info2.get("version", "").startswith("2.")
             and info2.get("sealed") is False and v2 == "openbao-pass-2026"
             and ref2 == "openbao-pass-2026")
    _catat(2, "OpenBao 2.7.1 NYATA: connect + resolve (fork Vault, LF)", lulus,
           f"addr        = {info2.get('addr')}\n"
           f"version     = {info2.get('version')}   sealed={info2.get('sealed')}\n"
           f"cluster     = {info2.get('cluster_name')}\n"
           f"SET demo/db -> OK\n"
           f"GET demo/db -> {v2!r}\n"
           f"resolve secret://openbao/demo/db -> {ref2!r}\n"
           f"CEK: produk BERBEDA dari Vault, nilai benar -> {lulus}",
           {"version": info2.get("version"), "sealed": info2.get("sealed")})

    # --- 3. AWS Secrets Manager NYATA (MiniStack) --------------------------
    p3 = sp.get_provider("aws")
    info3 = p3.info()
    p3.set("demo/db", "aws-pass-2026", OWNER)
    v3 = p3.get("demo/db", OWNER)
    ref3 = sp.resolve("secret://aws/demo/db", OWNER)
    lst = p3.list_paths(OWNER)
    lulus = (v3 == "aws-pass-2026" and ref3 == "aws-pass-2026"
             and "demo/db" in lst and info3.get("secret_count", 0) >= 1)
    _catat(3, "AWS Secrets Manager NYATA (boto3 + MiniStack :4566)", lulus,
           f"endpoint    = {info3.get('endpoint')}   region={info3.get('region')}\n"
           f"secret_count= {info3.get('secret_count')}\n"
           f"SET demo/db -> OK\n"
           f"GET demo/db -> {v3!r}\n"
           f"resolve secret://aws/demo/db -> {ref3!r}\n"
           f"list_paths  -> {lst}\n"
           f"CEK: boto3 ke API AWS bentuk-nyata, nilai benar -> {lulus}",
           {"endpoint": info3.get("endpoint"), "count": info3.get("secret_count")})

    # --- 4. Failover: Vault MATI -> OpenBao --------------------------------
    # Tulis HANYA ke openbao, lalu arahkan hashicorp ke alamat mati.
    p2.set("failover/key", "hanya-di-openbao", OWNER)
    simpan = os.environ["KATALIR_VAULT_ADDR"]
    os.environ["KATALIR_VAULT_ADDR"] = DEAD_ADDR
    try:
        t0 = time.time()
        nilai_fo = sp.resolve_with_failover("secret://hashicorp/failover/key", OWNER,
                                            chain=["hashicorp", "openbao"])
        durasi = time.time() - t0
        galat_langsung = None
        try:
            sp.resolve("secret://hashicorp/failover/key", OWNER)
        except Exception as exc:  # noqa: BLE001
            galat_langsung = f"{type(exc).__name__}"
    finally:
        os.environ["KATALIR_VAULT_ADDR"] = simpan
    lulus = (nilai_fo == "hanya-di-openbao" and galat_langsung is not None)
    _catat(4, "Failover: Vault MATI -> OpenBao (rantai backend)", lulus,
           f"KATALIR_VAULT_ADDR = {DEAD_ADDR} (mati)\n"
           f"resolve langsung      -> RAISES {galat_langsung}\n"
           f"resolve_with_failover -> {nilai_fo!r}  ({durasi*1000:.0f} ms)\n"
           f"CEK: backend mati dilewati, nilai dari OpenBao -> {lulus}",
           {"fallback": nilai_fo, "direct_error": galat_langsung})

    # --- 5. Rotasi + riwayat versi -----------------------------------------
    r1 = sp.rotate("secret://openbao/rotate/db", "v1-rahasia", OWNER)
    r2 = sp.rotate("secret://openbao/rotate/db", "v2-rahasia", OWNER)
    r3 = sp.rotate("secret://openbao/rotate/db", "v3-rahasia", OWNER)
    akhir = sp.resolve("secret://openbao/rotate/db", OWNER)
    riwayat = sp.rotation_store().history(OWNER, "rotate/db")
    lulus = (r1["version"] == 1 and r2["version"] == 2 and r3["version"] == 3
             and akhir == "v3-rahasia" and len(riwayat) == 3)
    _catat(5, "Rotasi rahasia + riwayat versi", lulus,
           f"rotate #1 -> version={r1['version']} bytes={r1['bytes']}\n"
           f"rotate #2 -> version={r2['version']} bytes={r2['bytes']}\n"
           f"rotate #3 -> version={r3['version']} bytes={r3['bytes']}\n"
           f"resolve   -> {akhir!r}\n"
           f"riwayat   -> {len(riwayat)} entri\n"
           f"CEK: versi naik monoton + nilai terbaru menang -> {lulus}",
           {"versions": [r1["version"], r2["version"], r3["version"]]})

    # --- 6. 100 resolve KONKUREN -------------------------------------------
    for i in range(100):
        sp.get_provider("openbao").set(f"conc/k{i}", f"nilai-{i}", OWNER)
    refs = [f"secret://openbao/conc/k{i}" for i in range(100)]

    def _ambil(r):
        return sp.resolve(r, OWNER)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=32) as pool:
        hasil_konk = list(pool.map(_ambil, refs))
    durasi = time.time() - t0
    benar = sum(1 for i, v in enumerate(hasil_konk) if v == f"nilai-{i}")
    lulus = benar == 100
    _catat(6, "100 resolve KONKUREN (32 thread) -> semua benar", lulus,
           f"refs        = 100\n"
           f"max_workers = 32\n"
           f"benar       = {benar}/100\n"
           f"durasi      = {durasi*1000:.0f} ms\n"
           f"contoh      = {hasil_konk[:3]}\n"
           f"CEK: 100/100 nilai tepat di bawah konkurensi -> {lulus}",
           {"correct": benar, "ms": round(durasi * 1000)})

    # --- 7. Isolasi multi-tenant -------------------------------------------
    sp.get_provider("openbao").set("tenant/rahasia", "milik-budi", OWNER)
    sp.get_provider("openbao").set("tenant/rahasia", "milik-siti", OWNER2)
    vb = sp.resolve("secret://openbao/tenant/rahasia", OWNER)
    vs_ = sp.resolve("secret://openbao/tenant/rahasia", OWNER2)
    # path yang sama, owner berbeda -> nilai berbeda (namespace terpisah)
    daftar_budi = sp.get_provider("openbao").list_paths(OWNER)
    lulus = (vb == "milik-budi" and vs_ == "milik-siti" and vb != vs_)
    _catat(7, "Isolasi multi-tenant (path sama, owner beda)", lulus,
           f"owner {OWNER:20s} -> {vb!r}\n"
           f"owner {OWNER2:20s} -> {vs_!r}\n"
           f"namespace Vault = <owner>/<path>\n"
           f"list_paths(budi) memuat 'tenant'? {'tenant' in daftar_budi}\n"
           f"CEK: nilai TIDAK saling bocor -> {lulus}",
           {"budi": vb, "siti": vs_})

    # --- 8. Batas ukuran 256 KB --------------------------------------------
    besar = "x" * (256 * 1024 + 1)          # 1 byte di atas batas
    tepat = "y" * (256 * 1024)              # tepat di batas -> boleh
    ditolak = None
    try:
        sp.check_size(besar)
    except Exception as exc:  # noqa: BLE001
        ditolak = f"{type(exc).__name__}"
    diizinkan = sp.check_size(tepat)
    # bukti end-to-end: rotasi dengan nilai > batas juga harus DITOLAK
    tolak_rotate = None
    try:
        sp.rotate("secret://openbao/too/big", besar, OWNER)
    except Exception as exc:  # noqa: BLE001
        tolak_rotate = f"{type(exc).__name__}"
    lulus = (ditolak == "SecretTooLarge" and diizinkan == 256 * 1024
             and tolak_rotate == "SecretTooLarge")
    _catat(8, "Batas ukuran 256 KB (ditolak > batas, diterima tepat batas)", lulus,
           f"MAX_SECRET_BYTES      = {sp.MAX_SECRET_BYTES}\n"
           f"check_size(256KB+1)   -> RAISES {ditolak}\n"
           f"check_size(256KB)     -> OK ({diizinkan} byte)\n"
           f"rotate(256KB+1)       -> RAISES {tolak_rotate}\n"
           f"CEK: batas ditegakkan di dua lapis -> {lulus}",
           {"limit": sp.MAX_SECRET_BYTES})

    # --- 9. Path traversal DITOLAK -----------------------------------------
    jahat = ["secret://../../etc/passwd",
             "secret://openbao/../../etc/passwd",
             "secret://openbao/a/..%2Fb",
             "secret://openbao//etc/shadow",
             "secret://openbao/..\\windows\\system32",
             "secret://openbao/x\x00y"]
    ditolak_semua, detail_jahat = [], []
    for r in jahat:
        try:
            sp.parse_ref(r)
            detail_jahat.append(f"  DITERIMA (BAHAYA): {r}")
        except Exception as exc:  # noqa: BLE001
            ditolak_semua.append(r)
            detail_jahat.append(f"  ditolak {type(exc).__name__}: {r}")
    lulus = len(ditolak_semua) == len(jahat)
    _catat(9, "Path traversal / segmen berbahaya DITOLAK", lulus,
           "\n".join(detail_jahat)
           + f"\nCEK: {len(ditolak_semua)}/{len(jahat)} ditolak -> {lulus}",
           {"rejected": len(ditolak_semua), "total": len(jahat)})

    # --- 10. Performa: 100 resolve < 1 detik --------------------------------
    for i in range(100):
        sp.get_provider("openbao").set(f"perf/k{i}", f"p{i}", OWNER)
    rp = [f"secret://openbao/perf/k{i}" for i in range(100)]
    t0 = time.time()
    hasil_perf = sp.resolve_many(rp, OWNER, max_workers=16)
    durasi = time.time() - t0
    ok_perf = sum(1 for k, v in hasil_perf.items() if v is not None)
    lulus = ok_perf == 100 and durasi < 1.0
    _catat(10, "Performa: 100 resolve paralel < 1 detik", lulus,
           f"refs        = 100\n"
           f"resolve_many(max_workers=16)\n"
           f"berhasil    = {ok_perf}/100\n"
           f"durasi      = {durasi*1000:.0f} ms  (batas 1000 ms)\n"
           f"CEK: benar DAN < 1s -> {lulus}",
           {"ms": round(durasi * 1000), "ok": ok_perf})

    # --- 11. Kredensial TERENKRIPSI (Fernet) --------------------------------
    rahasia = "sk-live-abcdef1234567890"
    cipher = vs.encrypt_key(rahasia)
    pulih = vs.decrypt_key(cipher)
    lulus = (rahasia not in cipher and pulih == rahasia
             and cipher.startswith("gAAAAA"))
    _raw11 = (f"plaintext          = {rahasia[:6]}… ({len(rahasia)} char)\n"
                  f"ciphertext         = {cipher[:44]}… ({len(cipher)} char)\n"
                  f"plaintext di cipher? {rahasia in cipher}  (harus False)\n"
                  f"prefix Fernet      = {cipher.startswith('gAAAAA')}\n"
                  f"decrypt(cipher)    = {pulih!r}  cocok={pulih == rahasia}\n"
                  f"CEK: ciphertext TIDAK memuat plaintext -> {lulus}")
    _catat(11, "Kredensial TERENKRIPSI (Fernet/AES-128-CBC + HMAC)", lulus,
           _raw11, {"cipher_len": len(cipher)})

    # --- 12. Provider MATI -> pesan galat JELAS -----------------------------
    simpan = os.environ["KATALIR_VAULT_ADDR"]
    os.environ["KATALIR_VAULT_ADDR"] = DEAD_ADDR
    try:
        t0 = time.time()
        pesan, jenis = None, None
        try:
            sp.resolve("secret://hashicorp/tidak/ada", OWNER)
        except Exception as exc:  # noqa: BLE001
            pesan, jenis = str(exc), type(exc).__name__
        durasi = time.time() - t0
    finally:
        os.environ["KATALIR_VAULT_ADDR"] = simpan
    lulus = (jenis in ("SecretNotFound", "BackendUnavailable")
             and pesan is not None and len(pesan) > 10
             and "traceback" not in pesan.lower()
             and durasi < 15.0)
    _catat(12, "Provider MATI -> galat JELAS (bukan gantung/500)", lulus,
           f"KATALIR_VAULT_ADDR = {DEAD_ADDR} (mati)\n"
           f"resolve secret://hashicorp/tidak/ada\n"
           f"  RAISES {jenis}: {pesan}\n"
           f"durasi      = {durasi:.1f}s (tanpa gantung)\n"
           f"CEK: galat terklasifikasi + pesan jelas -> {lulus}",
           {"error": jenis, "seconds": round(durasi, 1)})

    # --- ringkasan ----------------------------------------------------------
    lulus_n = sum(1 for h in HASIL if h["status"] == "PASS")
    print("=" * 78)
    print(f"RINGKASAN HARD TEST FITUR #1: {lulus_n}/{len(HASIL)} PASS")
    print("=" * 78)
    for h in HASIL:
        print(f"  #{h['no']:02d} [{h['status']}] {h['skenario']}")

    if args.json:
        out = os.path.join(HERE, args.json) if not os.path.isabs(args.json) else args.json
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({"feature": "#1 External Secrets Manager",
                       "lulus": lulus_n, "total": len(HASIL), "hasil": HASIL},
                      fh, indent=2, ensure_ascii=False)
        print(f"\nJSON -> {args.json}")
    return 0 if lulus_n == len(HASIL) else 1


if __name__ == "__main__":
    raise SystemExit(main())
