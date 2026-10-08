#!/usr/bin/env python
"""enterprise_scm_live.py — Hard test Fitur #5 (Source Control / Git).

Menjalankan 12 skenario WAJIB terhadap **GitHub NYATA** (REST API v3,
repo `vraafi/katalir-scm-verify`) memakai PAT asli — bukan transport palsu.

Pakai:
    python scripts/enterprise_scm_live.py
    python scripts/enterprise_scm_live.py --json docs/evidence/f05-scm-live.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv_loader import load_repo_env  # noqa: E402

load_repo_env()

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.environ.get("KATALIR_SCM_REPO", "vraafi/katalir-scm-verify")
HASIL: list[dict] = []


def _catat(no: int, nama: str, lulus: bool, raw: str, detail: dict | None = None) -> None:
    HASIL.append({"no": no, "skenario": nama, "status": "PASS" if lulus else "FAIL",
                  "raw": raw, "detail": detail or {}})
    print("=" * 78)
    print(f"#{no:02d} [{'PASS' if lulus else 'FAIL'}] {nama}")
    print("-" * 78)
    print(raw)
    print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    ap.add_argument("--repo", default=REPO)
    args = ap.parse_args()

    import source_control as sc

    TOKEN = os.environ.get("GITHUB_TOKEN", "")
    if not TOKEN:
        print("!! GITHUB_TOKEN tidak ada"); return 1
    OWNER = "vraafi@verify.test"
    OWNER2 = "orang-lain@verify.test"
    RUN = f"verify-{int(time.time()) % 100000}"

    # --- 1. GitHub NYATA: connect -----------------------------------------
    client = sc.GitHubClient(TOKEN, args.repo)
    user = client.call("GET", "/user")
    rate = client.call("GET", "/rate_limit")
    cabang = client.list_branches()
    lulus = (user.get("login") == "vraafi" and "main" in cabang
             and rate.get("rate", {}).get("limit", 0) > 0)
    _catat(1, "GitHub NYATA: connect (PAT asli) + daftar cabang", lulus,
           f"repo        = {args.repo}\n"
           f"GET /user   -> login={user.get('login')} id={user.get('id')}\n"
           f"rate_limit  -> core {rate.get('rate', {}).get('limit')} / "
           f"sisa {rate.get('rate', {}).get('remaining')}\n"
           f"branches    = {cabang}\n"
           f"CEK: PAT sah + repo terbaca -> {lulus}",
           {"login": user.get("login"), "branches": cabang})

    # --- 2. Commit -> verifikasi ULANG di GitHub --------------------------
    s = sc.SourceControl(client)
    wf = f"{RUN}-wf"
    flow = {"nodes": [{"id": "n1", "type": "trigger"}], "edges": [], "run": RUN}
    c1 = s.commit_workflow(wf, flow, branch="main", message=f"verify commit {RUN}")
    # baca ULANG lewat API (bukan dari memori) -> bukti benar-benar tersimpan
    konten, sha_remote = client.read_file(sc.workflow_path(wf), "main")
    pulih = sc.deserialize_workflow(konten)  # -> flow_data (dict dalam)
    lulus = (c1["sha"] and pulih.get("run") == RUN and sha_remote)
    _catat(2, "Commit -> terverifikasi ULANG di GitHub (baca balik API)", lulus,
           f"commit sha  = {c1['sha']}\n"
           f"path        = {sc.workflow_path(wf)}\n"
           f"created     = {c1['created']}\n"
           f"read_file() -> sha={sha_remote[:12]}…  run={pulih.get('run')}\n"
           f"CEK: isi di GitHub == yang dikirim -> {lulus}",
           {"sha": c1["sha"], "path": sc.workflow_path(wf)})
    commit_v1 = c1["sha"]

    # --- 3. Pull ----------------------------------------------------------
    out = s.pull_workflow(wf, "main")
    lulus = out["flow_data"].get("run") == RUN and out["sha"]
    _catat(3, "Pull: ambil workflow dari GitHub", lulus,
           f"pull_workflow('{wf}', 'main')\n"
           f"  sha       = {out['sha'][:12]}…\n"
           f"  flow_data = {json.dumps(out['flow_data'])[:160]}\n"
           f"CEK: isi cocok dengan yang di-commit -> {lulus}",
           {"sha": out["sha"]})

    # --- 4. Rollback ke commit lama ---------------------------------------
    c2 = s.commit_workflow(wf, {**flow, "versi": 2}, branch="main",
                           message=f"verify v2 {RUN}")
    # rollback ke commit_v1 (isi tanpa "versi": 2)
    rb = s.rollback(wf, commit_v1, branch="main")
    setelah, _ = client.read_file(sc.workflow_path(wf), "main")
    data_rb = sc.deserialize_workflow(setelah)  # -> flow_data (dict dalam)
    lulus = (rb["sha"] and "versi" not in (data_rb or {}))
    _catat(4, "Rollback ke commit lama (isi kembali seperti semula)", lulus,
           f"commit v1   = {commit_v1[:12]}…\n"
           f"commit v2   = {c2['sha'][:12]}…  (flow_data memuat 'versi': 2)\n"
           f"rollback(to_sha=v1) -> commit baru {rb['sha'][:12]}…\n"
           f"isi main sekarang = {json.dumps(data_rb)[:140]}\n"
           f"CEK: 'versi' hilang lagi (isi v1 dipulihkan) -> {lulus}",
           {"rollback_sha": rb["sha"]})

    # --- 5. Branch + push --------------------------------------------------
    br = f"feature/{RUN}"
    s.create_branch(br, "main")
    c3 = s.commit_workflow(wf, {**flow, "cabang": br}, branch=br,
                           message=f"verify di cabang {RUN}")
    isi_cabang, _ = client.read_file(sc.workflow_path(wf), br)
    daftar = client.list_branches()
    data_cabang = sc.deserialize_workflow(isi_cabang)  # -> flow_data (dict dalam)
    lulus = (br in daftar and c3["sha"] and data_cabang.get("cabang") == br)
    _catat(5, "Branch baru + push (terpisah dari main)", lulus,
           f"create_branch('{br}', from='main')\n"
           f"commit di cabang -> {c3['sha'][:12]}…\n"
           f"branches sekarang = {daftar}\n"
           f"isi di cabang     = {json.dumps(data_cabang)[:140]}\n"
           f"CEK: cabang ada & isinya beda dari main -> {lulus}",
           {"branch": br, "branches": daftar})

    # --- 6. Pull Request ---------------------------------------------------
    pr = s.open_pr(br, "main", f"Verify PR {RUN}", "PR otomatis dari hard test")
    detail_pr = client.call("GET", f"/repos/{args.repo}/pulls/{pr['number']}")
    lulus = (pr["number"] and detail_pr.get("state") == "open"
             and detail_pr.get("head", {}).get("ref") == br)
    _catat(6, "Pull Request: buka PR nyata + verifikasi di GitHub", lulus,
           f"open_pr(head='{br}', base='main')\n"
           f"  number = {pr['number']}  state = {pr['state']}\n"
           f"GET /pulls/{pr['number']} -> state={detail_pr.get('state')} "
           f"head={detail_pr.get('head', {}).get('ref')} "
           f"base={detail_pr.get('base', {}).get('ref')}\n"
           f"url    = {detail_pr.get('html_url')}\n"
           f"CEK: PR benar-benar ada di GitHub -> {lulus}",
           {"pr": pr["number"], "url": detail_pr.get("html_url")})

    # --- 7. Konflik 2 commit bersamaan (expect_sha kedaluwarsa) -----------
    wf2 = f"{RUN}-konflik"
    s.commit_workflow(wf2, {"a": 1}, branch="main", message="konflik dasar")
    _, sha_lama = client.read_file(sc.workflow_path(wf2), "main")
    # "proses A" commit lebih dulu
    s.commit_workflow(wf2, {"a": 2}, branch="main", message="proses A menang")
    # "proses B" masih memegang sha LAMA -> harus DITOLAK
    jenis, pesan = None, None
    try:
        s.commit_workflow(wf2, {"a": 3}, branch="main", message="proses B (basi)",
                          expect_sha=sha_lama)
    except Exception as exc:  # noqa: BLE001
        jenis, pesan = type(exc).__name__, str(exc)
    lulus = jenis == "ConflictError" and pesan and "konflik" in pesan.lower()
    _catat(7, "Konflik: 2 commit bersamaan -> yang basi DITOLAK (HTTP 409)", lulus,
           f"sha dasar (dibaca proses B) = {sha_lama[:12]}…\n"
           f"proses A commit dulu        -> sukses\n"
           f"proses B commit expect_sha  -> RAISES {jenis}: {pesan}\n"
           f"CEK: penulisan basi terdeteksi sebagai konflik -> {lulus}",
           {"error": jenis})

    # --- 8. Webhook push -> auto sync -------------------------------------
    payload = {
        "ref": "refs/heads/main",
        "commits": [
            {"added": [f"workflows/{RUN}-baru.json"], "modified": [],
             "removed": []},
            {"added": [], "modified": [f"workflows/{RUN}-wf.json"],
             "removed": [f"workflows/{RUN}-hapus.json"]},
            {"added": ["README.md", "src/lain.py"], "modified": [], "removed": []},
        ],
    }
    sync = s.sync_from_webhook(payload)
    lulus = (sync["branch"] == "main" and sync["count"] == 3
             and f"{RUN}-baru" in sync["workflow_ids"]
             and f"{RUN}-hapus" in sync["workflow_ids"]
             and "src/lain" not in " ".join(sync["workflow_ids"]))
    _catat(8, "Webhook push GitHub -> auto-sync daftar workflow", lulus,
           f"payload.ref = {payload['ref']}\n"
           f"3 commit, 5 berkas (3 .json workflow + README + src/lain.py)\n"
           f"hasil sync  = {json.dumps(sync)}\n"
           f"CEK: hanya berkas workflows/*.json yang diambil -> {lulus}",
           sync)

    # --- 9. Multi-user: koneksi terpisah ----------------------------------
    store = sc.ConnectionStore()
    store.save(OWNER, "github", args.repo, TOKEN)
    store.save(OWNER2, "github", "orang-lain/repo-pribadi", "ghp_palsu_orang_lain")
    li_budi = store.list(OWNER)
    li_orang = store.list(OWNER2)
    klien_orang = store.client(OWNER2, "github")
    lulus = (len(li_budi) == 1 and len(li_orang) == 1
             and li_budi[0]["repo"] == args.repo
             and klien_orang.repo == "orang-lain/repo-pribadi"
             and TOKEN not in json.dumps(li_budi))
    _catat(9, "Multi-user: koneksi & token terpisah per user", lulus,
           f"store.list(budi)  = {json.dumps(li_budi)}\n"
           f"store.list(orang) = {json.dumps(li_orang)}\n"
           f"store.client(orang).repo = {klien_orang.repo}\n"
           f"token asli muncul di list? {TOKEN in json.dumps(li_budi)} (harus False)\n"
           f"CEK: tidak ada kebocoran lintas-user -> {lulus}",
           {"budi": li_budi, "orang": li_orang})

    # --- 10. Token DIENKRIPSI saat disimpan --------------------------------
    rec = store._d[(OWNER, "github")]["enc"]
    lulus = (rec.startswith("gAAAAA") and TOKEN not in rec
             and store.get(OWNER, "github")["token"] == TOKEN)
    _catat(10, "Token DIENKRIPSI di penyimpanan (Fernet), dekripsi benar", lulus,
           f"ciphertext di store = {rec[:40]}… ({len(rec)} char)\n"
           f"token asli ada di cipher? {TOKEN in rec}  (harus False)\n"
           f"prefix Fernet        = {rec.startswith('gAAAAA')}\n"
           f"store.get()          = token panjang {len(store.get(OWNER,'github')['token'])} (cocok)\n"
           f"CEK: at-rest terenkripsi, in-use terdekripsi -> {lulus}",
           {"enc_prefix": rec[:8]})

    # --- 11. Performa: 100 commit ------------------------------------------
    wf3 = f"{RUN}-perf"
    t0 = time.time()
    sha_terakhir = ""
    for i in range(100):
        r = s.commit_workflow(wf3, {"i": i}, branch="main",
                              message=f"perf {i} {RUN}")
        sha_terakhir = r["sha"]
    durasi = time.time() - t0
    # verifikasi jumlah commit di GitHub untuk path itu
    hist = client.call("GET", f"/repos/{args.repo}/commits?path="
                              f"{sc.workflow_path(wf3)}&per_page=100")
    lulus = (durasi < 300 and sha_terakhir and len(hist) >= 100)
    _catat(11, "Performa: 100 commit nyata ke GitHub", lulus,
           f"100 commit ke {sc.workflow_path(wf3)}\n"
           f"durasi      = {durasi:.1f}s ({durasi/100*1000:.0f} ms/commit)\n"
           f"sha akhir   = {sha_terakhir[:12]}…\n"
           f"GET /commits?path=… -> {len(hist)} commit terdaftar di GitHub\n"
           f"CEK: semua commit benar-benar tercatat -> {lulus}",
           {"seconds": round(durasi, 1), "commits": len(hist)})

    # --- 12. Token SALAH -> pesan galat JELAS ------------------------------
    buruk = sc.GitHubClient("ghp_token_palsu_tidak_valid_000000000000", args.repo)
    jenis, pesan = None, None
    try:
        buruk.list_branches()
    except Exception as exc:  # noqa: BLE001
        jenis, pesan = type(exc).__name__, str(exc)
    lulus = (jenis in ("GitError", "NotFoundError") and pesan
             and "401" in pesan and "ghp_token_palsu" not in pesan)
    _catat(12, "Token SALAH -> galat JELAS (401, token tidak bocor)", lulus,
           f"token   = ghp_token_palsu_… (sengaja salah)\n"
           f"list_branches() -> RAISES {jenis}: {pesan}\n"
           f"token muncul di pesan? {'ghp_token_palsu' in (pesan or '')} (harus False)\n"
           f"CEK: 401 terklasifikasi + rahasia tidak bocor -> {lulus}",
           {"error": jenis, "message": pesan})

    lulus_n = sum(1 for h in HASIL if h["status"] == "PASS")
    print("=" * 78)
    print(f"RINGKASAN HARD TEST FITUR #5: {lulus_n}/{len(HASIL)} PASS")
    print("=" * 78)
    for h in HASIL:
        print(f"  #{h['no']:02d} [{h['status']}] {h['skenario']}")

    if args.json:
        out = os.path.join(HERE, args.json) if not os.path.isabs(args.json) else args.json
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({"feature": "#5 Source Control Git", "repo": args.repo,
                       "lulus": lulus_n, "total": len(HASIL), "hasil": HASIL},
                      fh, indent=2, ensure_ascii=False)
        print(f"\nJSON -> {args.json}")
    return 0 if lulus_n == len(HASIL) else 1


if __name__ == "__main__":
    raise SystemExit(main())
