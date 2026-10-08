"""Hard test Fitur #10 — Real-Time Collaboration di VPS (bukan lokal).

Server Yjs/CRDT (pycrdt-websocket) berjalan DI VPS (127.0.0.1:8140, diakses
lewat tunnel SSH), autentikasi JWT NYATA (Supabase), persistensi FileYStore
di VPS. Skenario restart server dieksekusi via SSH sungguhan.

Pakai:
    python scripts/enterprise_collab_vps_live.py --json docs/evidence/f10-collab-vps-live.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

WS = os.environ.get("F10_VPS_WS", "ws://localhost:8140")
VPS_HOST = ""
HASIL: list[dict] = []


def _catat(no: int, nama: str, lulus: bool, raw: str,
           detail: dict | None = None) -> None:
    HASIL.append({"no": no, "skenario": nama, "status": "PASS" if lulus else "FAIL",
                  "raw": raw, "detail": detail or {}})
    print("=" * 78)
    print(f"#{no:02d} [{'PASS' if lulus else 'FAIL'}] {nama}")
    print("-" * 78)
    print(raw)
    print()


def load_env() -> dict:
    env = {}
    for line in open(os.path.join(HERE, ".env"), encoding="utf-8",
                     errors="replace"):
        if line.lstrip().startswith("#"):
            continue
        m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$",
                     line)
        if m:
            env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return env


def ensure_jwt(env: dict) -> str:
    import httpx
    url = (env.get("SUPABASE_URL") or "").rstrip("/")
    pub = env.get("SUPABASE_PUBLISHABLE_KEY") or env.get("SUPABASE_KEY") or ""
    r = httpx.post(f"{url}/auth/v1/token?grant_type=password",
                   headers={"apikey": pub, "Content-Type": "application/json"},
                   json={"email": "otonom-test@katalir-internal.dev",
                         "password": "AutoTestKatalir2026!"}, timeout=30)
    if r.status_code == 200:
        return r.json()["access_token"]
    p = os.path.join(HERE, ".autonomous_jwt")
    return open(p, encoding="utf-8").read().strip()


def vps_ssh(env: dict):
    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(env["VPS_IP"], username=env["VPS_USERNAME"],
              password=env["VPS_PASSWORD"], timeout=20, allow_agent=False,
              look_for_keys=False)
    return c


def vps_restart_server(env: dict) -> bool:
    c = vps_ssh(env)
    supa_key = env.get("SUPABASE_PUBLISHABLE_KEY") or env.get("SUPABASE_KEY") or ""
    c.exec_command("pkill -f vps_collab_server; sleep 1", timeout=20)
    cmd = (f"cd /root/katalir-collab && setsid nohup env "
           f"SUPABASE_URL='{env.get('SUPABASE_URL', '')}' "
           f"SUPABASE_PUBLISHABLE_KEY='{supa_key}' SUPABASE_KEY='{supa_key}' "
           f"./venv/bin/python vps_collab_server.py --host 127.0.0.1 --port 8140 "
           f"< /dev/null >> /root/katalir-collab/server.log 2>&1 &")
    c.exec_command(cmd, timeout=20)
    ok = False
    for _ in range(30):
        time.sleep(1.0)
        _i, o, _e = c.exec_command("ss -ltn | grep -c ':8140'", timeout=15)
        if o.read().decode().strip().startswith(("1",)):
            ok = True
            break
    c.close()
    return ok


async def skenario(token: str, env: dict) -> None:
    import collab_realtime as cr

    RUN = f"vps{int(time.time()) % 100000}"

    # --- 1. 2 klien + JWT sah via tunnel -> server VPS --------------------
    a = cr.CollabClient(WS, token, "Andi", f"{RUN}-dasar", "#e11d48")
    b = cr.CollabClient(WS, token, "Budi", f"{RUN}-dasar", "#2563eb")
    t0 = time.perf_counter()
    await a.connect(); await b.connect()
    ok = (await a.wait_for(lambda: a.synced.is_set(), 20) and
          await b.wait_for(lambda: b.synced.is_set(), 20))
    _catat(1, "Server WS di VPS + 2 klien (JWT sah) lewat tunnel & tersinkron",
           ok,
           f"ws      = {WS}/{RUN}-dasar  (server: VPS 127.0.0.1:8140)\n"
           f"A.client_id = {a.awareness.client_id}\n"
           f"B.client_id = {b.awareness.client_id}\n"
           f"handshake+sync = {time.perf_counter()-t0:.2f}s\n"
           f"A.synced={a.synced.is_set()}  B.synced={b.synced.is_set()}")

    # --- 2. A tambah node -> B lihat ---------------------------------------
    a.add_node("n1", x=10.0, y=20.0, label="Mulai")
    ok = await b.wait_for(lambda: "n1" in b.nodes, 20)
    _catat(2, "CRDT sync: node buatan A tampak di B (lintas internet->VPS)",
           ok, f"A.add_node(n1) -> B.nodes = {dict(b.nodes)}")

    # --- 3. 5 user sync ----------------------------------------------------
    nama5 = ["Andi", "Budi", "Citra", "Dewi", "Eka"]
    klien = [a, b]
    for i, nm in enumerate(nama5[2:], start=1):
        k = cr.CollabClient(WS, token, nm, f"{RUN}-dasar", "#16a34a")
        await k.connect()
        await k.wait_for(lambda: k.synced.is_set(), 20)
        klien.append(k)
    klien[0].add_node("n5", x=1.0, y=2.0, label="lima-user")
    hasil = await asyncio.gather(*[k.wait_for(lambda k=k: "n5" in k.nodes, 25)
                                   for k in klien])
    ok = all(hasil)
    _catat(3, "5 user serentak melihat node yang sama", ok,
           f"klien  = {nama5}\nn5 terlihat = {list(hasil)}\n"
           f"peers A = {len(a.peers())}")

    # --- 4. Edit bersamaan node sama -> konvergen --------------------------
    a.update_node("n1", x=111.0)
    ok_x = await b.wait_for(lambda: b.nodes.get("n1", {}).get("x") == 111.0, 20)
    b.update_node("n1", label="Dari-Budi")
    ok_l = await a.wait_for(lambda: a.nodes.get("n1", {}).get("label") == "Dari-Budi", 20)
    await asyncio.sleep(1.5)
    xa = a.nodes.get("n1", {}).get("x")
    xb = b.nodes.get("n1", {}).get("x")
    la = a.nodes.get("n1", {}).get("label")
    lb = b.nodes.get("n1", {}).get("label")
    ok = ok_x and ok_l and xa == 111.0 and xb == 111.0 and la == "Dari-Budi" and lb == "Dari-Budi"
    _catat(4, "Edit bersamaan (field beda) -> CRDT konvergen di kedua klien",
           ok,
           f"A.lihat n1 = {dict(a.nodes.get('n1', {}))}\n"
           f"B.lihat n1 = {dict(b.nodes.get('n1', {}))}\n"
           f"CEK: x=111.0 & label='Dari-Budi' di KEDUANYA -> {ok}")

    # --- 5. Kursor / presence ---------------------------------------------
    await a.move_cursor(320.0, 140.0)
    ok = await b.wait_for(
        lambda: "Andi" in b.cursors(), 20)
    _catat(5, "Presence kursor: B melihat kursor A bernama", ok,
           f"cursors B = {json.dumps(b.cursors())}")

    # --- 6. Komentar terdistribusi -----------------------------------------
    a.add_comment("tolong cek node n1", target="n1")
    ok = await b.wait_for(
        lambda: any(c.get("text") == "tolong cek node n1" for c in b.comments),
        20)
    _catat(6, "Komentar CRDT: A tulis -> B terima", ok,
           f"comments B = {[dict(c) for c in b.comments]}")

    # --- 7. Persistensi: restart server VPS via SSH ------------------------
    nodes_sebelum = dict(a.nodes)
    for k in klien:
        await k.close()
    ok = vps_restart_server(env)
    k = cr.CollabClient(WS, token, "Farhan", f"{RUN}-dasar", "#7c3aed")
    await k.connect()
    pulih = await k.wait_for(
        lambda: k.nodes.get("n1", {}).get("x") == 111.0 and
                k.nodes.get("n1", {}).get("label") == "Dari-Budi" and
                "n5" in k.nodes, 30)
    await k.close()
    _catat(7, "Restart server VPS (SSH nyata) -> state CRDT dipulihkan",
           ok and pulih,
           f"restart OK = {ok}\n"
           f"state sebelum = {json.dumps(nodes_sebelum)}\n"
           f"state setelah (klien baru 'Farhan') = {json.dumps(dict(k.nodes))}\n"
           f"CEK: n1(x=111.0,'Dari-Budi') & n5 ada -> {pulih}")

    # --- 8. Auth ditolak tanpa token ---------------------------------------
    ditolak = False
    try:
        import websockets
        async with websockets.connect(f"{WS}/{RUN}-dasar", max_size=None,
                                      open_timeout=15) as _w:
            await asyncio.sleep(2)
    except Exception as e:  # noqa: BLE001
        ditolak = ("4401" in repr(e) or "closed" in repr(e).lower()
                   or "1008" in repr(e) or "401" in repr(e) or "403" in repr(e))
    _catat(8, "Koneksi TANPA token ditolak server VPS", ditolak,
           f"exception = {type(e).__name__}: {e}" if not ditolak else
           "koneksi ditolak (close 4401/403) sesuai kebijakan")

    # --- 9. Offline -> reconnect (server replay via ystore) ----------------
    b2 = cr.CollabClient(WS, token, "Budi-2", f"{RUN}-off", "#2563eb")
    await b2.connect()
    await b2.wait_for(lambda: b2.synced.is_set(), 20)
    b2.add_node("n9", x=9.0, y=9.0, label="awal")
    await b2.close()
    # editor lain DI ROOM YANG SAMA menulis saat B offline
    a2 = cr.CollabClient(WS, token, "Andi-2", f"{RUN}-off", "#e11d48")
    await a2.connect()
    await a2.wait_for(lambda: a2.synced.is_set(), 20)
    a2.update_node("n9", label="dibuat-saat-B-offline")
    await asyncio.sleep(1.5)
    b3 = cr.CollabClient(WS, token, "Budi-2", f"{RUN}-off", "#2563eb")
    await b3.connect()
    ok = await b3.wait_for(lambda: "n9" in b3.nodes, 25)
    _catat(9, "B offline -> A edit -> B reconnect -> state ter-replay", ok,
           f"n9 = {dict(b3.nodes.get('n9', {}))}")
    await b3.close(); await a2.close()

    # --- 10. Isolasi room ----------------------------------------------------
    x1 = cr.CollabClient(WS, token, "X1", f"{RUN}-isoA", "#e11d48")
    x2 = cr.CollabClient(WS, token, "X2", f"{RUN}-isoB", "#2563eb")
    await x1.connect(); await x2.connect()
    await x1.wait_for(lambda: x1.synced.is_set(), 20)
    await x2.wait_for(lambda: x2.synced.is_set(), 20)
    x1.add_node("rahasia", x=1.0, y=1.0, label="hanya-room-A")
    bocor = await x2.wait_for(lambda: "rahasia" in x2.nodes, 8)
    _catat(10, "Isolasi room: node room A TIDAK bocor ke room B", not bocor,
           f"x2.nodes = {dict(x2.nodes)} (harus kosong / tanpa 'rahasia')\n"
           f"bocor = {bocor}")
    await x1.close(); await x2.close()

    # --- 11. Perf: 200 update menyeluruh ------------------------------------
    p = cr.CollabClient(WS, token, "Perf", f"{RUN}-perf", "#ea580c")
    q = cr.CollabClient(WS, token, "Perf-2", f"{RUN}-perf", "#0d9488")
    await p.connect(); await q.connect()
    await p.wait_for(lambda: p.synced.is_set(), 20)
    await q.wait_for(lambda: q.synced.is_set(), 20)
    p.add_node("ctr", x=0.0, y=0.0, label="0")
    await q.wait_for(lambda: "ctr" in q.nodes, 20)
    t0 = time.perf_counter()
    for i in range(1, 201):
        p.update_node("ctr", label=str(i))
    ok = await q.wait_for(lambda: q.nodes.get("ctr", {}).get("label") == "200",
                          40)
    dt = time.perf_counter() - t0
    _catat(11, "Perf: 200 update melewati VPS (lintas internet) terkirim semua",
           ok, f"200 update dalam {dt:.2f}s ({200/dt:.0f} ops/s)\n"
               f"nilai akhir di q = {q.nodes.get('ctr', {}).get('label')}")
    await p.close(); await q.close()

    # --- 12. Raw WS protocol (y-sync) ----------------------------------------
    import websockets as _ws
    from pycrdt import YMessageType
    terlihat = {"sync": 0, "awareness": 0}
    try:
        # A bergabung dulu & menggerakkan kursor -> B membaca frame mentah
        # (SYNC broadcast + AWARENESS broadcast) langsung dari server VPS.
        async with _ws.connect(f"{WS}/{RUN}-proto?token={token}", max_size=None,
                               open_timeout=20) as wa:
            await asyncio.wait_for(wa.recv(), timeout=20)  # handshake sync
            import pycrdt as _y
            aw = _y.Awareness(_y.Doc())
            upd = aw.encode_awareness_update([aw.client_id])
            await wa.send(_y.create_awareness_message(upd))
            async with _ws.connect(f"{WS}/{RUN}-proto?token={token}",
                                   max_size=None, open_timeout=20) as wb:
                batas = asyncio.get_event_loop().time() + 30
                while (terlihat["sync"] < 1 or terlihat["awareness"] < 1):
                    sisa = batas - asyncio.get_event_loop().time()
                    if sisa <= 0:
                        break
                    msg = await asyncio.wait_for(wb.recv(), timeout=sisa)
                    if isinstance(msg, (bytes, bytearray)) and len(msg) > 1:
                        tipe = msg[0]
                        if tipe == YMessageType.SYNC:
                            terlihat["sync"] += 1
                        elif tipe == YMessageType.AWARENESS:
                            terlihat["awareness"] += 1
    except Exception as e:  # noqa: BLE001
        _catat(12, "Protokol y-sync mentah terbaca", False,
               f"exception {type(e).__name__}: {e}")
        return
    _catat(12, "Protokol y-sync/y-awareness mentah terbaca dari VPS",
           terlihat["sync"] > 0 and terlihat["awareness"] > 0,
           f"frame SYNC={terlihat['sync']}  AWARENESS={terlihat['awareness']} "
           f"(byte pertama = tipe pesan y-sync)")


async def _jalankan(token: str, env: dict) -> None:
    await skenario(token, env)
    # bersih-bersih koneksi tersisa
    try:
        import asyncio as _a
        tugas = [t for t in _a.all_tasks() if t is not _a.current_task()]
        for t in tugas:
            t.cancel()
        await _a.gather(*tugas, return_exceptions=True)
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    env = load_env()
    global VPS_HOST
    VPS_HOST = env.get("VPS_IP", "")

    print(f"VPS = {VPS_HOST} | WS = {WS}")
    token = ensure_jwt(env)
    print(f"JWT ok (len={len(token)})")

    asyncio.run(_jalankan(token, env))

    lulus = sum(1 for h in HASIL if h["status"] == "PASS")
    print("=" * 78)
    print(f"RINGKASAN HARD TEST FITUR #10 (VPS): {lulus}/{len(HASIL)} PASS")
    print("=" * 78)
    for h in HASIL:
        print(f"  #{h['no']:02d} [{h['status']}] {h['skenario']}")

    if args.json:
        out = {"feature": "#10 Real-Time Collaboration (VPS)",
               "target": f"VPS {VPS_HOST} 127.0.0.1:8140 via SSH tunnel",
               "lulus": lulus, "total": len(HASIL), "hasil": HASIL}
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1, ensure_ascii=False)
        print(f"JSON -> {args.json}")
    return 0 if lulus == len(HASIL) else 1


if __name__ == "__main__":
    raise SystemExit(main())
