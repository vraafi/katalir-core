# database.py - BaaS Supabase (SaaS 2026). 3 tabel: users, chat_sessions, chat_messages.
# SKEMA SQL (Supabase SQL Editor):
#   users(id uuid pk, email text unique, name text, tier text default 'free',
#         usage_count int default 0, created_at timestamptz default now());
#   chat_sessions(id uuid pk, user_id uuid ref users(id) on delete cascade,
#                 title text default 'Chat Baru', created_at timestamptz default now());
#   chat_messages(id uuid pk, session_id uuid ref chat_sessions(id) on delete cascade,
#                 role text, content text, created_at timestamptz default now());
#   user_integrations(id uuid pk, user_email text not null, provider_name text not null,
#                     api_token text not null, created_at timestamptz default now(),
#                     updated_at timestamptz default now(),
#                     unique(user_email, provider_name));

import os
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
SUPABASE_KEY = (os.getenv("SUPABASE_KEY") or "").strip()

_client = None
_configured = None

# Cuando True, los fallos de escritura NO caen silenciosamente a RAM:
# si SUPABASE_URL está configurado pero un INSERT/UPDATE falla, se propaga error.
# Esto garantiza datos permanentes en Postgres (sin "data amnesia").
PERSIST_REQUIRED = os.getenv("PERSIST_REQUIRED", "1").strip().lower() in ("1", "true", "yes")

# Service_role key: bypasa RLS (necesaria para INSERT/UPDATE con anon restringida).
# Si existe SUPABASE_SERVICE_KEY (recomendado), se usa para escrituras.
# De lo contrario, degrada a SUPABASE_KEY (anon; puede fallar si RLS bloquea writes).
SUPABASE_SERVICE_KEY = (os.getenv("SUPABASE_SERVICE_KEY") or "").strip()

# Fallback lokal bila Supabase belum dikonfigurasi / gagal
_LUSER = {}
_LSESS = {}
_LMSG = {}
_LINT = {}      # (email, provider) -> {"api_token":..., "updated_at":...}
_SEQ = [0]


def is_configured():
    global _configured
    if _configured is not None:
        return _configured
    if not (SUPABASE_URL and SUPABASE_KEY):
        _configured = False
        return False
    try:
        _get_client()
        _configured = True
    except Exception:
        _configured = False
    return _configured


def _get_client():
    global _client
    if _client is None:
        from supabase import create_client
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


_write_client = None


def _get_write_client():
    """Client para ESCRITURAS: usa SUPABASE_SERVICE_KEY (bypasa RLS) si disponible,
    de lo contrario degrada al client anon principal."""
    global _write_client
    key = SUPABASE_SERVICE_KEY or SUPABASE_KEY
    if _write_client is None:
        from supabase import create_client
        _write_client = create_client(SUPABASE_URL, key)
    return _write_client


def _now():
    return datetime.now().astimezone().isoformat()


# ---- USERS ----
def get_or_create_user(email, name=""):
    if is_configured():
        try:
            # Usa client de escritura si disponible (service_role bypasa RLS),
            # para poder insertar Y re-leer la fila con su id uuid real.
            c = _get_write_client()
            res = c.table("users").select("*").eq("email", email).execute()
            if res.data:
                return res.data[0]
            # No existe -> INSERT (service_role bypasa RLS)
            c.table("users").upsert(
                {"email": email, "name": name, "tier": "free", "usage_count": 0}
            ).execute()
            # Re-SELECT para obtener la fila con id uuid generado por DB
            res = c.table("users").select("*").eq("email", email).execute()
            if res.data:
                return res.data[0]
            if PERSIST_REQUIRED:
                raise RuntimeError(f"User {email} tidak bisa dipersist (select vacio)")
        except Exception:
            _configured = False
            if PERSIST_REQUIRED:
                raise
    return _local_user(email, name)


def update_tier(email, tier):
    if is_configured():
        try:
            _get_write_client().table("users").update({"tier": tier}).eq("email", email).execute()
            return
        except Exception:
            pass
    if email in _LUSER:
        _LUSER[email]["tier"] = tier


def _local_user(email, name=""):
    if email not in _LUSER:
        _LUSER[email] = {"email": email, "name": name or email,
                         "tier": "free", "usage_count": 0, "created_at": _now()}
    return dict(_LUSER[email])


# ---- CHAT SESSIONS ----
def list_sessions(email):
    if is_configured():
        try:
            c = _get_write_client()
            user = get_or_create_user(email)
            res = (c.table("chat_sessions").select("id,title,created_at")
                    .eq("user_id", user.get("id"))
                    .order("created_at", desc=True).execute())
            return res.data
        except Exception:
            _configured = False
    return _LSESS.get(email, [])


def create_session(email, title="Chat Baru"):
    if is_configured():
        try:
            wc = _get_write_client()
            user = get_or_create_user(email)
            res = wc.table("chat_sessions").insert(
                {"user_id": user.get("id"), "title": title}).execute()
            created = (res.data or [{}])[0]
            if created.get("id"):
                return created
            if PERSIST_REQUIRED:
                raise RuntimeError("Session tidak bisa dipersist (sin id)")
        except Exception:
            _configured = False
            if PERSIST_REQUIRED:
                raise
    _SEQ[0] += 1
    sid = "local_" + str(_SEQ[0])
    session = {"id": sid, "title": title, "user_email": email, "created_at": _now()}
    _LSESS.setdefault(email, []).insert(0, session)
    return session


def rename_session(email, session_id, title):
    """Update judul sesi (dipakai saat prompt pertama mengubah nama chat)."""
    if is_configured():
        try:
            c = _get_client()
            c.table("chat_sessions").update({"title": title}).eq("id", session_id).execute()
            return
        except Exception:
            _configured = False
    for s in _LSESS.get(email, []):
        if s["id"] == session_id:
            s["title"] = title
            return


# ---- CHAT MESSAGES ----
def get_messages(email, session_id):
    if is_configured():
        try:
            c = _get_write_client()
            res = (c.table("chat_messages").select("*")
                    .eq("session_id", session_id)
                    .order("created_at", desc=False).execute())
            return res.data
        except Exception:
            _configured = False
    return list(_LMSG.get((email, session_id), []))


def add_message(email, session_id, role, content):
    # Si Supabase está configurado, SIEMPRE escribir a Postgres (persistencia permanente).
    if is_configured():
        try:
            _get_write_client().table("chat_messages").insert(
                {"session_id": session_id, "role": role, "content": content}).execute()
            return
        except Exception:
            _configured = False
            if PERSIST_REQUIRED:
                raise  # fallo de escritura = error real (no "data amnesia" silencioso)
    key = (email, session_id)
    _LMSG.setdefault(key, []).append({"role": role, "content": content, "created_at": _now()})
# ---- USER INTEGRATIONS (Bring Your Own Key) ----
def save_integration(email, provider_name, api_token):
    """Simpan / perbarui API token untuk provider user (BYOK)."""
    if is_configured():
        try:
            c = _get_client()
            # Upsert: update bila ada, insert bila belum.
            existing = (c.table("user_integrations")
                        .select("id").eq("user_email", email)
                        .eq("provider_name", provider_name).execute())
            if existing.data:
                c.table("user_integrations").update({"api_token": api_token}).eq(
                    "id", existing.data[0]["id"]).execute()
            else:
                c.table("user_integrations").insert(
                    {"user_email": email, "provider_name": provider_name,
                     "api_token": api_token}).execute()
            return True
        except Exception:
            _configured = False
    _LINT[(email, provider_name)] = {"api_token": api_token, "updated_at": _now()}
    return True


def get_integration(email, provider_name):
    """Ambil API token milik user untuk provider tertentu."""
    if is_configured():
        try:
            c = _get_client()
            res = (c.table("user_integrations")
                   .select("*").eq("user_email", email)
                   .eq("provider_name", provider_name).execute())
            if res.data:
                return res.data[0]
            return None
        except Exception:
            _configured = False
    rec = _LINT.get((email, provider_name))
    return dict(rec) if rec else None


def list_integrations(email):
    """Daftar semua provider yang sudah di-save user."""
    if is_configured():
        try:
            c = _get_client()
            res = (c.table("user_integrations")
                   .select("provider_name,updated_at,api_token")
                   .eq("user_email", email).execute())
            return res.data
        except Exception:
            _configured = False
    return [
        {"provider_name": p, **data}
        for (em, p), data in _LINT.items() if em == email
    ]


def delete_integration(email, provider_name):
    """Hapus token provider milik user."""
    if is_configured():
        try:
            c = _get_client()
            c.table("user_integrations").delete().eq("user_email", email).eq(
                "provider_name", provider_name).execute()
            return
        except Exception:
            _configured = False
    _LINT.pop((email, provider_name), None)


def persistence_info():
    """Estado persistensi para health-check / logs.

    Returns:
        dict con status (persisted | degraded) y backend (supabase | memory).
    """
    if is_configured():
        return {"status": "persisted", "backend": "supabase", "url": SUPABASE_URL}
    return {"status": "degraded", "backend": "memory", "url": None}


# ---- WORKFLOWS (Visual AI Agent Workflow Builder) ----
def create_workflow(name: str, description: str, flow_data: dict):
    """Simpan workflow (nodes & edges como JSONB) a la tabla workflows."""
    if not is_configured():
        raise RuntimeError("Supabase belum dikonfigurasi — tidak dapat persist workflow.")
    c = _get_write_client()
    res = c.table("workflows").insert(
        {"name": name, "description": description, "flow_data": flow_data}
    ).execute()
    rows = res.data or []
    return rows[0] if rows else {}


def list_workflows():
    """Listar todos los workflows (creados_at desc)."""
    if not is_configured():
        return []
    c = _get_write_client()
    res = (
        c.table("workflows")
        .select("id,name,description,flow_data,created_at")
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []
# ---------------------------------------------------------------------------
# EXECUTION LOGS (Execution Engine)
# Tabla (Supabase SQL Editor):
#   executions(id uuid pk, workflow_id uuid, status text default 'pending',
#              created_at timestamptz default now());
#   execution_logs(id uuid pk, execution_id uuid ref executions(id) on delete cascade,
#                  node_id text, step_kind text, status text, payload jsonb,
#                  created_at timestamptz default now());
# ---------------------------------------------------------------------------
_L_EXEC = {}  # execution_id -> {"workflow_id", "status", "created_at"}
_L_EXLOG = {}  # execution_id -> [ {node_id, step_kind, status, payload, ts} ]


def create_execution(execution_id: str, workflow_id: str, flow_data: dict):
    """Crea un registro de ejecucion (status pending)."""
    if is_configured():
        try:
            _get_write_client().table("executions").insert(
                {"id": execution_id, "workflow_id": workflow_id, "status": "pending"}
            ).execute()
            return
        except Exception:
            _configured = False
            if PERSIST_REQUIRED:
                pass  # no bloquear ejecucion por falta de log (best-effort)
    _L_EXEC[execution_id] = {"workflow_id": workflow_id, "status": "pending", "created_at": _now()}


def append_execution_log(execution_id: str, node_id: str, step_kind: str, status: str, payload: dict):
    """Persiste un paso de ejecucion en execution_logs."""
    if is_configured():
        try:
            _get_write_client().table("execution_logs").insert(
                {
                    "execution_id": execution_id,
                    "node_id": node_id,
                    "step_kind": step_kind,
                    "status": status,
                    "payload": payload or {},
                }
            ).execute()
            return
        except Exception:
            _configured = False
    _L_EXLOG.setdefault(execution_id, []).append(
        {"node_id": node_id, "step_kind": step_kind, "status": status, "payload": payload or {}, "ts": _now()}
    )


def update_execution_status(execution_id: str, status: str):
    """Actualiza el estado final de una ejecucion."""
    if is_configured():
        try:
            _get_write_client().table("executions").update({"status": status}).eq(
                "id", execution_id).execute()
            return
        except Exception:
            _configured = False
    if execution_id in _L_EXEC:
        _L_EXEC[execution_id]["status"] = status


def get_execution(execution_id: str):
    """Obtiene el estado y logs de una ejecucion."""
    if is_configured():
        try:
            c = _get_write_client()
            ex = c.table("executions").select("*").eq("id", execution_id).execute()
            logs = (c.table("execution_logs").select("*")
                    .eq("execution_id", execution_id)
                    .order("created_at", desc=False).execute())
            return {"execution": (ex.data or [None])[0], "logs": logs.data or []}
        except Exception:
            _configured = False
    return {"execution": _L_EXEC.get(execution_id), "logs": _L_EXLOG.get(execution_id, [])}