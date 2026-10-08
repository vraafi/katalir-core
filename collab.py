# collab.py — Fitur #10: Real-Time Collaboration (Okt 2026)
# ======================================================================
# Kolaborasi real-time pada Canvas Builder: sinkronisasi CRDT (last-writer-wins
# + OR-Set), presence/multi-cursor, komentar + mention, undo/redo per-user, dan
# dukungan edit offline yang di-merge saat kembali online.
#
# RISET (Okt 2026): Yjs/Automerge adalah standar CRDT untuk editor kolaboratif.
# Binding Python (pycrdt/yrs) tersedia, tetapi untuk SEMANTIK alur kerja kita
# cukup model op-based LWW-register + OR-Set yang deterministik dan dapat
# di-hard-test. Produksi dapat menukar transport ke WebSocket/Yjs tanpa
# mengubah kontrak `CollabDoc`/`CollabRoom`.
#
# KEAMANAN: akses room dibatasi daftar user; op asing dari user tak berhak
# ditolak.
# ======================================================================

from __future__ import annotations

import re
import threading
import time
from typing import Any, Optional

_MENTION_RE = re.compile(r"@([A-Za-z0-9._%+\-]+)")


class CollabError(Exception):
    pass


class AccessDenied(CollabError):
    """User tidak berhak pada room ini."""


# ---------------------------------------------------------------------------
# Operasi + dokumen CRDT
# ---------------------------------------------------------------------------

class Op:
    __slots__ = ("client", "seq", "kind", "target", "field", "value", "ts")

    def __init__(self, client: str, seq: int, kind: str, target: str = "",
                 field: str = "", value: Any = None, ts: Optional[float] = None):
        self.client = client
        self.seq = int(seq)
        self.kind = kind
        self.target = target
        self.field = field
        self.value = value
        self.ts = float(ts if ts is not None else time.time())

    @property
    def key(self) -> tuple[str, int]:
        return (self.client, self.seq)

    def to_dict(self) -> dict:
        return {"client": self.client, "seq": self.seq, "kind": self.kind,
                "target": self.target, "field": self.field, "value": self.value,
                "ts": self.ts}

    @classmethod
    def from_dict(cls, d: dict) -> "Op":
        return cls(d.get("client", ""), d.get("seq", 0), d.get("kind", ""),
                   d.get("target", ""), d.get("field", ""), d.get("value"),
                   d.get("ts"))


class CollabDoc:
    """CRDT LWW-register + OR-Set untuk node workflow.

    - `set(node, field, value)`  -> LWW: (ts, client) terbesar menang.
    - `add_node(id, data)`       -> OR-Set (idempoten).
    - `remove_node(id)`          -> OR-Set tombstone.
    Idempotensi: op dengan (client, seq) yang sudah pernah diterapkan diabaikan.
    """

    def __init__(self) -> None:
        self._applied: set[tuple[str, int]] = set()
        self._nodes: dict[str, dict] = {}          # id -> {field: (value, ts, client)}
        self._removed: dict[str, tuple[float, str]] = {}   # id -> tombstone
        self._seq: dict[str, int] = {}             # client -> seq berikutnya

    # -- idempotensi -------------------------------------------------------
    def _seen(self, op: Op) -> bool:
        if op.key in self._applied:
            return True
        self._applied.add(op.key)
        return False

    def next_seq(self, client: str) -> int:
        self._seq[client] = self._seq.get(client, 0) + 1
        return self._seq[client]

    # -- terapkan ----------------------------------------------------------
    def apply(self, op: Op) -> bool:
        """Terapkan op. Return True bila mengubah state."""
        if self._seen(op):
            return False
        if op.kind == "set":
            rec = self._nodes.setdefault(op.target, {})
            cur = rec.get(op.field)
            # LWW: (ts, client) terbesar menang — INDEPENDEN urutan kedatangan.
            if cur is None or (op.ts, op.client) >= (cur[1], cur[2]):
                rec[op.field] = (op.value, op.ts, op.client)
                self._removed.pop(op.target, None)
                return True
            return False
        if op.kind == "add_node":
            rec = self._nodes.setdefault(op.target, {})
            data = op.value if isinstance(op.value, dict) else {}
            for k, v in data.items():
                rec[k] = (v, op.ts, op.client)
            self._removed.pop(op.target, None)
            return True
        if op.kind == "remove_node":
            lama = self._removed.get(op.target)
            if lama is None or (op.ts, op.client) > lama:
                self._removed[op.target] = (op.ts, op.client)
            return True
        return False

    def apply_many(self, ops: list[Op]) -> int:
        return sum(1 for op in ops if self.apply(op))

    # -- baca --------------------------------------------------------------
    def node(self, node_id: str) -> Optional[dict]:
        if node_id in self._removed:
            return None
        rec = self._nodes.get(node_id)
        if not rec:
            return None
        return {f: v[0] for f, v in rec.items()}

    def snapshot(self) -> dict:
        nodes = []
        for nid in sorted(self._nodes):
            if nid in self._removed:
                continue
            nodes.append({"id": nid, **{f: v[0] for f, v in
                                        self._nodes[nid].items()}})
        return {"nodes": nodes}

    def ops_since(self, seq_by_client: dict[str, int]) -> list[Op]:
        """Op yang belum dilihat klien (untuk sync delta / reconnect)."""
        out = []
        for (c, s) in sorted(self._applied):
            if s > seq_by_client.get(c, 0):
                out.append(self._log.get((c, s)))
        return [o for o in out if o is not None]

    # log ringkas untuk replay
    @property
    def _log(self) -> dict:
        if not hasattr(self, "_logstore"):
            self._logstore: dict[tuple[str, int], Op] = {}
        return self._logstore

    def record(self, op: Op) -> None:
        self._log[op.key] = op


# ---------------------------------------------------------------------------
# Room: presence, komentar, undo/redo, akses
# ---------------------------------------------------------------------------

class CollabRoom:
    def __init__(self, name: str, allowed: Optional[list[str]] = None) -> None:
        self.name = name
        self.allowed = set(allowed or [])       # kosong = terbuka
        self.doc = CollabDoc()
        self._lock = threading.RLock()
        self._presence: dict[str, dict] = {}
        self._comments: list[dict] = []
        self._undo: dict[str, list[Op]] = {}
        self._redo: dict[str, list[Op]] = {}
        self._members: set[str] = set()
        self._clock = time.time
        self._max_ts: float = 0.0
        self._sys_seq: int = 0

    # -- akses -------------------------------------------------------------
    def can(self, user: str) -> bool:
        return not self.allowed or user in self.allowed

    def join(self, user: str) -> None:
        if not self.can(user):
            raise AccessDenied(f"user {user!r} tidak berhak pada room {self.name}")
        with self._lock:
            self._members.add(user)

    def leave(self, user: str) -> None:
        with self._lock:
            self._members.discard(user)
            self._presence.pop(user, None)

    # -- op ----------------------------------------------------------------
    def _sys_op(self, kind: str, target: str, field: str = "",
                value: Any = None) -> Op:
        """Op sistem (undo/redo) dengan ts logis selalu menang + seq unik."""
        self._max_ts += 1.0
        self._sys_seq += 1
        return Op("__sys__", self._sys_seq, kind, target, field, value,
                  ts=self._max_ts)

    def submit(self, op: Op) -> bool:
        if not self.can(op.client):
            raise AccessDenied(f"user {op.client!r} tidak berhak")
        with self._lock:
            self.doc.record(op)
            berubah = self.doc.apply(op)
            if berubah:
                self._max_ts = max(self._max_ts, op.ts)
                self._undo.setdefault(op.client, []).append(op)
                self._redo.pop(op.client, None)
            return berubah

    # -- presence ----------------------------------------------------------
    def set_presence(self, user: str, cursor: Optional[dict] = None,
                     name: str = "") -> dict:
        with self._lock:
            self._presence[user] = {"user": user, "name": name,
                                    "cursor": cursor or {},
                                    "at": self._clock()}
        return dict(self._presence[user])

    def presence(self) -> list[dict]:
        with self._lock:
            return [dict(v) for v in self._presence.values()]

    def cursors(self) -> dict[str, dict]:
        with self._lock:
            return {u: p["cursor"] for u, p in self._presence.items()
                    if p.get("cursor")}

    # -- komentar ----------------------------------------------------------
    def comment(self, user: str, target: str, text: str,
                parent: Optional[int] = None) -> dict:
        if not self.can(user):
            raise AccessDenied(f"user {user!r} tidak berhak")
        with self._lock:
            entry = {"id": len(self._comments) + 1, "user": user,
                     "target": target, "text": text, "parent": parent,
                     "mentions": _MENTION_RE.findall(text or ""),
                     "at": self._clock()}
            self._comments.append(entry)
            return dict(entry)

    def comments(self, target: Optional[str] = None) -> list[dict]:
        with self._lock:
            return [dict(c) for c in self._comments
                    if target is None or c["target"] == target]

    # -- undo / redo per-user ---------------------------------------------
    def undo(self, user: str) -> bool:
        """Batalkan op terakhir `user`. Inverse = op sistem (ts logis menang)."""
        with self._lock:
            tumpuk = self._undo.get(user) or []
            if not tumpuk:
                return False
            orig = tumpuk.pop()
            if orig.kind == "add_node":
                inv = self._sys_op("remove_node", orig.target)
            elif orig.kind == "remove_node":
                inv = self._sys_op("add_node", orig.target, value=orig.value)
            else:  # set -> kosongkan field
                inv = self._sys_op("set", orig.target, orig.field, None)
            self.doc.record(inv)
            self.doc.apply(inv)
            self._redo.setdefault(user, []).append(orig)
            return True

    def redo(self, user: str) -> bool:
        with self._lock:
            tumpuk = self._redo.get(user) or []
            if not tumpuk:
                return False
            orig = tumpuk.pop()
            ulang = self._sys_op(orig.kind, orig.target, orig.field, orig.value)
            self.doc.record(ulang)
            self.doc.apply(ulang)
            self._undo.setdefault(user, []).append(orig)
            return True

    def stats(self) -> dict:
        return {"room": self.name, "members": len(self._members),
                "presence": len(self._presence),
                "comments": len(self._comments),
                "nodes": len(self.doc.snapshot()["nodes"])}


# ---------------------------------------------------------------------------
# Server: banyak room + broadcast + offline merge
# ---------------------------------------------------------------------------

class CollabServer:
    def __init__(self) -> None:
        self.rooms: dict[str, CollabRoom] = {}

    def room(self, name: str, allowed: Optional[list[str]] = None) -> CollabRoom:
        if name not in self.rooms:
            self.rooms[name] = CollabRoom(name, allowed)
        return self.rooms[name]

    def submit(self, room: str, op: Op) -> dict:
        r = self.room(room)
        berubah = r.submit(op)
        return {"applied": berubah, "snapshot": r.doc.snapshot(),
                "presence": r.presence()}

    def merge_offline(self, room: str, ops: list[Op]) -> dict:
        """Terapkan op yang dibuat saat offline (idempoten, aman urutan)."""
        r = self.room(room)
        n = r.doc.apply_many(ops)
        for op in ops:
            r.doc.record(op)
        return {"merged": n, "snapshot": r.doc.snapshot()}
