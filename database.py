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
from fastapi import HTTPException

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
# Railway memakai nama SUPABASE_SERVICE_ROLE_KEY, lokal memakai SUPABASE_SERVICE_KEY.
# Dukung KEDUANYA (alias) supaya tidak 503 misterius hanya karena beda nama env.
SUPABASE_SERVICE_KEY = (
    (os.getenv("SUPABASE_SERVICE_KEY") or "").strip()
    or (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
)

# Fallback lokal bila Supabase belum dikonfigurasi / gagal
_LUSER = {}
_LSESS = {}
_LMSG = {}
_LINT = {}      # (email, provider) -> {"api_token":..., "updated_at":...}
_LVAULT = {}    # email -> {provider: encrypted_key}   (in-memory vault fallback)
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
    """Client para ESCRITURAS: usa SUPABASE_SERVICE_KEY (bypasa RLS).

    Fase 2a (fail-fast): TIDAK ada lagi degradasi diam-diam ke anon key.
    Kalau SERVICE_KEY belum di-set -> raise RuntimeError dengan pesan jelas,
    supaya log Railway langsung menunjukkan root cause (bukan RLS 500 misterius).
    """
    global _write_client
    key = SUPABASE_SERVICE_KEY
    if not key:
        raise RuntimeError(
            "SUPABASE_SERVICE_KEY belum di-set — operasi tulis akan kena RLS. "
            "Set variabel ini di Railway Variables (service_role key dari Supabase)."
        )
    if _write_client is None:
        from supabase import create_client
        _write_client = create_client(SUPABASE_URL, key)
    return _write_client


def _map_api_error(exc, context):
    """Convert postgrest APIError -> HTTPException dengan status yang sesuai.

    Fase 2b: RLS denial -> 503 (backend misconfigured), FK violation -> 409,
    lainnya -> 503. Pesan asli (dipotong 300 char, tanpa secret — hanya pesan
    PostgREST) ikut di detail supaya root cause TERBACA di respons E2E tanpa
    perlu buka dashboard Railway.
    """
    msg = str(exc)
    code = getattr(exc, "code", "") or ""
    print(f"[{context}] Supabase APIError code={code} msg={msg[:500]}")
    low = (msg + " " + str(code)).lower()
    if "row-level security" in low or "rls" in low.split() or "42501" in low:
        raise HTTPException(503, f"Backend misconfigured (RLS memblokir {context}).")
    if "foreign key" in low or "23503" in low:
        raise HTTPException(409, f"FK constraint gagal saat {context}.")
    if "duplicate" in low or "unique" in low or "23505" in low:
        raise HTTPException(409, f"Duplikat saat {context}.")
    detail = (msg[:300] or type(exc).__name__).replace("\n", " ")
    raise HTTPException(503, f"Supabase error saat {context} [{code or '?'}]: {detail}.")


def _wrap_write(fn, context):
    """Bungkus pemanggilan .execute(): APIError -> HTTPException terpetakan,
    exception lain -> propagate (akan di-log full stack di endpoint)."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        # HTTPException yang sudah dipetakan: teruskan apa adanya.
        if isinstance(exc, (HTTPException, RuntimeError)):
            raise
        try:
            from postgrest.exceptions import APIError
            if isinstance(exc, APIError):
                _map_api_error(exc, context)
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001
            pass
        print(f"[{context}] {type(exc).__name__}: {str(exc)[:500]}")
        raise


def _now():
    return datetime.now().astimezone().isoformat()


# ---- USERS ----
def get_or_create_user(email, name="", auth_id=None):
    """Resolve baris public.users dari email.

    Aturan kanonis (anti-hang): JANGAN PERNAH UPDATE users.id.
    Mengubah PK yang dirujuk FK chat_sessions dapat mengunci/memacetkan
    request (gejala: /chat menggantung ~25-30s lalu tanpa respons).
    Sebagai gantinya, fungsi ini mengembalikan baris apa adanya;
    pemanggil memakai row["id"] untuk semua FK (lihat create_session).
    auth_id hanya dipakai saat INSERT baris baru (id = auth.users.id).
    """
    if is_configured():
        try:
            # Usa client de escritura si disponible (service_role bypasa RLS),
            # para poder insertar Y re-leer la fila con su id uuid real.
            c = _get_write_client()
            res = _wrap_write(
                lambda: c.table("users").select("*").eq("email", email).execute(),
                "users.select",
            )
            if res.data:
                return res.data[0]
            # No existe -> INSERT dengan id = auth.users.id bila diketahui
            # (skema FK chat_sessions.user_id -> users.id; auth_id menjamin valid).
            payload = {"email": email, "name": name, "tier": "free", "usage_count": 0}
            if auth_id:
                payload["id"] = auth_id
            _wrap_write(
                lambda: c.table("users").upsert(payload).execute(),
                "users.upsert",
            )
            # Re-SELECT para obtener la fila con id uuid generado por DB
            res = _wrap_write(
                lambda: c.table("users").select("*").eq("email", email).execute(),
                "users.reselect",
            )
            if res.data:
                return res.data[0]
            if PERSIST_REQUIRED:
                raise RuntimeError(f"User {email} tidak bisa dipersist (select vacio)")
        except (HTTPException, RuntimeError):
            raise
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
def _resolve_user_id(owner, auth_id=None):
    """owner bisa user_id uuid ATAU email. Resolve ke user_id KANONIS.

    Aturan anti-FK-409: user_id kanonis = public.users.id yang SUDAH ADA
    di DB (hasil get_or_create_user), BUKAN auth.users.id (JWT sub) secara
    membabi-buta. Baris lama (uuid generate sendiri) tetap valid sebagai
    target FK selama kita memakai id dari baris itu sendiri.
    """
    if not owner:
        return auth_id or owner
    owner = str(owner)
    if "@" in owner:
        u = get_or_create_user(owner, auth_id=auth_id or None)
        return (u.get("id") if u else None) or auth_id
    # owner sudah uuid: itu diasumsikan id kanonis dari sesi login lama /
    # session yang sudah ada. auth_id HANYA dipakai bila owner kosong.
    # (Jangan timpa uuid owner dengan JWT sub — itu yang menyebabkan FK 409
    # untuk user lama yang baris users.id-nya berbeda dari auth id.)
    return owner


def list_sessions(owner):
    # FIX Bug1 (Issue #29 / PR #28): read path TIDAK pernah throw -> 500.
    # _resolve_user_id di-move ke DALAM try. APIError/None -> return [] (200).
    if not is_configured():
        return []
    try:
        uid = _resolve_user_id(owner)
        if not uid:
            return []
        c = _get_write_client()
        res = (c.table("chat_sessions").select("id,title,created_at")
               .eq("user_id", uid)
               .order("created_at", desc=True).execute())
        return res.data or []
    except Exception as exc:
        print(f"[list_sessions] {type(exc).__name__}: {str(exc)[:300]}")
        return []


def create_session(owner, title="Chat Baru", auth_id=None, email=None):
    # Aturan kanonis: user_id yang di-insert = public.users.id yang SUDAH
    # ADA (hasil ensure baris via email). Untuk user lama (uuid generate
    # sendiri), itu berarti id lama — valid untuk FK. auth_id dipakai hanya
    # untuk INSERT baris baru (via get_or_create_user), bukan untuk menimpa.
    if email and ("@" in str(email)):
        try:
            ensured = get_or_create_user(str(email), auth_id=auth_id or None)
            if ensured and ensured.get("id"):
                uid = ensured["id"]
            else:
                uid = _resolve_user_id(owner, auth_id=auth_id) if auth_id else _resolve_user_id(owner)
        except (HTTPException, RuntimeError):
            raise
        except Exception:
            uid = _resolve_user_id(owner, auth_id=auth_id) if auth_id else _resolve_user_id(owner)
    else:
        uid = _resolve_user_id(owner, auth_id=auth_id) if auth_id else _resolve_user_id(owner)
    if is_configured() and uid:
        try:
            wc = _get_write_client()
            res = _wrap_write(
                lambda: wc.table("chat_sessions").insert(
                    {"user_id": uid, "title": title}).execute(),
                "chat_sessions.insert",
            )
            created = (res.data or [{}])[0]
            if created.get("id"):
                return created
            if PERSIST_REQUIRED:
                raise RuntimeError("Session tidak bisa dipersist (sin id)")
        except (HTTPException, RuntimeError):
            raise
        except Exception:
            _configured = False
            if PERSIST_REQUIRED:
                raise
    _SEQ[0] += 1
    sid = "local_" + str(_SEQ[0])
    session = {"id": sid, "title": title, "user_id": (uid or owner), "created_at": _now()}
    return session


def rename_session(owner, session_id, title):
    """Update judul sesi (dipakai saat prompt pertama mengubah nama chat)."""
    uid = _resolve_user_id(owner)
    if is_configured() and uid:
        try:
            c = _get_client()
            c.table("chat_sessions").update({"title": title}).eq("id", session_id).eq(
                "user_id", uid).execute()
            return
        except Exception:
            _configured = False
    return


# ---- CHAT SESSIONS: DELETE ----
def delete_session(owner, session_id):
    """Hapus sesi milik user (chat_messages ikut ter-cascade via FK). Return bool."""
    if not is_configured() or not session_id:
        return False
    try:
        uid = _resolve_user_id(owner)
        if not uid:
            return False
        wc = _get_write_client()
        # Verifikasi kepemilikan: sesi harus milik user ini (anti-spoof).
        own = (wc.table("chat_sessions").select("id")
               .eq("id", session_id).eq("user_id", uid).limit(1).execute())
        if not (own.data or []):
            return False
        wc.table("chat_sessions").delete().eq("id", session_id).eq("user_id", uid).execute()
        return True
    except Exception as exc:
        print(f"[delete_session] {type(exc).__name__}: {str(exc)[:300]}")
        return False


# ---- CHAT MESSAGES ----
def get_messages(owner, session_id):
    # FIX Bug1: TIDAK pernah throw -> 500. APIError/None -> return [] (200).
    if not is_configured() or not session_id:
        return []
    try:
        uid = _resolve_user_id(owner)
        if not uid:
            return []
        c = _get_write_client()
        # Verifikasi kepemilikan session BUKAN spoof: session harus milik user.
        own = (c.table("chat_sessions").select("id")
               .eq("id", session_id).eq("user_id", uid).limit(1).execute())
        if not (own.data or []):
            return []
        res = (c.table("chat_messages").select("*")
               .eq("session_id", session_id)
               .order("created_at", desc=False).execute())
        return res.data or []
    except Exception as exc:
        print(f"[get_messages] {type(exc).__name__}: {str(exc)[:300]}")
        return []


def find_user_message_by_request(client_request_id):
    """Idempotensi (openclaw #69266): sudah ada user-pesan untuk kiriman logis ini?
    Kembalikan baris pertama (role=user) yg membawa client_request_id tsb, atau None."""
    if not is_configured() or not client_request_id or not _request_key_enabled():
        return None
    try:
        wc = _get_write_client()
        res = _wrap_write(
            lambda: wc.table("chat_messages")
            .select("id, session_id, role, content")
            .eq("client_request_id", client_request_id)
            .eq("role", "user")
            .limit(1).execute(),
            "chat_messages.idem_find",
        )
        return (res.data or [None])[0]
    except Exception as exc:
        print(f"[find_user_message_by_request] {type(exc).__name__}: {str(exc)[:200]}")
        return None


def get_last_assistant_reply(session_id):
    """Reply assistant terakhir untuk sesi — dipakai saat deteksi kiriman yg sudah
    diproses, supaya retry mengembalikan reply yg sama (TANPA menjalankan ulang loop)."""
    if not is_configured() or not session_id:
        return None
    try:
        wc = _get_write_client()
        res = _wrap_write(
            lambda: wc.table("chat_messages")
            .select("content")
            .eq("session_id", session_id)
            .eq("role", "assistant")
            .order("created_at", desc=True).limit(1).execute(),
            "chat_messages.last_reply",
        )
        rows = res.data or []
        return rows[0]["content"] if rows else None
    except Exception as exc:
        print(f"[get_last_assistant_reply] {type(exc).__name__}: {str(exc)[:200]}")
        return None


# Feature-detect kolom client_request_id (migration 2026_dedupe_chat_messages.sql).
# Bila kolom/index belum ada di DB, idempotensi MENURUN jadi no-op (insert normal)
# supaya app TETAP berjalan walau migration belum di-apply (deploy tidak 500).
# Setelah dipastikan kolom ada, isi cache dan aktifkan jalur idempoten.
_req_key = {"checked": False, "enabled": False}


def _request_key_enabled() -> bool:
    if _req_key["checked"]:
        return _req_key["enabled"]
    enabled = False
    if is_configured():
        try:
            c = _get_write_client()
            c.table("chat_messages").select("client_request_id").limit(0).execute()
            enabled = True
        except Exception:
            enabled = False
    _req_key["checked"] = True
    _req_key["enabled"] = enabled
    return enabled


def add_message(owner, session_id, role, content, auth_id=None, client_request_id=None):
    # owner bisa email ATAU user_id. Resolve ke id KANONIS (baris users yang
    # ada) supaya insert chat_messages selalu menunjuk session yang valid.
    # Kepemilikan dicek terhadap uid kanonis — BUKAN auth_id mentah — supaya
    # user lama (users.id != JWT sub) tetap bisa menulis ke session miliknya.
    # Si Supabase está configurado, SIEMPRE escribir a Postgres (persistencia permanente).
    if is_configured():
        try:
            wc = _get_write_client()
            uid = _resolve_user_id(owner, auth_id=auth_id) if auth_id else _resolve_user_id(owner)
            # Validasi kepemilikan session terhadap uid kanonis
            # (cegah user A menulis ke session user B).
            if uid:
                own = _wrap_write(
                    lambda: wc.table("chat_sessions").select("id")
                    .eq("id", session_id).eq("user_id", uid).limit(1).execute(),
                    "chat_sessions.own_check",
                )
                if not (own.data or []):
                    raise HTTPException(403, "Session bukan milik user.")
            # Idempotensi user-pesan: bila client_request_id sudah tercatat utk
            # role user, JANGAN insert lagi (retry/double-fire) -> return False.
            # Hanya aktif bila kolom+index ada (feature-detected) — jika migration
            # belum di-apply, kolom tidak ada -> skip guard, insert normal (no-op).
            if client_request_id and role == "user" and _request_key_enabled():
                existed = _wrap_write(
                    lambda: wc.table("chat_messages").select("id")
                    .eq("client_request_id", client_request_id).eq("role", "user")
                    .limit(1).execute(),
                    "chat_messages.idem_check",
                )
                if existed.data:
                    return False
            row = {"session_id": session_id, "role": role, "content": content}
            if client_request_id and _request_key_enabled():
                row["client_request_id"] = client_request_id
            _wrap_write(
                lambda: wc.table("chat_messages").insert(row).execute(),
                "chat_messages.insert",
            )
            return True
        except HTTPException:
            raise  # 403 ownership — harus tetap memblokir
        except Exception as exc:
            # Unique-violation pada index client_request_id = kiriman sudah tercatat
            # (race antar-dua request paralel) -> idempoten, jangan gagalkan request.
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                return False
            _configured = False
            if PERSIST_REQUIRED:
                raise  # fallo de escritura = error real (no "data amnesia" silencioso)
    key = (owner, session_id)
    _LMSG.setdefault(key, []).append({"role": role, "content": content, "created_at": _now()})
    return True
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


# ---- ZERO-KNOWLEDGE VAULT (user_vault) ----
def vault_save(email: str, provider: str, encrypted_key: str) -> bool:
    """Upsert ciphertext key tauluun user_vault (PK: email+provider)."""
    try:
        if is_configured():
            c = _get_write_client()
            ex = c.table("user_vault").select("provider").eq("email", email).eq(
                "provider", provider).limit(1).execute()
            if (getattr(ex, "data", None) or []):
                c.table("user_vault").update({"encrypted_key": encrypted_key}).eq(
                    "email", email).eq("provider", provider).execute()
            else:
                c.table("user_vault").insert({"email": email,
                                              "provider": provider,
                                              "encrypted_key": encrypted_key}).execute()
            return True
    except Exception:
        pass
    # Fallback in-memory (ei persist restartin yli, vain demo).
    _LVAULT.setdefault(email, {})[provider] = encrypted_key
    return True


def vault_get(email: str, provider: str) -> str:
    """Palauta encrypted_key (ciphertext) user_vault:lta. '' jos ei löydy."""
    try:
        if is_configured():
            res = _get_write_client().table("user_vault").select("encrypted_key").eq(
                "email", email).eq("provider", provider).limit(1).execute()
            d = (getattr(res, "data", None) or [])
            if d:
                return str(d[0].get("encrypted_key") or "")
            return ""
    except Exception:
        pass
    return _LVAULT.get(email, {}).get(provider, "")


def vault_list(email: str) -> list[dict]:
    """Palauta daftar provider jolle säilytetty (ei koskaan plaintext avainta)."""
    try:
        if is_configured():
            res = (_get_write_client().table("user_vault").select("provider")
                   .eq("email", email).execute())
            return [{"provider": d.get("provider"), "saved": True}
                    for d in (getattr(res, "data", None) or [])]
    except Exception:
        pass
    return [{"provider": p, "saved": True} for p in _LVAULT.get(email, {})]


def persistence_info():
    """Estado persistensi para health-check / logs.

    Returns:
        dict con status (persisted | degraded) y backend (supabase | memory).
    """
    if is_configured():
        return {"status": "persisted", "backend": "supabase", "url": SUPABASE_URL}
    return {"status": "degraded", "backend": "memory", "url": None}


# ---- WORKFLOWS (Visual AI Agent Workflow Builder) ----
# NOTE keamanan: setiap workflow WAJIB punya user_id (owner). Semua query
# di-scope dengan user_id supaya service_role/bypass RLS tidak membocorkan
# data antar-user (defense-in-depth: RLS di DB + filter user di backend).
def create_workflow(user_id: str, name: str, description: str, flow_data: dict):
    """Simpan workflow (nodes & edges como JSONB) a la tabla workflows.

    user_id diisi dari JWT (di api_server), BUKAN dari body request.
    """
    if not is_configured():
        raise RuntimeError("Supabase belum dikonfigurasi — tidak dapat persist workflow.")
    c = _get_write_client()
    res = c.table("workflows").insert(
        {"user_id": user_id, "name": name, "description": description, "flow_data": flow_data}
    ).execute()
    rows = res.data or []
    return rows[0] if rows else {}


def list_workflows(user_id: str):
    """Listar workflows milik EXPLICIT user (created_at desc).

    Filter user_id = defense-in-depth, walau RLS sudah aktif.
    """
    if not is_configured():
        return []
    c = _get_write_client()
    res = (
        c.table("workflows")
        .select("id,name,description,flow_data,created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


def get_workflow_owner(workflow_id: str) -> str | None:
    """Return user_id pemilik workflow, atau None bila workflow tak ada."""
    if not is_configured():
        return None
    try:
        c = _get_write_client()
        res = (c.table("workflows").select("user_id").eq("id", workflow_id)
               .limit(1).execute())
        d = res.data or []
        return str(d[0].get("user_id")) if d else None
    except Exception:  # noqa: BLE001
        return None
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


_LBAL={}

def get_balance(email):
 try:
  if is_configured():
   r=_get_client().table('user_balances').select('balance').eq('email',email).limit(1).execute()
   d=getattr(r,'data',None) or []
   return float(d[0].get('balance',0) or 0) if d else 0.0
 except Exception:
  pass
 return float(_LBAL.get(email,0.0))

def topup_balance(email,amt):
 try:
  if is_configured():
   cur=get_balance(email)
   c=_get_write_client()
   ex=c.table('user_balances').select('email').eq('email',email).limit(1).execute()
   dd=getattr(ex,'data',None) or []
   nb=cur+float(amt)
   (c.table('user_balances').update({'balance':nb}).eq('email',email).execute() if dd else c.table('user_balances').insert({'email':email,'balance':nb}).execute())
   return nb
 except Exception:
  pass
 _LBAL[email]=float(_LBAL.get(email,0.0))+float(amt)
 return _LBAL[email]

def deduct_balance(email,amt):
 b=get_balance(email)
 if b < float(amt): return None
 return topup_balance(email,-float(amt))
