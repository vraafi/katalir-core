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
from datetime import datetime, timedelta, timezone

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
_LWORKFLOW = {}  # workflow_id -> row (fallback memori saat Supabase tidak aktif)
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
    """Set tier user (kanonik di `public.users.tier`).

    RAISE bila DB terkonfigurasi tapi penulisan gagal. Dulu `except: pass`
    menelan kegagalan sehingga webhook pembayaran membalas SUKSES padahal tier
    tidak berubah -- user sudah bayar tetapi tetap "free" (temuan audit billing).
    `UPDATE` pada email yang tidak ada memengaruhi 0 baris TANPA error, jadi
    baris user dipastikan ada lebih dulu.
    """
    if is_configured():
        get_or_create_user(email)
        _get_write_client().table("users").update({"tier": tier}).eq("email", email).execute()
        return
    _local_user(email)
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
        # LIMIT defensif (depth cap): sidebar riwayat cuma perlu daftar terbaru.
        # PostgREST + index user_id membuat besar daftar tetap cepat (lihat
        # migration 2026_backend_indexes.sql), tapi robust walau user 1000+ reset.
        res = (c.table("chat_sessions").select("id,title,created_at")
              .eq("user_id", uid)
              .order("created_at", desc=True).limit(100).execute())
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
    """Ambil API token milik user untuk provider tertentu.

    FASE 2.3 — urutan sumber (kompatibel mundur):
      1. `user_integrations` (kolom plaintext, jalur BYOK lama);
      2. `user_vault` (ciphertext Fernet, jalur form kredensial di chat).
    Tool di `tools.py` memanggil fungsi ini, jadi tanpa fallback ke-2 kredensial
    yang user isi lewat form chat (terenkripsi) tidak akan pernah ditemukan —
    flow akan meminta token berulang-ulang.
    """
    if is_configured():
        try:
            c = _get_client()
            res = (c.table("user_integrations")
                   .select("*").eq("user_email", email)
                   .eq("provider_name", provider_name).execute())
            if res.data:
                return res.data[0]
        except Exception:
            _configured = False
    rec = _LINT.get((email, provider_name))
    if rec:
        return dict(rec)
    return _vault_integration(email, provider_name)


def _vault_integration(email, provider_name):
    """Baris bentuk `user_integrations` dari Brankas (didekripsi) atau None.

    Nilai plaintext HANYA hidup di memori proses pemanggil (untuk mengisi header
    request ke provider); ia tidak pernah dikembalikan lewat API maupun ke model.
    """
    try:
        cipher = vault_get(email, provider_name)
        if not cipher:
            return None
        import vault_security as vs
        token = vs.decrypt_key(cipher)
        if not token:
            return None
        return {"user_email": email, "provider_name": provider_name,
                "api_token": token, "source": "vault"}
    except Exception as exc:  # kunci vault berubah / cryptography tak ada
        print(f"[database] vault tidak terbaca untuk {provider_name}: "
              f"{type(exc).__name__}")
        return None



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


def vault_delete(email: str, provider: str) -> bool:
    """Hapus kredensial user untuk satu provider (Brankas + tabel BYOK).

    KENAPA ADA: tanpa ini user TIDAK bisa mencabut kredensial yang sudah
    tersimpan — hanya bisa menimpanya. `user_integrations` (jalur lama) ikut
    dibersihkan supaya tidak ada sisa token yang masih terbaca tool.
    """
    removed = False
    try:
        if is_configured():
            c = _get_write_client()
            c.table("user_vault").delete().eq("email", email).eq(
                "provider", provider).execute()
            c.table("user_integrations").delete().eq("user_email", email).eq(
                "provider_name", provider).execute()
            removed = True
    except Exception as exc:  # noqa: BLE001
        print(f"[database] vault_delete gagal ({type(exc).__name__})")
    _LVAULT.get(email, {}).pop(provider, None)
    _LINT.pop((email, provider), None)
    return removed


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
    """INSERT workflow BARU (nodes & edges sebagai JSONB).

    user_id diisi dari JWT (di api_server), BUKAN dari body request.
    Untuk menyimpan ULANG workflow yang sudah ada, pakai `update_workflow`
    (dulu POST selalu INSERT → setiap klik "Simpan Alur" menumpuk baris baru
    bernama sama; itu akar duplikat di sidebar).
    """
    if not is_configured():
        import uuid as _uuid
        wid = "local-" + _uuid.uuid4().hex[:12]
        row = {"id": wid, "user_id": user_id, "name": name,
               "description": description, "flow_data": flow_data or {},
               "created_at": _now()}
        _LWORKFLOW[wid] = row
        return dict(row)
    c = _get_write_client()
    res = c.table("workflows").insert(
        {"user_id": user_id, "name": name, "description": description, "flow_data": flow_data}
    ).execute()
    rows = res.data or []
    return rows[0] if rows else {}


def update_workflow(workflow_id: str, user_id: str, name: str | None = None,
                    description: str | None = None, flow_data: dict | None = None):
    """UPDATE workflow yang SUDAH ada, HANYA bila milik `user_id`.

    Mengembalikan row terbaru, atau None bila tidak ada / bukan milik user
    (pemanggil yang memutuskan 404 vs 403).
    """
    patch = {}
    if name is not None:
        patch["name"] = name
    if description is not None:
        patch["description"] = description
    if flow_data is not None:
        patch["flow_data"] = flow_data
    if not patch:
        return get_workflow(workflow_id, user_id)
    if not is_configured():
        row = _LWORKFLOW.get(workflow_id)
        if not row or str(row.get("user_id")) != str(user_id):
            return None
        row.update(patch)
        return dict(row)
    c = _get_write_client()
    res = (c.table("workflows").update(patch)
           .eq("id", workflow_id).eq("user_id", user_id).execute())
    rows = res.data or []
    return rows[0] if rows else None


def get_workflow(workflow_id: str, user_id: str):
    """Detail SATU workflow (termasuk flow_data), hanya bila milik `user_id`."""
    if not is_configured():
        row = _LWORKFLOW.get(workflow_id)
        if row and str(row.get("user_id")) == str(user_id):
            return dict(row)
        return None
    c = _get_write_client()
    res = (c.table("workflows").select("*")
           .eq("id", workflow_id).eq("user_id", user_id).limit(1).execute())
    rows = res.data or []
    return rows[0] if rows else None


def delete_workflow(workflow_id: str, user_id: str) -> bool:
    """Hapus workflow MILIK `user_id` saja. True bila ada baris terhapus."""
    if not is_configured():
        row = _LWORKFLOW.get(workflow_id)
        if row and str(row.get("user_id")) == str(user_id):
            del _LWORKFLOW[workflow_id]
            return True
        return False
    c = _get_write_client()
    res = (c.table("workflows").delete()
           .eq("id", workflow_id).eq("user_id", user_id).execute())
    return bool(res.data)


def count_nodes(flow_data) -> int:
    """Jumlah node dari flow_data apa pun bentuknya (tahan nilai rusak)."""
    if not isinstance(flow_data, dict):
        return 0
    nodes = flow_data.get("nodes")
    return len(nodes) if isinstance(nodes, list) else 0


def list_workflows(user_id: str, include_flow: bool = False):
    """Listar workflows milik user (created_at desc).

    `include_flow=False` (default) mengembalikan METADATA saja -- `flow_data`
    TIDAK ikut. Dulu list selalu membawa `flow_data` penuh untuk SEMUA workflow
    (payload besar), padahal frontend hanya butuh isi graf saat membuka SATU
    workflow (ambil lewat GET /workflows/{id}).

    `node_count` sengaja TIDAK ada di list: menghitungnya butuh membaca
    `flow_data` (mengembalikan payload yang sedang kita buang) atau kolom
    generated yang berarti perubahan skema. Sidebar hanya butuh nama.
    """
    if not is_configured():
        rows = [dict(r) for r in _LWORKFLOW.values()
                if str(r.get("user_id")) == str(user_id)]
        rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    else:
        c = _get_write_client()
        sel = "id,name,description,flow_data,created_at" if include_flow else "id,name,description,created_at"
        res = (
            c.table("workflows")
            .select(sel)
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        rows = res.data or []
    if include_flow:
        return [dict(r) for r in rows]
    out = []
    for r in rows:
        row = dict(r)
        row.pop("flow_data", None)
        out.append(row)
    return out



def get_workflow_owner(workflow_id: str) -> str | None:
    """Return user_id pemilik workflow, atau None bila workflow tak ada.

    Jalur memori WAJIB mengembalikan pemilik sebenarnya juga: kalau tidak,
    backend tidak bisa membedakan "tidak ada" dari "milik orang lain"
    (sebelumnya selalu None -> akses lintas user dilaporkan 404, bukan 403,
    sehingga tes/observability kehilangan sinyal ada-tidaknya kepemilikan).
    """
    if not is_configured():
        row = _LWORKFLOW.get(workflow_id)
        return str(row.get("user_id")) if row else None
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


# Kolom ASLI tabel `execution_logs` (dibaca dari PostgREST OpenAPI Supabase):
#   id, execution_id, node_id, node_type, status, output_data, error_message,
#   started_at, finished_at
# Versi lama menulis `step_kind` + `payload` yang TIDAK ADA di skema, sehingga
# SETIAP insert gagal 400 dan log hanya tersisa di memori proses — itulah sebab
# `GET /executions/{id}` selalu "belum ada langkah" walau workflow sudah jalan.
EXECUTION_LOG_COLUMNS = ("execution_id", "node_id", "node_type", "status",
                         "output_data", "error_message", "started_at",
                         "finished_at")


def execution_log_row(execution_id: str, node_id: str, step_kind: str,
                      status: str, payload: dict) -> dict:
    """Baris `execution_logs` sesuai skema nyata (murni, mudah diuji).

    `step_kind` dipetakan ke `node_type`, `payload` ke `output_data`, dan pesan
    error dipromosikan ke kolomnya sendiri supaya bisa dicari/diindeks.
    """
    data = payload if isinstance(payload, dict) else {"output": payload}
    row: dict = {
        "execution_id": execution_id,
        "node_id": node_id,
        "node_type": step_kind,
        "status": status,
        "output_data": data,
    }
    err = data.get("error")
    if err:
        row["error_message"] = str(err)[:500]
    stamp = datetime.now(timezone.utc).isoformat()
    if status == "running":
        row["started_at"] = stamp
    else:
        row["finished_at"] = stamp
    return row


def _normalize_log(row: dict) -> dict:
    """Baris DB -> bentuk yang dipakai laporan ({node_id, status, payload}).

    Membuat `execution_report` tidak perlu tahu nama kolom fisik, dan tetap
    menerima baris gaya lama (kalau ada sisa di memori).
    """
    if not isinstance(row, dict):
        return row
    if "output_data" not in row and "node_type" not in row:
        return row                      # sudah bentuk lama (memori)
    payload = row.get("output_data") or {}
    if row.get("error_message"):
        if isinstance(payload, dict):
            payload = {**payload, "error": row["error_message"]}
        else:
            payload = {"output": payload, "error": row["error_message"]}
    return {
        "node_id": row.get("node_id"),
        "step_kind": row.get("node_type"),
        "status": row.get("status"),
        "payload": payload,
        "ts": row.get("finished_at") or row.get("started_at"),
    }


def append_execution_log(execution_id: str, node_id: str, step_kind: str, status: str, payload: dict):
    """Persiste un paso de ejecucion en execution_logs (kolom sesuai skema).

    Sama seperti `get_execution`: kegagalan tulis tidak mematikan `_configured`
    secara global (satu kegagalan akan mengalihkan SEMUA penulisan berikutnya ke
    memori sehingga log hilang dari DB tanpa jejak).
    """
    row = execution_log_row(execution_id, node_id, step_kind, status, payload)
    try:
        if is_configured():
            _get_write_client().table("execution_logs").insert(row).execute()
            return
    except Exception as exc:  # noqa: BLE001
        print(f"[database] append_execution_log gagal ({type(exc).__name__}); "
              "disimpan di memori")
    _L_EXLOG.setdefault(execution_id, []).append(
        {"node_id": node_id, "step_kind": step_kind, "status": status, "payload": payload or {}, "ts": _now()}
    )


def update_execution_status(execution_id: str, status: str):
    """Actualiza el estado final de una ejecucion (tanpa mematikan `_configured`)."""
    try:
        if is_configured():
            _get_write_client().table("executions").update({"status": status}).eq(
                "id", execution_id).execute()
            return
    except Exception as exc:  # noqa: BLE001
        print(f"[database] update_execution_status gagal ({type(exc).__name__})")
    if execution_id in _L_EXEC:
        _L_EXEC[execution_id]["status"] = status


def get_execution(execution_id: str):
    """Obtiene el estado y logs de una ejecucion.

    CATATAN (FASE 2.5): kegagalan BACA di sini TIDAK lagi mematikan flag global
    `_configured`. Sebelumnya satu error baca (mis. RLS/timeout sesaat) membuat
    seluruh proses beralih ke memori: baris `executions` tak terbaca (status
    `None`) dan `append_execution_log` berikutnya menulis ke memori saja —
    log terpisah dari DB tanpa pesan error. Sekarang penurunan itu hanya
    berlaku untuk panggilan ini.
    """
    try:
        if is_configured():
            c = _get_write_client()
            ex = c.table("executions").select("*").eq("id", execution_id).execute()
            logs = (c.table("execution_logs").select("*")
                    .eq("execution_id", execution_id).execute())
            # Urutan dihitung di Python: `execution_logs` TIDAK punya kolom
            # `created_at`, jadi `.order("created_at")` membuat SELURUH pembacaan
            # gagal 400 (dan status eksekusi selalu terlihat None).
            rows = [_normalize_log(r) for r in (logs.data or [])]
            rows.sort(key=lambda r: str((r or {}).get("ts") or ""))
            return {"execution": (ex.data or [None])[0], "logs": rows}
    except Exception as exc:  # noqa: BLE001
        print(f"[database] get_execution gagal ({type(exc).__name__}); "
              "pakai salinan memori")
    return {"execution": _L_EXEC.get(execution_id), "logs": _L_EXLOG.get(execution_id, [])}


_LBAL={}

def get_balance(email):
 """Saldo kredit user.

 KOLOM ASLI = `credit_balance`. Kode lama membaca/menulis `balance` yang TIDAK
 ADA di `user_balances` (skema: email, credit_balance, tier), sehingga setiap
 query gagal 400 dan `except: pass` mengembalikan saldo dari MEMORI proses --
 saldo yang terlihat user tidak pernah berasal dari DB (temuan audit billing).

 KLIEN BACA = service (sama seperti tulis). Regresi yang terbukti di produksi
 2026-09-18: dengan klien anon, RLS membuat hasil baca SELALU kosong -> saldo
 terbaca 0 -> setiap topup MENIMPA alih-alih menjumlah, dan refund menghasilkan
 saldo negatif (5000000 + refund 2000000 -> -2000000, bukan 3000000).

 RAISE bila DB terkonfigurasi tapi query gagal; pemanggil yang memang ingin
 tahan-gagal (mis. execution_engine) sudah membungkusnya dengan try/except.
 """
 if is_configured():
  c = _get_write_client() if SUPABASE_SERVICE_KEY else _get_client()
  r = (c.table('user_balances').select('credit_balance')
       .eq('email', email).limit(1).execute())
  d = getattr(r, 'data', None) or []
  return float(d[0].get('credit_balance', 0) or 0) if d else 0.0
 return float(_LBAL.get(email, 0.0))

def topup_balance(email, amt):
 """Tambah (atau kurangi dengan `amt` negatif) saldo kredit.

 RAISE bila DB terkonfigurasi tapi penulisan gagal -- itulah yang membuat
 webhook membalas 5xx dan Dodo mengirim ulang, alih-alih "sukses" padahal
 tidak ada yang tersimpan (gagal senyap, temuan audit billing).
 """
 if is_configured():
  cur = get_balance(email)
  c = _get_write_client()
  ex = c.table('user_balances').select('email').eq('email', email).limit(1).execute()
  nb = cur + float(amt)
  if getattr(ex, 'data', None):
   c.table('user_balances').update({'credit_balance': nb}).eq('email', email).execute()
  else:
   c.table('user_balances').insert({'email': email, 'credit_balance': nb}).execute()
  return nb
 _LBAL[email] = float(_LBAL.get(email, 0.0)) + float(amt)
 return _LBAL[email]

def deduct_balance(email,amt):
 b=get_balance(email)
 if b < float(amt): return None
 return topup_balance(email,-float(amt))

# ---- PAYMENT EVENTS (idempotensi webhook Dodo Payments) -------------------
# KENAPA ADA: Dodo punya RETRY otomatis + "bulk replay" (dokumentasi resmi).
# Handler lama tidak menyimpan id event, sehingga satu pembayaran bisa
# dikredit BERKALI-KALI (double-credit) setiap Dodo mengirim ulang.
#
# Status dipakai, bukan sekadar "ada/tidak ada": bila baris diklaim lalu
# pemrosesan GAGAL (mis. DB sempat down), retry berikutnya HARUS tetap boleh
# memproses -- kalau tidak, pembayaran yang sudah dibayar tidak pernah dikredit.
_LPAY: dict[str, str] = {}   # webhook_id -> "pending" | "processed"


def claim_payment_event(webhook_id, payment_id=None, event_type=None,
                        amount=None, email=None):
    """Klaim satu event webhook. Return: "new" | "pending" | "processed".

    "processed" = sudah selesai -> handler berhenti (idempoten).
    "pending"   = percobaan sebelumnya gagal -> LANJUT proses (retry-safe).
    """
    if not webhook_id:
        raise ValueError("webhook_id wajib diisi (idempotency key)")
    row = {"webhook_id": webhook_id, "payment_id": payment_id,
           "event_type": event_type, "amount": amount, "email": email}
    if is_configured():
        c = _get_write_client()
        try:
            c.table("payment_events").insert(dict(row, status="pending")).execute()
            return "new"
        except Exception:
            # Kemungkinan besar PK sudah ada (race/retry). Kalau barisnya TIDAK
            # ada, penyebabnya lain -> JANGAN telan, biar handler menjawab 5xx.
            r = (c.table("payment_events").select("status")
                 .eq("webhook_id", webhook_id).limit(1).execute())
            d = getattr(r, "data", None) or []
            if not d:
                raise
            return "processed" if str(d[0].get("status")) == "processed" else "pending"
    st = _LPAY.get(webhook_id)
    if st is None:
        _LPAY[webhook_id] = "pending"
        return "new"
    return st


def mark_payment_event_processed(webhook_id):
    """Tandai event SELESAI — dipanggil hanya setelah tier/saldo tersimpan."""
    if is_configured():
        _get_write_client().table("payment_events").update({"status": "processed"}) \
            .eq("webhook_id", webhook_id).execute()
        return True
    _LPAY[webhook_id] = "processed"
    return True


def payment_event_exists(webhook_id):
    """True bila event sudah pernah SELESAI diproses (dipakai tes/audit).

    Membaca lewat klien SERVICE (bypass RLS): dengan klien anon, RLS membuat
    hasil baca kosong sehingga event yang sudah diproses terlihat "belum" dan
    pembayaran bisa dikredit ulang.
    """
    if not webhook_id:
        return False
    if is_configured():
        c = _get_write_client() if SUPABASE_SERVICE_KEY else _get_client()
        r = (c.table("payment_events").select("status")
             .eq("webhook_id", webhook_id).limit(1).execute())
        d = getattr(r, "data", None) or []
        return bool(d) and str(d[0].get("status")) == "processed"
    return _LPAY.get(webhook_id) == "processed"


def log_payment_event(webhook_id, payment_id=None, event_type=None,
                      amount=None, email=None):
    """Alias ramah-tes: klaim event lalu tandai selesai (atomik dari sisi uji)."""
    state = claim_payment_event(webhook_id, payment_id, event_type, amount, email)
    if state != "processed":
        mark_payment_event_processed(webhook_id)
    return state


# ---- KUOTA HARIAN (struktur bisnis final 2026-09-18) ----------------------
# 1 request = 1 RPD, dihitung PER HARI, reset 00:00 **WIB** (UTC+7).
#
# PRINSIP BISNIS (jangan diubah tanpa keputusan user):
#   * Gemma 4 = jalur GRATIS (kuota upstream 187.200 RPD) -> JANGAN pelit:
#     free 100/hari, berbayar 500/hari;
#   * pembeda tier = DeepSeek (Flash/Pro), bukan Gemma;
#   * bucket `gemma` juga menampung model gratis lain + Flash-Lite INTERNAL,
#     supaya satu jalur murah punya satu ember kuota yang mudah dijelaskan.
WIB = timezone(timedelta(hours=7))

QUOTA_LIMITS = {
    "free":  {"gemma": 100, "flash": 0,    "pro": 0},
    "plus":  {"gemma": 500, "flash": 100,  "pro": 0},
    "pro":   {"gemma": 500, "flash": 500,  "pro": 50},
    "ultra": {"gemma": 500, "flash": 2500, "pro": 200},
}
QUOTA_BUCKETS = ("gemma", "flash", "pro")
# Urutan turun-biaya untuk auto-fallback: Pro -> Flash -> Gemma.
QUOTA_FALLBACK_ORDER = ("pro", "flash", "gemma")

# ---- TIER SAAT LAUNCH (keputusan produk 2026-09-18) ----------------------
# Hanya `free` + `plus` yang DITAWARKAN. `pro` & `ultra` DISEMBUNYIKAN dari UI,
# bukan dihapus: skema, harga, dan batas kuotanya tetap ada supaya bisa
# diaktifkan lagi tanpa migrasi.
#
# User lama yang tier-nya `pro`/`ultra` TIDAK diturunkan ke `free`: mereka
# diperlakukan setara `plus` (tetap dapat jalur berbayar), supaya tidak ada yang
# kehilangan akses yang sudah dibayar.
LAUNCH_TIERS = ("free", "plus")
HIDDEN_TIERS = ("pro", "ultra")


def effective_tier(tier: str) -> str:
    """Tier EFEKTIF untuk penegakan kuota & tier-gate.

    `pro`/`ultra` (disembunyikan saat launch) -> dipetakan ke `plus` agar user
    lama tetap mendapat akses berbayar, bukan turun ke `free`.
    """
    t = (tier or "free").strip().lower()
    return "plus" if t in HIDDEN_TIERS else (t if t in LAUNCH_TIERS else "free")

_LQUOTA: dict[str, dict] = {}


def get_quota_limit(tier: str) -> dict:
    """Batas harian per bucket untuk tier (tier tak dikenal -> free)."""
    t = (tier or "free").strip().lower()
    return dict(QUOTA_LIMITS.get(t, QUOTA_LIMITS["free"]))


def quota_total_limit(tier: str) -> int:
    """Total request/hari: free 100, plus 600, pro 1050, ultra 3200."""
    return sum(get_quota_limit(tier).values())


def quota_bucket(model_id: str) -> str:
    """Petakan id model -> bucket kuota.

    Berdasarkan id yang TERBUKTI ada di katalog gateway:
      * `deepseek` + `pro` -> pro;
      * `deepseek`         -> flash (`deepseek-ai/deepseek-v4-flash-0731`);
      * sisanya (gemma, gemini-*-flash-lite, model gratis lain) -> gemma.
    """
    mid = (model_id or "").strip().lower()
    if "deepseek" in mid:
        return "pro" if "pro" in mid else "flash"
    return "gemma"


def quota_now() -> datetime:
    """Waktu sekarang di zona WIB (UTC+7)."""
    return datetime.now(WIB)


def _wib_date(dt: datetime):
    return dt.astimezone(WIB).date()


def quota_reset_due(reset_at, now=None) -> bool:
    """True bila TANGGAL WIB sudah berganti sejak `reset_at`.

    Memakai tanggal WIB, bukan selisih 24 jam: pengguna yang aktif melewati
    tengah malam harus mendapat jatah baru tepat saat tanggal berganti di WIB.
    """
    if reset_at is None:
        return True
    if isinstance(reset_at, str):
        try:
            reset_at = datetime.fromisoformat(reset_at.replace("Z", "+00:00"))
        except ValueError:
            return True
    if reset_at.tzinfo is None:
        reset_at = reset_at.replace(tzinfo=timezone.utc)
    return _wib_date(reset_at) < _wib_date(now or quota_now())


def _quota_row(email: str):
    """Baris user_usage untuk email (None bila belum ada)."""
    if is_configured():
        c = _get_write_client() if SUPABASE_SERVICE_KEY else _get_client()
        r = (c.table("user_usage").select(
            "email,daily_gemma,daily_flash,daily_pro,daily_reset_at")
            .eq("email", email).limit(1).execute())
        d = getattr(r, "data", None) or []
        return d[0] if d else None
    return _LQUOTA.get(email)


def _quota_write(email: str, values: dict) -> None:
    if is_configured():
        c = _get_write_client()
        # WAJIB: datetime -> string ISO. httpx/json TIDAK bisa menyerialkan objek
        # datetime, sehingga menulis `daily_reset_at` apa adanya melempar
        # "Object of type datetime is not JSON serializable" -> /chat gagal
        # untuk setiap user yang BELUM punya baris kuota (regresi produksi
        # 2026-09-18, tertangkap E2E: 3 tes timeout + 4 TypeError di log server).
        safe = {
            k: (v.isoformat() if isinstance(v, datetime) else v)
            for k, v in values.items()
        }
        ex = c.table("user_usage").select("email").eq("email", email).limit(1).execute()
        if getattr(ex, "data", None):
            c.table("user_usage").update(safe).eq("email", email).execute()
        else:
            c.table("user_usage").insert({"email": email, **safe}).execute()
        return
    row = _LQUOTA.setdefault(email, {"email": email, "daily_gemma": 0,
                                     "daily_flash": 0, "daily_pro": 0,
                                     "daily_reset_at": quota_now()})
    row.update(values)


def check_and_reset(email: str, now=None) -> bool:
    """Reset penghitung harian bila tanggal WIB berganti. True bila reset terjadi."""
    row = _quota_row(email)
    if row is None:
        _quota_write(email, {"daily_gemma": 0, "daily_flash": 0, "daily_pro": 0,
                             "daily_reset_at": (now or quota_now())})
        return True
    if not quota_reset_due(row.get("daily_reset_at"), now):
        return False
    if is_configured():
        try:
            _get_write_client().rpc("reset_daily_quota", {"p_email": email}).execute()
            return True
        except Exception:  # noqa: BLE001 - RPC belum dimigrasi -> jalur UPDATE
            pass
    _quota_write(email, {"daily_gemma": 0, "daily_flash": 0, "daily_pro": 0,
                         "daily_reset_at": (now or quota_now())})
    return True


def quota_status(email: str, tier: str = "free") -> dict:
    """Ringkasan kuota hari ini (endpoint /quota + dashboard frontend).

    Memakai `effective_tier`: user lama pro/ultra (tier disembunyikan) tetap
    mendapat batas Plus di ringkasan ini, supaya dashboard tidak menampilkan
    skema yang tidak ditawarkan.
    """
    eff = effective_tier(tier)
    check_and_reset(email)
    row = _quota_row(email) or {}
    limits = get_quota_limit(eff)
    used = {b: int(row.get("daily_%s" % b, 0) or 0) for b in QUOTA_BUCKETS}
    now = quota_now()
    nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "tier": eff,
        "buckets": {
            b: {"used": used[b], "limit": limits[b],
                "remaining": max(0, limits[b] - used[b])}
            for b in QUOTA_BUCKETS
        },
        "used_total": sum(used.values()),
        "limit_total": sum(limits.values()),
        "reset_at_wib": nxt.isoformat(),
        "reset_at_utc": nxt.astimezone(timezone.utc).isoformat(),
    }


def check_quota(email: str, model_id: str, tier: str = "free"):
    """Cek izin satu request. Return `(allowed, info)` dengan info bucket/sisa."""
    bucket = quota_bucket(model_id)
    st = quota_status(email, tier)
    b = st["buckets"][bucket]
    info = {"bucket": bucket, "used": b["used"], "limit": b["limit"],
            "remaining": b["remaining"]}
    return (b["limit"] > 0 and b["remaining"] > 0), info


def quota_fallback_bucket(email: str, tier: str, requested: str):
    """Bucket lebih murah yang MASIH bersisa (Pro -> Flash -> Gemma) atau None."""
    st = quota_status(email, tier)
    try:
        start = QUOTA_FALLBACK_ORDER.index(requested) + 1
    except ValueError:
        start = len(QUOTA_FALLBACK_ORDER)
    for b in QUOTA_FALLBACK_ORDER[start:]:
        if st["buckets"][b]["limit"] > 0 and st["buckets"][b]["remaining"] > 0:
            return b
    return None


def increment_quota(email: str, model_id: str) -> dict:
    """Catat 1 request pada bucket model.

    Memakai RPC `increment_daily_quota` (atomic `x = x + 1`) bila tersedia:
    read-modify-write dari backend kehilangan hitungan saat dua request paralel,
    sehingga user bisa melewati kuota.
    """
    bucket = quota_bucket(model_id)
    if is_configured():
        try:
            _get_write_client().rpc("increment_daily_quota",
                                    {"p_email": email, "p_bucket": bucket}).execute()
            return {"bucket": bucket, "via": "rpc"}
        except Exception:  # noqa: BLE001 - RPC belum ada -> jalur manual
            pass
    row = _quota_row(email) or {}
    used = int(row.get("daily_%s" % bucket, 0) or 0) + 1
    _quota_write(email, {"daily_%s" % bucket: used})
    return {"bucket": bucket, "used": used, "via": "fallback"}
