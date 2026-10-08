#!/usr/bin/env python
"""enterprise_collab_live.py — Hard test Fitur #10 (Real-Time Collaboration).

Menjalankan 12 skenario WAJIB terhadap **server WebSocket NYATA** (FastAPI +
pycrdt/ASGI, CRDT **Yjs**) memakai klien Python sungguhan yang berbicara
protokol y-sync + y-awareness.

Pakai:
    python scripts/enterprise_collab_live.py
    python scripts/enterprise_collab_live.py --json docs/evidence/f10-collab-live.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv_loader import load_repo_env  # noqa: E402

load_repo_env()

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8131
HTTP = f"http://localhost:{PORT}"
WS = f"ws://localhost:{PORT}/collab/ws"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
HASIL: list[dict] = []
_PROCS: list[subprocess.Popen] = []


def _catat(no: int, nama: str, lulus: bool, raw: str,
           detail: dict | None = None) -> None:
    HASIL.append({"no": no, "skenario": nama, "status": "PASS" if lulus else "FAIL",
                  "raw": raw, "detail": detail or {}})
    print("=" * 78)
    print(f"#{no:02d} [{'PASS' if lulus else 'FAIL'}] {nama}")
    print("-" * 78)
    print(raw)
    print()


# ---------------------------------------------------------------------------
# JWT + server lifecycle
# ---------------------------------------------------------------------------

def ensure_jwt() -> str:
    import httpx
    url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    pub = os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_KEY") or ""
    r = httpx.post(f"{url}/auth/v1/token?grant_type=password",
                   headers={"apikey": pub, "Content-Type": "application/json"},
                   json={"email": "otonom-test@katalir-internal.dev",
                         "password": "AutoTestKatalir2026!"}, timeout=30)
    if r.status_code == 200:
        tok = r.json()["access_token"]
        with open(os.path.join(HERE, ".autonomous_jwt"), "w",
                  encoding="utf-8") as fh:
            fh.write(tok)
        return tok
    return open(os.path.join(HERE, ".autonomous_jwt"),
                encoding="utf-8").read().strip()


def _wait_health(timeout: float = 60.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            OPENER.open(HTTP + "/health", timeout=3)
            return True
        except Exception:  # noqa: BLE001
            time.sleep(0.6)
    return False


def start_server() -> subprocess.Popen:
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["COLLAB_ENABLED"] = "1"
    env["QUEUE_WORKERS"] = "0"
    log = open(os.path.join(HERE, "docs", "evidence",
                            f"f10-server-{len(_PROCS)}.log"), "w", encoding="utf-8")
    p = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api_server:app", "--host", "127.0.0.1",
         "--port", str(PORT), "--log-level", "warning"],
        cwd=HERE, env=env, stdout=log, stderr=subprocess.STDOUT)
    _PROCS.append(p)
    _wait_health()
    return p


def stop_server(p: subprocess.Popen) -> None:
    try:
        p.terminate()
        p.wait(timeout=20)
    except Exception:  # noqa: BLE001
        try:
            p.kill()
        except Exception:  # noqa: BLE001
            pass


def _rest(path: str, token: str, body: dict | None = None) -> tuple[int, str]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        HTTP + path, data=data, method="POST" if data else "GET",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json",
                 **({"Content-Type": "application/json"} if data else {})})
    try:
        r = OPENER.open(req, timeout=30)
        return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:  # noqa: BLE001
        return 0, repr(e)


# ---------------------------------------------------------------------------
# Skenario
# ---------------------------------------------------------------------------

async def skenario(token: str) -> None:
    import collab_realtime as cr

    RUN = f"r{int(time.time()) % 100000}"

    # --- 1. Server + connect 2 klien (JWT sah) ----------------------------
    a = cr.CollabClient(WS, token, "Andi", f"{RUN}-dasar", "#e11d48")
    b = cr.CollabClient(WS, token, "Budi", f"{RUN}-dasar", "#2563eb")
    await a.connect(); await b.connect()
    ok_sync = await a.wait_for(lambda: a.synced.is_set(), 10) and \
        await b.wait_for(lambda: b.synced.is_set(), 10)
    lulus = ok_sync
    _catat(1, "Server WS NYATA + 2 klien terhubung (JWT sah) & tersinkron",
           lulus,
           f"ws      = {WS}/{RUN}-dasar\n"
           f"A.client_id = {a.awareness.client_id}\n"
           f"B.client_id = {b.awareness.client_id}\n"
           f"A.synced={a.synced.is_set()}  B.synced={b.synced.is_set()}\n"
           f"CEK: handshake + sync-step selesai -> {lulus}",
           {"a": a.awareness.client_id, "b": b.awareness.client_id})

    # --- 2. Sinkron 2 user: A tambah node -> B melihat --------------------
    a.add_node("n1", x=10, y=20, label="Mulai")
    ok = await b.wait_for(lambda: "n1" in b.nodes, 10)
    lulus = ok and dict(b.nodes.get("n1") or {}).get("label") == "Mulai"
    _catat(2, "Sinkron 2 user: A tambah node -> B melihatnya", lulus,
           f"A: nodes={{'n1': {{'x':10,'y':20,'label':'Mulai'}}}}\n"
           f"B.nodes setelah propagasi = {dict(b.nodes)}\n"
           f"CEK: node A muncul di dokumen CRDT B -> {lulus}",
           {"b_nodes": list(b.nodes.keys())})

    # --- 3. Sinkron 5 user -> semua konvergen -----------------------------
    room5 = f"{RUN}-lima"
    klien = [cr.CollabClient(WS, token, f"U{i}", room5, "#22c55e")
             for i in range(1, 6)]
    for c in klien:
        await c.connect()
    klien[0].add_node("shared", label="dari-U1")
    klien[1].add_node("milik-U2", label="dari-U2")
    konvergen = all([await c.wait_for(
        lambda c=c: "shared" in c.nodes and "milik-U2" in c.nodes, 12)
        for c in klien])
    snaps = [json.dumps(c.snapshot()["nodes"], sort_keys=True) for c in klien]
    lulus = konvergen and len(set(snaps)) == 1
    _catat(3, "Sinkron 5 user: semua konvergen ke dokumen identik", lulus,
           f"5 klien di room {room5}\n"
           f"U1 tambah 'shared', U2 tambah 'milik-U2'\n"
           f"jumlah node tiap klien = {[len(c.nodes) for c in klien]}\n"
           f"snapshot identik (hash sama) = {len(set(snaps)) == 1}\n"
           f"CEK: konvergensi CRDT penuh -> {lulus}",
           {"nodes": len(klien[0].nodes)})

    # --- 4. Edit bersamaan (node berbeda) -> merge ------------------------
    room4 = f"{RUN}-merge"
    x = cr.CollabClient(WS, token, "X", room4, "#f59e0b")
    y = cr.CollabClient(WS, token, "Y", room4, "#8b5cf6")
    await x.connect(); await y.connect()
    await x.wait_for(lambda: x.synced.is_set(), 8)
    await y.wait_for(lambda: y.synced.is_set(), 8)
    x.add_node("nx", label="X")
    y.add_node("ny", label="Y")
    okx = await x.wait_for(lambda: "ny" in x.nodes, 10)
    oky = await y.wait_for(lambda: "nx" in y.nodes, 10)
    lulus = okx and oky and set(x.nodes.keys()) == set(y.nodes.keys()) == {"nx", "ny"}
    _catat(4, "Edit BERSAMAAN (node berbeda) -> kedua node ter-merge", lulus,
           f"X menambah 'nx', Y menambah 'ny' (tanpa koordinasi)\n"
           f"X.nodes = {sorted(x.nodes.keys())}\n"
           f"Y.nodes = {sorted(y.nodes.keys())}\n"
           f"CEK: tidak ada yang hilang (merge CRDT) -> {lulus}",
           {"x": sorted(x.nodes.keys()), "y": sorted(y.nodes.keys())})

    # --- 5. Tulisan BERSAMAAN pada field sama -> konvergen deterministik ---
    room5b = f"{RUN}-lww"
    p = cr.CollabClient(WS, token, "P", room5b, "#06b6d4")
    q = cr.CollabClient(WS, token, "Q", room5b, "#ef4444")
    await p.connect(); await q.connect()
    await p.wait_for(lambda: p.synced.is_set(), 8)
    await q.wait_for(lambda: q.synced.is_set(), 8)
    p.add_node("n", label="dasar"); await q.wait_for(lambda: "n" in q.nodes, 8)
    # keduanya menulis field 'label' nyaris bersamaan
    p.update_node("n", label="dari-P")
    q.update_node("n", label="dari-Q")
    await p.wait_for(lambda: dict(p.nodes["n"]).get("label") in ("dari-P", "dari-Q"), 8)
    await q.wait_for(lambda: dict(q.nodes["n"]).get("label") in ("dari-P", "dari-Q"), 8)
    await asyncio.sleep(1.0)
    lp = dict(p.nodes["n"]).get("label")
    lq = dict(q.nodes["n"]).get("label")
    lulus = lp == lq and lp in ("dari-P", "dari-Q")
    _catat(5, "Tulisan BERSAMAAN field sama -> konvergen deterministik", lulus,
           f"P set label='dari-P', Q set label='dari-Q' (bersamaan)\n"
           f"P.label = {lp!r}\n"
           f"Q.label = {lq!r}\n"
           f"CEK: kedua klien setuju pada nilai yang sama -> {lulus}",
           {"p": lp, "q": lq})

    # --- 6. Multi-kursor: A geser kursor -> B lihat nama+kursor -----------
    await a.move_cursor(120, 240, node="n1")
    ok = await b.wait_for(lambda: bool(b.cursors().get("Andi", {}).get("x")), 10)
    cur = b.cursors().get("Andi", {})
    lulus = ok and cur.get("x") == 120 and cur.get("y") == 240
    _catat(6, "Multi-kursor: A geser kursor -> B melihat kursor + nama", lulus,
           f"A.move_cursor(x=120, y=240, node='n1')\n"
           f"B.cursors() = {json.dumps(b.cursors())}\n"
           f"CEK: nama 'Andi' + posisi kursor sampai ke B -> {lulus}",
           {"cursor": cur})

    # --- 7. Presence 5 user: tiap klien lihat 4 rekan ---------------------
    await klien[0].move_cursor(1, 1)
    await klien[1].move_cursor(2, 2)
    await klien[2].move_cursor(3, 3)
    await klien[3].move_cursor(4, 4)
    await klien[4].move_cursor(5, 5)
    peers_ok = all([await c.wait_for(lambda c=c: len(c.peers()) >= 4, 12)
                    for c in klien])
    jumlah = [len(c.peers()) for c in klien]
    nama_terlihat = sorted({p["user"]["name"] for p in klien[0].peers()})
    lulus = peers_ok and all(n == 4 for n in jumlah)
    _catat(7, "Presence 5 user: tiap klien melihat 4 rekan + nama", lulus,
           f"jumlah rekan dilihat tiap klien = {jumlah}\n"
           f"nama yang dilihat U1 = {nama_terlihat}\n"
           f"CEK: awareness penuh (5-1=4) -> {lulus}",
           {"peers": jumlah, "names": nama_terlihat})

    # --- 8. Komentar -> terdistribusi + tersimpan di REST -----------------
    a.add_comment("tolong cek node n1", target="n1")
    ok = await b.wait_for(lambda: any("cek node n1" in dict(c).get("text", "")
                                      for c in b.comments), 10)
    st, body = _rest(f"/collab/rooms/{RUN}-dasar", token)
    rest_ok = st == 200 and "cek node n1" in body
    lulus = ok and rest_ok
    _catat(8, "Komentar: A tulis -> B lihat & tersimpan di snapshot REST", lulus,
           f"A.add_comment('tolong cek node n1', target='n1')\n"
           f"B.comments = {[dict(c) for c in b.comments]}\n"
           f"GET /collab/rooms/{RUN}-dasar -> HTTP {st}\n"
           f"  {body[:200]}\n"
           f"CEK: komentar terdistribusi + persist di server -> {lulus}",
           {"rest_status": st})

    # --- 9. Persistensi CRDT lintas restart server ------------------------
    room9 = f"{RUN}-persist"
    c9 = cr.CollabClient(WS, token, "Persist", room9, "#0ea5e9")
    await c9.connect()
    await c9.wait_for(lambda: c9.synced.is_set(), 8)
    c9.add_node("tahan", label="harus-selamat")
    await asyncio.sleep(1.5)   # beri waktu FileYStore menulis
    store_file = cr.WS_SERVER.store_path(room9)
    ada_file = os.path.exists(store_file) and os.path.getsize(store_file) > 0
    await c9.close()
    for c in klien + [a, b, x, y, p, q]:
        try:
            await c.close()
        except Exception:  # noqa: BLE001
            pass
    await asyncio.sleep(0.5)
    # restart server (proses BARU, memori kosong)
    stop_server(_PROCS[0])
    start_server()
    c9b = cr.CollabClient(WS, token, "Persist2", room9, "#0ea5e9")
    await c9b.connect()
    await c9b.wait_for(lambda: c9b.synced.is_set(), 10)
    ok = await c9b.wait_for(lambda: "tahan" in c9b.nodes, 10)
    lulus = ada_file and ok and \
        dict(c9b.nodes.get("tahan") or {}).get("label") == "harus-selamat"
    _catat(9, "Persistensi CRDT: state bertahan setelah RESTART server", lulus,
           f"FileYStore = {os.path.basename(store_file)} "
           f"({os.path.getsize(store_file) if ada_file else 0} byte)\n"
           f"server di-restart (proses BARU, memori kosong)\n"
           f"klien baru baca nodes = {dict(c9b.nodes)}\n"
           f"CEK: dokumen dipulihkan dari disk -> {lulus}",
           {"file_bytes": os.path.getsize(store_file) if ada_file else 0})
    await c9b.close()

    # --- 10. Koneksi tanpa token / token salah -> DITOLAK -----------------
    import websockets
    hasil_tolak = {}
    for label, tk in (("tanpa-token", ""), ("token-palsu", "eyJhbGciOiJIUzI1NiJ9.bogus.bogus")):
        url = f"{WS}/{RUN}-tolak" + (f"?token={tk}" if tk else "")
        try:
            ws = await websockets.connect(url, open_timeout=6)
            await ws.close()
            hasil_tolak[label] = "DITERIMA (BURUK)"
        except Exception as exc:  # noqa: BLE001
            hasil_tolak[label] = f"ditolak: {type(exc).__name__}"
    lulus = all("ditolak" in v for v in hasil_tolak.values())
    _catat(10, "Keamanan: koneksi tanpa/ dengan token palsu DITOLAK", lulus,
           "\n".join(f"  {k}: {v}" for k, v in hasil_tolak.items()) +
           f"\nCEK: tidak ada koneksi anonim -> {lulus}",
           hasil_tolak)

    # --- 11. Edit OFFLINE lalu reconnect -> ter-merge ---------------------
    room11 = f"{RUN}-offline"
    o1 = cr.CollabClient(WS, token, "O1", room11, "#84cc16")
    o2 = cr.CollabClient(WS, token, "O2", room11, "#a855f7")
    await o1.connect(); await o2.connect()
    await o1.wait_for(lambda: o1.synced.is_set(), 8)
    await o2.wait_for(lambda: o2.synced.is_set(), 8)
    o1.add_node("awal", label="bibit")
    await o2.wait_for(lambda: "awal" in o2.nodes, 8)
    # O2 "offline": putuskan, edit lokal, lalu sambung lagi
    await o2.close()
    o2.add_node("saat-offline", label="dibuat-offline")
    o1.add_node("saat-o1-online", label="dibuat-o1")
    await o2.connect()
    ok = await o1.wait_for(lambda: "saat-offline" in o1.nodes, 12) and \
        await o2.wait_for(lambda: "saat-o1-online" in o2.nodes, 12)
    lulus = ok and set(o1.nodes.keys()) == set(o2.nodes.keys())
    _catat(11, "Edit OFFLINE lalu reconnect -> ter-merge (tanpa kehilangan)", lulus,
           f"O2 putus -> menambah 'saat-offline' (lokal)\n"
           f"O1 (online) menambah 'saat-o1-online'\n"
           f"O2 tersambung lagi -> O1.nodes = {sorted(o1.nodes.keys())}\n"
           f"                        O2.nodes = {sorted(o2.nodes.keys())}\n"
           f"CEK: kedua perubahan bertahan -> {lulus}",
           {"o1": sorted(o1.nodes.keys()), "o2": sorted(o2.nodes.keys())})
    await o1.close(); await o2.close()

    # --- 12. Performa: 200 op di 5 klien -> konvergen ---------------------
    room12 = f"{RUN}-perf"
    tim = [cr.CollabClient(WS, token, f"P{i}", room12, "#f97316")
           for i in range(5)]
    for c in tim:
        await c.connect()
    t0 = time.time()
    for i in range(200):
        tim[i % 5].add_node(f"p{i}", label=f"op-{i}", x=i)
    konvergen = all([await c.wait_for(lambda c=c: len(c.nodes) >= 200, 30)
                     for c in tim])
    durasi = time.time() - t0
    jumlah = [len(c.nodes) for c in tim]
    lulus = konvergen and len(set(jumlah)) == 1 and jumlah[0] >= 200 and durasi < 60
    _catat(12, "Performa: 200 op CRDT di 5 klien -> konvergen", lulus,
           f"200 add_node dibagi ke 5 klien\n"
           f"durasi            = {durasi:.2f}s\n"
           f"jumlah node/klien = {jumlah}\n"
           f"CEK: semua klien sepakat >= 200 node -> {lulus}",
           {"seconds": round(durasi, 2), "nodes": jumlah})
    for c in tim:
        await c.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    token = ensure_jwt()
    start_server()
    try:
        asyncio.run(skenario(token))
    finally:
        for p in list(_PROCS):
            stop_server(p)

    lulus_n = sum(1 for h in HASIL if h["status"] == "PASS")
    print("=" * 78)
    print(f"RINGKASAN HARD TEST FITUR #10: {lulus_n}/{len(HASIL)} PASS")
    print("=" * 78)
    for h in HASIL:
        print(f"  #{h['no']:02d} [{h['status']}] {h['skenario']}")
    if args.json:
        out = os.path.join(HERE, args.json) if not os.path.isabs(args.json) else args.json
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({"feature": "#10 Real-Time Collaboration", "lulus": lulus_n,
                       "total": len(HASIL), "hasil": HASIL},
                      fh, indent=2, ensure_ascii=False)
        print(f"\nJSON -> {args.json}")
    return 0 if lulus_n == len(HASIL) else 1


if __name__ == "__main__":
    raise SystemExit(main())
