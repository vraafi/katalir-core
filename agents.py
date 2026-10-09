"""TASK 5 / Fitur #1 — n8n Agents sebagai *first-class entity*.

Masalah yang diselesaikan
-------------------------
Di n8n, "AI Agent" adalah **node** di dalam workflow: ia hidup sebagai bagian
dari graf, bukan sebagai objek tersendiri. Akibatnya agent tidak bisa dipakai
ulang, tidak punya siklus hidup (draft → aktif → arsip), tidak bisa
dihubungkan ke beberapa kanal, dan tidak bisa diekspos sebagai MCP server.

Fitur ini mengangkat **Agent menjadi entitas kelas satu** di Katalir:

    agents (tabel) + siklus hidup + kanal + MCP + UI /agents

Kontrak data
------------
Sebuah agent adalah bundel deklaratif dari komponen yang **sudah ada** di
proyek ini — tidak ada mesin baru:

| Komponen agent | Modul yang sudah ada |
|----------------|----------------------|
| model | `agent_engine.MODEL_ID` / pilihan user |
| instruksi | teks bebas (system prompt) |
| tools | `tools.py` + katalog connector (`mcp_registry`) |
| memory | `memory_manager` (sudah per-`agent_id`!) |
| workflow | `workflow_templates.flow_data` |
| kanal | tabel `agent_channels` (baru) |
| MCP | `mcp_server` (Katalir sebagai MCP server) |

Siklus hidup
------------
`draft` → `active` → `paused` → `archived`. Transisi dibatasi oleh tabel
`AGENT_TRANSITIONS`; transisi terlarang ditolak (bukan diterima diam-diam).

Backend
-------
Sama seperti `workflow_templates`: Supabase bila terkonfigurasi, dan store
in-memory deterministik untuk dev/uji (tanpa jaringan).
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Optional

import database as db

# ---------------------------------------------------------------------------
# Kosakata tertutup
# ---------------------------------------------------------------------------

AGENT_STATUSES = ("draft", "active", "paused", "archived")

#: Transisi yang diizinkan. Semua yang tidak ada di sini DITOLAK.
AGENT_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft": ("active", "archived"),
    "active": ("paused", "archived"),
    "paused": ("active", "archived"),
    "archived": (),          # arsip bersifat terminal
}

CHANNEL_TYPES = ("web", "api", "webhook", "slack", "schedule", "mcp", "embed")

MAX_NAME = 120
MAX_INSTRUCTION = 20000
MAX_AGENTS_PER_USER = 200
MAX_CHANNELS_PER_AGENT = 20
MAX_TOOLS_PER_AGENT = 100

_TABLE = "agents"
_CH_TABLE = "agent_channels"

# Store in-memory untuk dev/uji (deterministik, tanpa jaringan).
_LAGENTS: dict[str, dict] = {}
_LCHANNELS: dict[str, dict] = {}


class AgentError(ValueError):
    """Agent tidak sah. Selalu membawa pesan yang bisa ditindaklanjuti."""


# ---------------------------------------------------------------------------
# Validasi
# ---------------------------------------------------------------------------


def _now() -> int:
    return int(time.time())


def _iso(ts: Any) -> str:
    """Konversi timestamp (int epoch / ISO string) -> ISO-8601 UTC.

    PENTING: kolom `created_at`/`updated_at` di Supabase bertipe `timestamptz`.
    Mengirim angka epoch mentah ditolak Postgres
    (`date/time field value out of range`). Store in-memory tetap memakai int.
    """
    import datetime as _dt

    if isinstance(ts, str):
        return ts
    return _dt.datetime.fromtimestamp(int(ts), tz=_dt.timezone.utc).isoformat()


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise AgentError(msg)


def _clean_str(v: Any, *, field: str, max_len: int, required: bool = False) -> str:
    s = str(v or "").strip()
    if required:
        _require(bool(s), f"{field}: wajib diisi")
    _require(len(s) <= max_len, f"{field}: maks {max_len} karakter")
    return s


def validate_status(status: str) -> str:
    s = str(status or "").strip().lower()
    _require(s in AGENT_STATUSES,
             f"status tidak dikenal: '{status}' (didukung: {', '.join(AGENT_STATUSES)})")
    return s


def can_transition(src: str, dst: str) -> bool:
    """True bila perpindahan `src -> dst` diizinkan oleh siklus hidup."""
    s, d = str(src or "").strip().lower(), str(dst or "").strip().lower()
    if s == d:
        return True  # idempoten
    return d in AGENT_TRANSITIONS.get(s, ())


def validate_tools(tools: Any) -> list[str]:
    """Tools harus daftar nama string yang unik & wajar."""
    if tools is None:
        return []
    _require(isinstance(tools, list), "tools: harus daftar")
    _require(len(tools) <= MAX_TOOLS_PER_AGENT,
             f"tools: maks {MAX_TOOLS_PER_AGENT}")
    out: list[str] = []
    for t in tools:
        name = str(t or "").strip()
        _require(bool(name), "tools: nama tool tidak boleh kosong")
        _require(len(name) <= 120, "tools: nama tool maks 120 karakter")
        out.append(name)
    _require(len(set(out)) == len(out), "tools: ada nama duplikat")
    return out


def validate_channels(channels: Any) -> list[dict]:
    if channels is None:
        return []
    _require(isinstance(channels, list), "channels: harus daftar")
    _require(len(channels) <= MAX_CHANNELS_PER_AGENT,
             f"channels: maks {MAX_CHANNELS_PER_AGENT}")
    out: list[dict] = []
    for c in channels:
        _require(isinstance(c, dict), "channels: tiap item harus objek")
        ctype = str(c.get("type") or "").strip().lower()
        _require(ctype in CHANNEL_TYPES,
                 f"channel.type tidak dikenal: '{c.get('type')}' "
                 f"(didukung: {', '.join(CHANNEL_TYPES)})")
        out.append({
            "type": ctype,
            "config": dict(c.get("config") or {}),
            "enabled": bool(c.get("enabled", True)),
        })
    return out


def validate_payload(payload: Any, *, partial: bool = False) -> dict:
    """Validasi payload agent. `partial=True` untuk update (field opsional)."""
    _require(isinstance(payload, dict), "payload harus objek")

    out: dict[str, Any] = {}
    if not partial or "name" in payload:
        out["name"] = _clean_str(payload.get("name"), field="name",
                                 max_len=MAX_NAME, required=True)
    if not partial or "instruction" in payload:
        out["instruction"] = _clean_str(payload.get("instruction"),
                                        field="instruction",
                                        max_len=MAX_INSTRUCTION)
    if not partial or "model" in payload:
        out["model"] = _clean_str(payload.get("model"), field="model",
                                  max_len=120)
    if not partial or "tools" in payload:
        out["tools"] = validate_tools(payload.get("tools"))
    if not partial or "channels" in payload:
        out["channels"] = validate_channels(payload.get("channels"))
    if not partial or "memory_enabled" in payload:
        out["memory_enabled"] = bool(payload.get("memory_enabled", True))
    if not partial or "workflow_id" in payload:
        wid = _clean_str(payload.get("workflow_id"), field="workflow_id",
                         max_len=120)
        out["workflow_id"] = wid or None
    if not partial or "description" in payload:
        out["description"] = _clean_str(payload.get("description"),
                                        field="description", max_len=2000)
    if "status" in payload:
        out["status"] = validate_status(payload.get("status"))
    return out


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def _row_to_agent(row: dict) -> dict:
    a = dict(row)
    a["channels"] = list(a.get("channels") or [])
    a["tools"] = list(a.get("tools") or [])
    a["can_transition"] = list(AGENT_TRANSITIONS.get(str(a.get("status")), ()))
    return a


def _backend() -> str:
    return "supabase" if db.is_configured() else "memory"


def create_agent(user_id: str, payload: dict) -> dict:
    """Buat agent baru dalam status `draft`."""
    uid = _clean_str(user_id, field="user_id", max_len=200, required=True)
    data = validate_payload(payload, partial=False)

    existing = list_agents(uid)
    _require(len(existing) < MAX_AGENTS_PER_USER,
             f"batas agent per pengguna ({MAX_AGENTS_PER_USER}) tercapai")

    aid = str(uuid.uuid4())
    row = {
        "id": aid,
        "user_id": uid,
        "name": data["name"],
        "description": data.get("description", ""),
        "instruction": data["instruction"],
        "model": data["model"],
        "tools": data["tools"],
        "channels": data["channels"],
        "memory_enabled": data["memory_enabled"],
        "workflow_id": data.get("workflow_id"),
        "status": "draft",
        "version": 1,
        "created_at": _now(),
        "updated_at": _now(),
    }

    if _backend() == "supabase":
        try:
            c = db.get_write_client()
            # `channels` disimpan di tabel terpisah; simpan sisanya di `agents`.
            # created_at/updated_at dikirim ISO-8601 (kolom timestamptz).
            agents_row = {k: v for k, v in row.items() if k != "channels"}
            agents_row["created_at"] = _iso(row["created_at"])
            agents_row["updated_at"] = _iso(row["updated_at"])
            res = c.table(_TABLE).insert(agents_row).execute()
            if res.data:
                row = dict(res.data[0])
                row["channels"] = data["channels"]
            _sync_channels(c, uid, aid, data["channels"])
        except Exception as exc:  # noqa: BLE001 - tabel belum dimigrasi
            raise AgentError(
                f"gagal menyimpan agent ke database: {type(exc).__name__}: {exc}"
            ) from exc
    else:
        _LAGENTS[aid] = {k: v for k, v in row.items() if k != "channels"}
        _LCHANNELS[aid] = list(data["channels"])

    return _row_to_agent(row)


def _sync_channels(c, user_id: str, agent_id: str, channels: list[dict]) -> None:
    """Tulis ulang kanal agent (hapus lalu sisip) — sederhana & idempoten."""
    try:
        c.table(_CH_TABLE).delete().eq("agent_id", agent_id).execute()
        if channels:
            rows = [{"id": str(uuid.uuid4()), "agent_id": agent_id,
                     "user_id": user_id, "type": ch["type"],
                     "config": ch["config"], "enabled": ch["enabled"],
                     "created_at": _iso(_now())}
                    for ch in channels]
            c.table(_CH_TABLE).insert(rows).execute()
    except Exception:  # noqa: BLE001 - kanal opsional bila tabel belum ada
        pass


def get_agent(agent_id: str, user_id: Optional[str] = None) -> Optional[dict]:
    """Ambil satu agent milik user. None bila tidak ada (bukan 500)."""
    aid = str(agent_id or "").strip()
    if not aid:
        return None
    if _backend() == "supabase":
        # ID agent adalah uuid; ID non-uuid MUSTAHIL ada dan meneruskannya ke
        # PostgREST membuat Postgres menolak sintaks -> 500. Jawaban benar
        # untuk "tidak ada" adalah None (-> 404). (Pelajaran dari
        # `workflow_templates.get_template`.)
        try:
            uuid.UUID(aid)
        except (ValueError, AttributeError, TypeError):
            return None
        try:
            c = db.get_write_client()
            q = c.table(_TABLE).select("*").eq("id", aid)
            if user_id:
                q = q.eq("user_id", user_id)
            res = q.execute()
        except Exception:  # noqa: BLE001
            return None
        if not res.data:
            return None
        row = dict(res.data[0])
        row["channels"] = _load_channels(c, aid)
        return _row_to_agent(row)

    row = _LAGENTS.get(aid)
    if not row:
        return None
    if user_id and str(row.get("user_id")) != str(user_id):
        return None
    merged = dict(row)
    merged["channels"] = list(_LCHANNELS.get(aid, []))
    return _row_to_agent(merged)


def _load_channels(c, agent_id: str) -> list[dict]:
    try:
        res = (c.table(_CH_TABLE).select("*").eq("agent_id", agent_id)
               .order("created_at").execute())
        return [{"type": r.get("type"), "config": r.get("config") or {},
                 "enabled": bool(r.get("enabled", True))}
                for r in (res.data or [])]
    except Exception:  # noqa: BLE001
        return []


def list_agents(user_id: str, status: Optional[str] = None) -> list[dict]:
    """Semua agent milik user, urut terbaru dulu."""
    uid = str(user_id or "").strip()
    if not uid:
        return []
    if _backend() == "supabase":
        try:
            c = db.get_write_client()
            res = (c.table(_TABLE).select("*").eq("user_id", uid)
                   .order("created_at", desc=True).execute())
            rows = [dict(r) for r in (res.data or [])]
            for r in rows:
                r["channels"] = _load_channels(c, str(r.get("id")))
        except Exception:  # noqa: BLE001
            rows = []
    else:
        rows = []
        for aid, r in _LAGENTS.items():
            if str(r.get("user_id")) != uid:
                continue
            merged = dict(r)
            merged["channels"] = list(_LCHANNELS.get(aid, []))
            rows.append(merged)
        rows.sort(key=lambda r: r.get("created_at") or 0, reverse=True)

    out = [_row_to_agent(r) for r in rows]
    if status:
        s = validate_status(status)
        out = [a for a in out if a.get("status") == s]
    return out


def update_agent(agent_id: str, user_id: str, patch: dict) -> dict:
    """Perbarui agent (partial). Transisi status DIVALIDASI bila ada."""
    current = get_agent(agent_id, user_id)
    _require(current is not None, "agent tidak ditemukan")

    data = validate_payload(patch, partial=True)
    if "status" in data:
        new_status = data["status"]
        _require(can_transition(current["status"], new_status),
                 f"transisi status '{current['status']}' -> '{new_status}' tidak diizinkan")
    if "channels" in data:
        _require(current["status"] != "archived",
                 "agent terarsip tidak dapat diubah kanalnya")

    updates = dict(data)
    if updates:
        updates["updated_at"] = _now()
        updates["version"] = int(current.get("version") or 1) + 1

    aid = current["id"]
    if _backend() == "supabase":
        try:
            c = db.get_write_client()
            channels = updates.pop("channels", None)
            if "updated_at" in updates:
                updates["updated_at"] = _iso(updates["updated_at"])
            if updates:
                c.table(_TABLE).update(updates).eq("id", aid).eq("user_id", user_id).execute()
            if channels is not None:
                _sync_channels(c, user_id, aid, channels)
        except Exception as exc:  # noqa: BLE001
            raise AgentError(f"gagal memperbarui agent: {type(exc).__name__}: {exc}") from exc
    else:
        channels = updates.pop("channels", None)
        store = _LAGENTS.get(aid)
        if store is not None:
            store.update(updates)
        if channels is not None:
            _LCHANNELS[aid] = list(channels)

    refreshed = get_agent(aid, user_id)
    _require(refreshed is not None, "agent hilang setelah pembaruan")
    return refreshed


def set_status(agent_id: str, user_id: str, status: str) -> dict:
    """Ubah status dengan pemeriksaan transisi siklus hidup."""
    return update_agent(agent_id, user_id, {"status": status})


def delete_agent(agent_id: str, user_id: str) -> bool:
    """Hapus agent. Agent `active` harus dijeda/diarsip dulu (aman)."""
    current = get_agent(agent_id, user_id)
    if current is None:
        return False
    _require(current["status"] != "active",
             "agent aktif harus dijeda atau diarsipkan sebelum dihapus")
    aid = current["id"]
    if _backend() == "supabase":
        try:
            c = db.get_write_client()
            c.table(_CH_TABLE).delete().eq("agent_id", aid).execute()
            c.table(_TABLE).delete().eq("id", aid).eq("user_id", user_id).execute()
        except Exception as exc:  # noqa: BLE001
            raise AgentError(f"gagal menghapus agent: {type(exc).__name__}: {exc}") from exc
    else:
        _LAGENTS.pop(aid, None)
        _LCHANNELS.pop(aid, None)
    return True


# ---------------------------------------------------------------------------
# Turunan: kanal, MCP, memory
# ---------------------------------------------------------------------------


def agent_channels(agent_id: str, user_id: str) -> list[dict]:
    a = get_agent(agent_id, user_id)
    return list(a["channels"]) if a else []


def mcp_descriptor(agent_id: str, user_id: str) -> Optional[dict]:
    """Deskripsi agent sebagai MCP server entry (dipakai `/agents/:id/mcp`).

    Hanya agent `active` yang boleh diekspos — agent draft/arsip tidak.
    """
    a = get_agent(agent_id, user_id)
    if not a:
        return None
    exposed = a["status"] == "active"
    return {
        "agent_id": a["id"],
        "name": a["name"],
        "exposed": exposed,
        "reason": None if exposed else f"agent berstatus '{a['status']}' tidak diekspos",
        "tools": a.get("tools", []),
        "transport": "streamable_http",
        "endpoint": f"/mcp/agents/{a['id']}",
        "memory_enabled": bool(a.get("memory_enabled")),
    }


def recall_scope(agent_id: str, user_id: str) -> dict:
    """Ruang lingkup memory agent (dipakai `memory_manager`)."""
    a = get_agent(agent_id, user_id)
    _require(a is not None, "agent tidak ditemukan")
    return {
        "user_id": str(user_id),
        "agent_id": a["id"],
        "memory_enabled": bool(a.get("memory_enabled")),
    }


def describe() -> dict[str, Any]:
    return {
        "statuses": list(AGENT_STATUSES),
        "transitions": {k: list(v) for k, v in AGENT_TRANSITIONS.items()},
        "channel_types": list(CHANNEL_TYPES),
        "limits": {
            "agents_per_user": MAX_AGENTS_PER_USER,
            "channels_per_agent": MAX_CHANNELS_PER_AGENT,
            "tools_per_agent": MAX_TOOLS_PER_AGENT,
            "name": MAX_NAME,
            "instruction": MAX_INSTRUCTION,
        },
        "backend": _backend(),
        "rules": [
            "agent baru selalu berstatus draft",
            "transisi status divalidasi (AGENT_TRANSITIONS)",
            "agent aktif harus dijeda/diarsip sebelum dihapus",
            "hanya agent aktif yang diekspos sebagai MCP server",
            "penghapusan/agent tidak ditemukan -> None/False, bukan 500",
        ],
    }
