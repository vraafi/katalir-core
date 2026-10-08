# hitl.py — Fitur #3: Human-in-the-Loop (8 Okt 2026)
# ======================================================================
# Menutup gap vs n8n "Wait" node + Slack/Email approval ("send and wait").
# Riset Okt 2026 (docs/feature-gap-closure-2026-10-08.md §3): pola HITL
# produksi = PAUSE workflow -> kirim notifikasi -> tunggu keputusan ->
# RESUME, dengan timeout auto-resume, multi-approver, dan audit trail.
#
# KENAPA PAUSE = EXCEPTION, BUKAN BLOCKING
#   Menahan coroutine `run()` selama menunggu manusia akan memblokir event
#   loop (dan slot worker) berjam-jam. Karena itu node `wait_for_human`
#   MENGHENTIKAN eksekusi dengan `HitlPaused` (kontrol-alir, BUKAN error),
#   menyimpan permintaan, dan mengembalikan status `waiting_approval`.
#   Resume memakai ULANG eksekusi yang sama: node HITL melihat permintaan
#   sudah disetujui lalu lewat (idempoten), node lain berjalan lagi.
#
# DUA BACKEND
#   - Supabase (`hitl_requests`) di produksi.
#   - Memori proses (dev/uji) sebagai fallback deterministik.
#
# MODEL KEPUTUSAN
#   approval_mode "any" : satu approver setuju -> approved; satu menolak -> rejected
#   approval_mode "all" : SEMUA approver harus setuju; satu menolak -> rejected
#   timeout             : on_timeout "resume" -> approved(default_action) | "reject"
#   eskalasi            : bila timeout & escalate_to ada -> tambah approver, 1x
# ======================================================================

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import database as db

CHANNELS = ("chat", "slack", "email", "telegram", "webhook")
APPROVAL_MODES = ("any", "all")
ON_TIMEOUT = ("resume", "reject")
DEFAULT_TIMEOUT_S = 3600
MAX_TIMEOUT_S = 7 * 24 * 3600  # 7 hari

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_EXPIRED = "expired"


class HitlError(ValueError):
    """Konfigurasi/permintaan HITL tidak valid."""


class HitlPaused(Exception):
    """Kontrol-alir: workflow dijeda menunggu manusia. BUKAN kegagalan."""

    def __init__(self, request: dict) -> None:
        super().__init__(f"HITL pause: {request.get('request_id')}")
        self.request = request


# ---------------------------------------------------------------------------
# Token resume (HMAC, pola sama dengan approval flow)
# ---------------------------------------------------------------------------

def _secret() -> bytes:
    return (os.getenv("HITL_SECRET")
            or os.getenv("APPROVAL_SECRET")
            or os.getenv("JWT_SECRET")
            or "katalir-hitl-dev-secret").encode("utf-8")


def make_token(request_id: str) -> str:
    return hmac.new(_secret(), f"hitl:{request_id}".encode("utf-8"),
                    hashlib.sha256).hexdigest()[:32]


def verify_token(request_id: str, token: str) -> bool:
    return bool(token) and hmac.compare_digest(make_token(request_id),
                                               str(token))


# ---------------------------------------------------------------------------
# Backend: memori (uji/dev) & Supabase (produksi)
# ---------------------------------------------------------------------------

class _MemoryBackend:
    name = "memory"

    def __init__(self) -> None:
        self._rows: dict[str, dict] = {}

    def save(self, row: dict) -> None:
        self._rows[row["request_id"]] = json.loads(json.dumps(row))

    def get(self, request_id: str) -> Optional[dict]:
        r = self._rows.get(request_id)
        return json.loads(json.dumps(r)) if r else None

    def find(self, workflow_id: str = "", execution_id: str = "",
             node_id: str = "") -> Optional[dict]:
        for r in self._rows.values():
            if (workflow_id and r.get("workflow_id") != workflow_id) or \
               (execution_id and r.get("execution_id") != execution_id) or \
               (node_id and r.get("node_id") != node_id):
                continue
            return json.loads(json.dumps(r))
        return None

    def list_pending(self) -> list[dict]:
        return [json.loads(json.dumps(r)) for r in self._rows.values()
                if r.get("status") == STATUS_PENDING]

    def all(self) -> list[dict]:
        return [json.loads(json.dumps(r)) for r in self._rows.values()]


class _SupabaseBackend:
    name = "supabase"

    def _t(self):
        return db.get_write_client()

    def save(self, row: dict) -> None:
        self._t().table("hitl_requests").upsert(row, on_conflict="request_id").execute()

    def get(self, request_id: str) -> Optional[dict]:
        res = (self._t().table("hitl_requests").select("*")
               .eq("request_id", request_id).limit(1).execute())
        return (res.data or [None])[0]

    def find(self, workflow_id: str = "", execution_id: str = "",
             node_id: str = "") -> Optional[dict]:
        q = self._t().table("hitl_requests").select("*")
        if workflow_id:
            q = q.eq("workflow_id", workflow_id)
        if execution_id:
            q = q.eq("execution_id", execution_id)
        if node_id:
            q = q.eq("node_id", node_id)
        res = q.order("created_at", desc=True).limit(1).execute()
        return (res.data or [None])[0]

    def list_pending(self) -> list[dict]:
        res = (self._t().table("hitl_requests").select("*")
               .eq("status", STATUS_PENDING).execute())
        return res.data or []

    def all(self) -> list[dict]:
        return self._t().table("hitl_requests").select("*").execute().data or []


_BACKEND: Any = None


def _backend():
    global _BACKEND
    if _BACKEND is not None:
        return _BACKEND
    if db.is_configured():
        try:
            _BACKEND = _SupabaseBackend()
            return _BACKEND
        except Exception:  # noqa: BLE001
            pass
    _BACKEND = _MemoryBackend()
    return _BACKEND


def set_backend(backend: Any) -> None:
    """Untuk uji: pasang backend eksplisit (mis. memori bersama)."""
    global _BACKEND
    _BACKEND = backend


# ---------------------------------------------------------------------------
# Jam
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse_iso(s: Any) -> Optional[datetime]:
    if not s:
        return None
    try:
        v = str(s).replace("Z", "+00:00")
        dt = datetime.fromisoformat(v)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Keputusan (murni, bisa diuji tanpa DB)
# ---------------------------------------------------------------------------

def evaluate(row: dict) -> str:
    """Hitung status dari daftar keputusan. Murni (tanpa efek samping)."""
    mode = str(row.get("approval_mode") or "any").lower()
    approvers = _approvers(row)
    decisions = row.get("decisions") or []
    if not isinstance(decisions, list):
        decisions = []
    by_approver = {str(d.get("approver")): str(d.get("decision"))
                   for d in decisions if isinstance(d, dict)}
    rejects = [a for a, d in by_approver.items() if d == "reject"]
    approves = [a for a, d in by_approver.items() if d == "approve"]

    if mode == "all":
        if rejects:
            return STATUS_REJECTED
        if approvers and all(a in approves for a in approvers):
            return STATUS_APPROVED
        if not approvers and approves:
            return STATUS_APPROVED
        return STATUS_PENDING
    # mode "any"
    if approves:
        return STATUS_APPROVED
    if rejects:
        return STATUS_REJECTED
    return STATUS_PENDING


def _approvers(row: dict) -> list[str]:
    a = row.get("approvers")
    if isinstance(a, str):
        try:
            parsed = json.loads(a)
            a = parsed if isinstance(parsed, list) else [a]
        except (ValueError, TypeError):
            a = [x.strip() for x in a.split(",") if x.strip()]
    if not a:
        return []
    return [str(x).strip() for x in a if str(x).strip()]


# ---------------------------------------------------------------------------
# API publik
# ---------------------------------------------------------------------------

def create_request(*, workflow_id: str = "", execution_id: str = "",
                   node_id: str = "", owner: str = "", channel: str = "chat",
                   message: str = "", approvers: Any = None,
                   approval_mode: str = "any", timeout_s: int = DEFAULT_TIMEOUT_S,
                   on_timeout: str = "resume", default_action: str = "approve",
                   escalate_to: Any = None, context: Optional[dict] = None,
                   backend: Any = None) -> dict:
    """Buat permintaan persetujuan (status pending) + token resume."""
    channel = channel if channel in CHANNELS else "chat"
    approval_mode = (approval_mode if approval_mode in APPROVAL_MODES else "any")
    on_timeout = on_timeout if on_timeout in ON_TIMEOUT else "resume"
    try:
        timeout_s = int(timeout_s)
    except (TypeError, ValueError):
        timeout_s = DEFAULT_TIMEOUT_S
    timeout_s = max(0, min(timeout_s, MAX_TIMEOUT_S))

    approvers_list = approvers
    if isinstance(approvers, str):
        approvers_list = [x.strip() for x in approvers.split(",") if x.strip()]
    approvers_list = [str(x).strip() for x in (approvers_list or []) if str(x).strip()]

    escalate = escalate_to
    if isinstance(escalate, str):
        escalate = [x.strip() for x in escalate.split(",") if x.strip()]

    rid = str(uuid.uuid4())
    row = {
        "request_id": rid,
        "workflow_id": workflow_id or None,
        "execution_id": execution_id or None,
        "node_id": node_id or None,
        "owner": owner or None,
        "channel": channel,
        "message": message or "",
        "approvers": approvers_list,
        "approval_mode": approval_mode,
        "on_timeout": on_timeout,
        "default_action": default_action if default_action in ("approve", "reject")
                          else "approve",
        "escalate_to": escalate or [],
        "escalated": False,
        "status": STATUS_PENDING,
        "decisions": [],
        "context": context or {},
        "resume_token": make_token(rid),
        "created_at": _iso(_now()),
        "timeout_at": _iso(_now() + timedelta(seconds=timeout_s)) if timeout_s else None,
        "resolved_at": None,
    }
    (backend or _backend()).save(row)
    return row


def record_decision(request_id: str, approver: str, decision: str,
                    token: str = "", backend: Any = None) -> dict:
    """Catat keputusan satu approver, hitung ulang status."""
    be = backend or _backend()
    row = be.get(request_id)
    if not row:
        raise HitlError(f"permintaan {request_id} tidak ditemukan")
    if token and not verify_token(request_id, token):
        raise HitlError("token resume tidak valid")
    decision = str(decision or "").strip().lower()
    if decision not in ("approve", "reject"):
        raise HitlError(f"keputusan {decision!r} tidak dikenal (approve/reject)")
    if row.get("status") != STATUS_PENDING:
        return row  # sudah selesai: keputusan berikut diabaikan (idempoten)

    decisions = list(row.get("decisions") or [])
    # ganti keputusan approver yang sama (boleh berubah pikiran)
    decisions = [d for d in decisions if str(d.get("approver")) != str(approver)]
    decisions.append({"approver": str(approver), "decision": decision,
                      "at": _iso(_now())})
    row["decisions"] = decisions
    status = evaluate(row)
    row["status"] = status
    if status in (STATUS_APPROVED, STATUS_REJECTED):
        row["resolved_at"] = _iso(_now())
    be.save(row)
    return row


def get_request(request_id: str, backend: Any = None) -> Optional[dict]:
    return (backend or _backend()).get(request_id)


def find_request(*, workflow_id: str = "", execution_id: str = "",
                 node_id: str = "", backend: Any = None) -> Optional[dict]:
    return (backend or _backend()).find(workflow_id=workflow_id,
                                        execution_id=execution_id,
                                        node_id=node_id)


def resume_url(request_id: str, base_url: str = "") -> str:
    base = (base_url or os.getenv("PUBLIC_BASE_URL", "")
            or "https://katalir.de5.net").rstrip("/")
    return f"{base}/hitl/resume/{request_id}?token={make_token(request_id)}"


def expire_due(backend: Any = None, now: Optional[datetime] = None) -> list[dict]:
    """Tandai permintaan yang melewati timeout; terapkan aksi default.

    Bila `escalate_to` ada dan belum pernah dieskalasi: tambah approver dan
    PERPANJANG timeout sekali (pola eskalasi 2026) alih-alih langsung menutup.
    """
    be = backend or _backend()
    now = now or _now()
    changed: list[dict] = []
    for row in be.list_pending():
        t = _parse_iso(row.get("timeout_at"))
        if not t or now < t:
            continue
        esc = row.get("escalate_to") or []
        if isinstance(esc, str):
            esc = [x.strip() for x in esc.split(",") if x.strip()]
        if esc and not row.get("escalated"):
            row["escalated"] = True
            cur = _approvers(row)
            row["approvers"] = sorted(set(cur) | set(str(x) for x in esc))
            row["timeout_at"] = _iso(now + timedelta(seconds=DEFAULT_TIMEOUT_S))
            be.save(row)
            changed.append(row)
            continue
        if str(row.get("on_timeout") or "resume") == "reject":
            row["status"] = STATUS_REJECTED
        else:
            row["status"] = STATUS_APPROVED
            row["decisions"] = list(row.get("decisions") or []) + [{
                "approver": "__timeout__",
                "decision": str(row.get("default_action") or "approve"),
                "at": _iso(now), "reason": "timeout"}]
        row["resolved_at"] = _iso(now)
        be.save(row)
        changed.append(row)
    return changed


def is_resumable(request_id: str, backend: Any = None) -> bool:
    """Boleh lanjut? approved/timeout-approve -> True; pending/rejected -> False."""
    row = get_request(request_id, backend=backend)
    if not row:
        return False
    return str(row.get("status")) == STATUS_APPROVED


def audit_trail(request_id: str, backend: Any = None) -> list[dict]:
    row = get_request(request_id, backend=backend)
    if not row:
        return []
    trail = [{"event": "created", "at": row.get("created_at"),
              "channel": row.get("channel"), "message": row.get("message")}]
    for d in row.get("decisions") or []:
        trail.append({"event": "decision", "approver": d.get("approver"),
                      "decision": d.get("decision"), "at": d.get("at"),
                      "reason": d.get("reason")})
    if row.get("escalated"):
        trail.append({"event": "escalated", "to": row.get("escalate_to"),
                      "at": row.get("timeout_at")})
    if row.get("status") in (STATUS_APPROVED, STATUS_REJECTED):
        trail.append({"event": "resolved", "status": row.get("status"),
                      "at": row.get("resolved_at")})
    return trail


def notify(row: dict, sender: Optional[Any] = None) -> dict:
    """Kirim notifikasi ke kanal. `sender(channel, message, row) -> dict`.

    Tanpa `sender`, notifikasi hanya DICATAT (kanal "chat" memakai kartu di
    UI). Ini sengaja: HITL tidak boleh gagal hanya karena provider tak siap.
    """
    if sender is None:
        return {"status": "recorded", "channel": row.get("channel"),
                "message": row.get("message")}
    try:
        out = sender(row.get("channel"), row.get("message"), row)
        return out if isinstance(out, dict) else {"status": "sent"}
    except Exception as exc:  # noqa: BLE001 - notifikasi gagal bukan alasan gagal HITL
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}


__all__ = [
    "CHANNELS", "APPROVAL_MODES", "ON_TIMEOUT", "DEFAULT_TIMEOUT_S",
    "STATUS_PENDING", "STATUS_APPROVED", "STATUS_REJECTED", "STATUS_EXPIRED",
    "HitlError", "HitlPaused", "make_token", "verify_token", "evaluate",
    "create_request", "record_decision", "get_request", "find_request",
    "resume_url", "expire_due", "is_resumable", "audit_trail", "notify",
    "set_backend", "_MemoryBackend", "_SupabaseBackend",
]
