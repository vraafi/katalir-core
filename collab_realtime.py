# collab_realtime.py — Fitur #10: Real-Time Collaboration (Okt 2026)
# ======================================================================
# Binding NYATA: server WebSocket (ASGI, di-mount ke FastAPI) + CRDT **Yjs**
# lewat `pycrdt` (implementasi Rust `yrs`). Klien (browser) memakai `yjs`
# sungguhan lewat protokol y-sync + y-awareness.
#
# RISET (Okt 2026):
#   - Yjs dipilih (21.989 bintang, 20,5 juta unduhan/bulan, rilis 2026-05-28)
#     karena awareness (kursor/presence) sudah jadi fitur kelas satu dan
#     provider WebSocket matang. Automerge (6.390 bintang) lebih cocok untuk
#     offline-first + riwayat penuh. Sumber:
#     https://zairalabs.ai/guide/compare/automerge-vs-yjs/ (diverifikasi 7 Okt 2026)
#   - Server: `pycrdt-websocket` 0.16.5 (rilis 20 Sep 2026, MIT, Project
#     Jupyter) menyediakan `ASGIServer` yang bisa di-mount ke FastAPI.
#     Sumber: https://pypi.org/project/pycrdt-websocket/
#
# KEAMANAN: setiap koneksi WAJIB membawa JWT Supabase yang sah
# (`?token=<jwt>` atau header Authorization). Nama room divalidasi ketat.
# ======================================================================

from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any, Optional
from urllib.parse import parse_qs

import pycrdt as y
from pycrdt import Awareness, Doc
from pycrdt.store import FileYStore, YDocNotFound
from pycrdt.websocket import ASGIServer, WebsocketServer
from pycrdt.websocket.yroom import YRoom

# ---------------------------------------------------------------------------
# Konfigurasi
# ---------------------------------------------------------------------------

STORE_DIR = os.getenv(
    "KATALIR_COLLAB_STORE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "collab"))

#: Nama room: 1–64 karakter aman (huruf/angka/._:-). Mencegah path traversal.
ROOM_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


def _safe_name(name: str) -> str:
    aman = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    aman = re.sub(r"^[._-]+", "", aman)      # buang awalan ./- (hindari "..")
    return aman or "room"


def room_from_path(path: str) -> str:
    """`/collab/ws/tim-alpha` (atau `/tim-alpha` setelah mount) -> `tim-alpha`."""
    nama = path.strip("/").split("/")[-1] if path.strip("/") else ""
    return nama


def valid_room(name: str) -> bool:
    return bool(ROOM_RE.match(name or ""))


# ---------------------------------------------------------------------------
# Server WebSocket persisten
# ---------------------------------------------------------------------------

class PersistentWebsocketServer(WebsocketServer):
    """`WebsocketServer` + persistensi CRDT per-room (`FileYStore`).

    `YRoom` bawaan tidak menerima `ystore`, jadi `get_room` di-override untuk
    memasang `FileYStore` sehingga setiap update CRDT tersimpan ke disk dan
    dipulihkan saat room dibuka lagi (tahan restart proses).
    """

    def __init__(self, store_dir: str = STORE_DIR, **kw: Any) -> None:
        super().__init__(**kw)
        self.store_dir = store_dir
        os.makedirs(store_dir, exist_ok=True)

    def store_path(self, name: str) -> str:
        return os.path.join(self.store_dir, _safe_name(name) + ".y")

    async def get_room(self, name: str) -> YRoom:
        if name not in self.rooms:
            store = FileYStore(self.store_path(name))
            room = YRoom(
                ready=self.rooms_ready,
                ystore=store,
                exception_handler=self.exception_handler,
                log=self.log,
            )
            # PULIHKAN state dari disk. `YRoom` hanya MENULIS update ke ystore;
            # pemulihan adalah tanggung jawab pemanggil (`BaseYStore.apply_updates`
            # tidak pernah dipanggil kerangka) — ini bug nyata yang ditemukan
            # hard test skenario #9.
            try:
                await store.apply_updates(room.ydoc)
            except YDocNotFound:
                pass
            self.rooms[name] = room
        room = self.rooms[name]
        await self.start_room(room)
        # Tunggu sampai observer dokumen TERPASANG. Tanpa ini ada balapan:
        # perubahan yang terjadi tepat setelah room dibuat bisa TERLEWAT
        # (tidak tersimpan ke ystore) karena `_watch_ready` dijadwalkan async.
        try:
            await asyncio.wait_for(room.ydoc_observed.wait(), timeout=5)
        except Exception:  # noqa: BLE001 - TimeoutError / pembatalan
            pass
        return room


WS_SERVER = PersistentWebsocketServer(rooms_ready=True, auto_clean_rooms=False)


# ---------------------------------------------------------------------------
# Autentikasi koneksi
# ---------------------------------------------------------------------------

def _extract_token(scope: dict) -> str:
    qs = (scope.get("query_string") or b"").decode("utf-8", "ignore")
    params = parse_qs(qs)
    tok = (params.get("token") or [""])[0]
    if tok:
        return tok
    for k, v in scope.get("headers") or []:
        if k == b"authorization":
            val = v.decode("utf-8", "ignore")
            if val.lower().startswith("bearer "):
                return val[7:].strip()
    return ""


def verify_token(token: str) -> Optional[dict]:
    """Verifikasi JWT via `security` (JWKS lokal, fallback jaringan)."""
    if not token:
        return None
    try:
        import security
        return security.get_current_user("Bearer " + token)
    except Exception:  # noqa: BLE001 - apa pun -> tolak
        return None


async def _on_connect(msg: dict, scope: dict) -> bool:
    """Return True -> TOLAK koneksi (tidak di-accept)."""
    if not valid_room(room_from_path(scope.get("path", ""))):
        return True
    token = _extract_token(scope)
    user = verify_token(token)
    if user is None:
        return True
    scope["katalir_user"] = user
    return False


class CollabASGIServer(ASGIServer):
    """`ASGIServer` + penolakan eksplisit (close 4401) untuk koneksi tak sah.

    `on_connect` bawaan hanya "tidak menerima" koneksi (klien menggantung
    sampai timeout). Kita kirim `websocket.close` lebih dulu supaya klien
    menerima sinyal tolak yang tegas dan cepat.
    """

    async def __call__(self, scope, receive, send):  # type: ignore[override]
        if scope.get("type") == "websocket":
            msg = await receive()
            if msg.get("type") == "websocket.connect":
                if await self._on_connect(msg, scope):
                    await send({"type": "websocket.close", "code": 4401})
                    return
                await send({"type": "websocket.accept"})

                async def guarded_send(message: dict) -> None:
                    """Kirim tanpa membunuh room.

                    BUG PRODUKSI (ditemukan hard test VPS): saat klien
                    terakhir sebuah room memutus koneksi, broadcast yroom
                    masih memanggil `send` -> uvicorn `ClientDisconnected`
                    -> exception merambat ke TaskGroup yroom -> TaskGroup
                    WebsocketServer ikut runtuh -> lifespan mati ->
                    SEMUA koneksi berikutnya gagal
                    ("The WebsocketServer is not running").
                    Solusi: telan galat kirim untuk klien yang sudah pergi;
                    pembersihan klien tetap lewat jalur `recv`
                    (websocket.disconnect).
                    """
                    try:
                        await send(message)
                    except Exception:  # noqa: BLE001
                        pass

                from pycrdt.websocket.asgi_server import ASGIWebsocket
                # Nama room = segmen terakhir path (BUKAN path penuh): Starlette
                # `mount()` TIDAK memotong prefix, jadi `scope["path"]` =
                # "/collab/ws/<room>". Tanpa normalisasi ini, kunci room jadi
                # path penuh dan lookup REST/persistensi jadi tidak konsisten.
                ws = ASGIWebsocket(receive, guarded_send,
                                   room_from_path(scope.get("path", "")),
                                   self._on_disconnect)
                await self._websocket_server.serve(ws)
                return
        await super().__call__(scope, receive, send)


ASGI = CollabASGIServer(WS_SERVER, on_connect=_on_connect)


# ---------------------------------------------------------------------------
# Klien Python (dipakai hard test + integrasi server-ke-server)
# ---------------------------------------------------------------------------

class CollabClient:
    """Klien Yjs (protokol y-sync + y-awareness) di atas `websockets`.

    Ini klien NYATA: ia mengirim state vector (SYNC_STEP1), menerapkan
    SYNC_STEP2/UPDATE ke `Doc` CRDT lokal, dan bertukar state awareness
    (kursor + identitas user) dengan server.
    """

    def __init__(self, base_url: str, token: str, name: str,
                 room: str, color: str = "#5b8cff") -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.name = name
        self.room = room
        self.color = color
        self.doc = Doc()
        self.awareness = Awareness(self.doc)
        self.nodes = self.doc.get("nodes", type=y.Map)
        self.comments = self.doc.get("comments", type=y.Array)
        self._ws: Any = None
        self._task: Optional[asyncio.Task] = None
        self._sub = None
        self.synced = asyncio.Event()
        self.updates_received = 0
        self.error: str = ""

    # -- lifecycle ---------------------------------------------------------
    @property
    def url(self) -> str:
        return f"{self.base_url}/{self.room}?token={self.token}"

    async def connect(self, timeout: float = 15.0) -> None:
        import websockets
        self._ws = await websockets.connect(self.url, max_size=None,
                                            open_timeout=timeout)
        self._sub = self.doc.observe(self._on_doc_change)
        # kirim state vector kita -> server balas state yang kita kurang
        await self._ws.send(y.create_sync_message(self.doc))
        self.awareness.set_local_state({
            "user": {"name": self.name, "color": self.color},
            "cursor": {},
        })
        await self.flush_awareness()
        self._task = asyncio.create_task(self._recv_loop())

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except BaseException:  # noqa: BLE001
                pass
        if self._sub is not None:
            try:
                self.doc.unobserve(self._sub)
            except Exception:  # noqa: BLE001
                pass
        if self._ws is not None:
            await self._ws.close()

    # -- protokol ----------------------------------------------------------
    async def _recv_loop(self) -> None:
        try:
            async for raw in self._ws:
                if not raw:
                    continue
                mtype = raw[0]
                if mtype == y.YMessageType.SYNC:
                    reply = y.handle_sync_message(raw[1:], self.doc)
                    if reply is not None:
                        await self._ws.send(reply)
                    self.synced.set()
                    self.updates_received += 1
                elif mtype == y.YMessageType.AWARENESS:
                    try:
                        self.awareness.apply_awareness_update(
                            y.read_message(raw[1:]), "remote")
                    except Exception:  # noqa: BLE001
                        pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - catat agar tak hilang diam-diam
            self.error = f"{type(exc).__name__}: {exc}"

    def _on_doc_change(self, event) -> None:
        if self._ws is None:
            return
        try:
            asyncio.get_running_loop().create_task(
                self._ws.send(y.create_update_message(event.update)))
        except RuntimeError:
            pass

    async def flush_awareness(self) -> None:
        upd = self.awareness.encode_awareness_update([self.awareness.client_id])
        await self._ws.send(y.create_awareness_message(upd))

    # -- operasi dokumen ---------------------------------------------------
    def add_node(self, node_id: str, **props: Any) -> None:
        self.nodes[node_id] = props

    def update_node(self, node_id: str, **props: Any) -> None:
        """Perbarui field node.

        CATATAN PENTING: `Map.get()` pycrdt mengembalikan SALINAN `dict`, jadi
        menulis `self.nodes.get(id)['field'] = v` TIDAK berpengaruh (bug nyata
        yang ditemukan hard test). Karena itu nilai node ditulis ULANG utuh
        (read-merge-write) -> perubahan benar-benar masuk ke CRDT.
        """
        cur = dict(self.nodes.get(node_id) or {})
        if not cur and node_id not in self.nodes:
            self.add_node(node_id, **props)
            return
        cur.update(props)
        self.nodes[node_id] = cur

    def remove_node(self, node_id: str) -> None:
        del self.nodes[node_id]

    def snapshot(self) -> dict:
        return {"nodes": {k: dict(v) for k, v in self.nodes.items()},
                "comments": [dict(c) for c in self.comments]}

    def add_comment(self, text: str, target: str = "") -> None:
        self.comments.append({"user": self.name, "text": text,
                              "target": target, "at": time.time()})

    async def move_cursor(self, x: float, y: float,
                          node: str = "") -> None:
        self.awareness.set_local_state({
            "user": {"name": self.name, "color": self.color},
            "cursor": {"x": x, "y": y, "node": node},
        })
        await self.flush_awareness()

    def peers(self) -> list[dict]:
        """Presence rekan (kecuali diri sendiri) dari state awareness."""
        out = []
        for cid, st in self.awareness.states.items():
            if cid == self.awareness.client_id:
                continue
            if not st:
                continue
            out.append({"client_id": cid, **st})
        return out

    def cursors(self) -> dict[str, dict]:
        return {p["user"]["name"]: p.get("cursor", {})
                for p in self.peers() if p.get("user")}

    async def wait_for(self, pred, timeout: float = 10.0,
                       interval: float = 0.05) -> bool:
        """Tunggu sinkronisasi lokal.

        ASYNC dengan sengaja: versi sinkron (`time.sleep`) akan MEMBLOKIR event
        loop sehingga task `_recv_loop` tidak pernah jalan dan klien tampak
        "tidak pernah sync" (bug nyata yang ditemukan hard test).
        """
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while loop.time() < end:
            if pred():
                return True
            await asyncio.sleep(interval)
        return pred()


# ---------------------------------------------------------------------------
# Metadata room untuk endpoint REST
# ---------------------------------------------------------------------------

def _find_room(server: WebsocketServer, name: str) -> Optional[YRoom]:
    """Cari room berdasarkan nama bersih (tahan kunci ber-prefix path)."""
    if name in server.rooms:
        return server.rooms[name]
    target = room_from_path(name)
    for key, room in server.rooms.items():
        if room_from_path(key) == target:
            return room
    return None


def room_view(server: WebsocketServer, name: str) -> dict:
    """Ringkasan room (dari state server) untuk UI/endpoint REST."""
    room = _find_room(server, name)
    if room is None:
        return {"room": room_from_path(name), "exists": False, "nodes": {},
                "comments": [], "presence": [], "clients": 0}
    doc = room.ydoc
    nodes = doc.get("nodes", type=y.Map)
    comments = doc.get("comments", type=y.Array)
    presence = []
    for cid, st in room.awareness.states.items():
        if st:
            presence.append({"client_id": cid, **st})
    return {
        "room": room_from_path(name), "exists": True,
        "nodes": {k: dict(v) for k, v in nodes.items()},
        "comments": [dict(c) for c in comments],
        "presence": presence,
        "clients": len(room.clients),
    }


def list_rooms(server: WebsocketServer) -> list[dict]:
    out = []
    for name, room in server.rooms.items():
        out.append({
            "room": room_from_path(name),
            "clients": len(room.clients),
            "presence": len([s for s in room.awareness.states.values() if s]),
            "nodes": len(room.ydoc.get("nodes", type=y.Map)),
        })
    return sorted(out, key=lambda r: r["room"])
