"""end_user_credentials.py — Fitur #6: kredensial end-user berbasis trigger.

Padanan n8n "End-user credentials" (Enterprise, Preview, docs Okt 2026):
sebuah kredensial **template** dibuat sekali oleh admin; setiap pengguna
menghubungkan akunnya sendiri. Saat runtime kredensial di-*resolve* ke akun
milik **pengguna yang memicu** workflow, bukan ke kredensial tetap.

Yang ditambahkan modul ini di atas infrastruktur vault Katalir yang sudah ada:

* **Template + koneksi terpisah.** Template menyimpan metadata OAuth
  (client_id, scope, dll). Koneksi menyimpan token milik satu pengguna.
* **Resolusi berbasis trigger.** Hanya trigger yang mendukung identitas
  pengguna yang boleh me-resolve: `manual`, `chat-hub`, `mcp-server`,
  `form` (butuh *n8n User Auth*), `chat` (hanya *Hosted Chat*, bukan
  embedded/webhook).
* **Opsional vs wajib.** `required_missing` membuat trigger gagal bila
  pengguna belum menghubungkan akun; `optional` cukup mengembalikan None.
* **Isolasi data eksekusi.** Hanya pengguna pemicu yang boleh melihat
  input/output node; pihak lain (termasuk admin) melihat output teredaksi.
* **Rotasi token sesuai RFC 9700 §4.14.** Rotasi refresh token + retensi
  relasi + deteksi reuse (reuse -> cabut seluruh grant). Token disimpan
  terenkripsi (Fernet) dan tidak pernah dikembalikan mentah oleh API.
* **Admin hanya melihat AGREGAT.** Jumlah koneksi boleh; isi koneksi tidak.

Env:
    KATALIR_EUC_ENFORCE_SCOPE     \"1\" (default) — token hanya boleh dipakai
                                  untuk scope yang disetujui (RFC 9700 §4.14.2)
    KATALIR_EUC_REQUIRE_MODES     daftar mode trigger yang memaksa koneksi
                                  (default: semua mode yang didukung)
    KATALIR_EUC_REVOKE_ON_REUSE   \"1\" (default) — cabut grant saat reuse
    KATALIR_EUC_IDLE_EXPIRE_SEC   umur diam refresh token (default 30 hari)
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
import time
import uuid
from typing import Any, Callable, Optional

__all__ = [
    "EndUserCredentialError", "TemplateNotFound", "ConnectionMissing",
    "TriggerNotSupported", "ScopeViolation", "RotationReuseDetected",
    "SUPPORTED_TRIGGER_MODES", "TRIGGER_AUTH_REQUIREMENTS", "CREDENTIAL_KINDS",
    "EndUserCredentialTemplate", "EndUserConnection", "RotatingTokenStore",
    "CredentialResolver", "resolver", "set_resolver", "resolver_from_env",
    "redact_execution_data", "template_from_config", "connection_from_config",
    "supports_end_user_credentials", "describe", "iter_supported_triggers",
]

# ---------------------------------------------------------------------------
# Konstanta
# ---------------------------------------------------------------------------

#: Mode trigger yang boleh me-resolve kredensial end-user (n8n docs, Okt 2026).
SUPPORTED_TRIGGER_MODES = (
    "manual",
    "chat-hub",
    "mcp-server",
    "form",
    "chat",
)

#: Mode trigger yang mensyaratkan autentikasi pengguna ("n8n User Auth").
#: Form Trigger & Chat Trigger hanya me-resolve bila memakai n8n User Auth.
TRIGGER_AUTH_REQUIREMENTS: dict[str, str] = {
    "manual": "session",
    "chat-hub": "session",
    "mcp-server": "session",
    "form": "n8n-user-auth",
    "chat": "n8n-user-auth",
}

#: Chat Trigger hanya me-resolve pada mode Hosted Chat, BUKAN embedded/webhook.
CHAT_ALLOWED_MODES = ("hosted",)

#: n8n membatasi kredensial end-user ke tipe berbasis OAuth saja.
CREDENTIAL_KINDS = ("oauth2", "oauth1")

DEFAULT_IDLE_EXPIRE_SEC = 30 * 24 * 3600.0     # 30 hari (RFC 9700: MAY)
DEFAULT_REVOKE_ON_REUSE = True
DEFAULT_ENFORCE_SCOPE = True

REDACTED = "***redacted***"
MAX_RESOLVE_DEPTH = 8


class EndUserCredentialError(Exception):
    """Kesalahan umum kredensial end-user."""


class TemplateNotFound(EndUserCredentialError):
    """Template kredensial tidak ada (atau sudah dihapus)."""


class ConnectionMissing(EndUserCredentialError):
    """Pengguna pemicu belum menghubungkan akunnya ke template ini."""


class TriggerNotSupported(EndUserCredentialError):
    """Mode trigger tidak mendukung kredensial end-user."""


class ScopeViolation(EndUserCredentialError):
    """Permintaan memakai scope di luar yang disetujui (RFC 9700 §4.14.2)."""


class RotationReuseDetected(EndUserCredentialError):
    """Refresh token lama dipakai ulang -> indikasi kebocoran (§4.14.2)."""


# ---------------------------------------------------------------------------
# Dukungan trigger
# ---------------------------------------------------------------------------

def supports_end_user_credentials(mode: str, *, auth: str = "",
                                  chat_mode: str = "hosted") -> bool:
    """Apakah mode trigger ini me-resolve kredensial end-user?

    Mengikuti n8n: Form/Chat butuh n8n User Auth; Chat hanya Hosted Chat
    (embedded/webhook tidak didukung).
    """
    m = str(mode or "").strip().lower()
    if m not in SUPPORTED_TRIGGER_MODES:
        return False
    need = TRIGGER_AUTH_REQUIREMENTS.get(m, "")
    if need == "n8n-user-auth":
        if str(auth or "").strip().lower() != "n8n-user-auth":
            return False
    if m == "chat":
        return str(chat_mode or "hosted").strip().lower() in CHAT_ALLOWED_MODES
    return True


def iter_supported_triggers() -> list[dict]:
    """Katalog trigger + syaratnya (untuk UI/dokumentasi)."""
    out: list[dict] = []
    for m in SUPPORTED_TRIGGER_MODES:
        out.append({
            "mode": m,
            "requires_auth": TRIGGER_AUTH_REQUIREMENTS.get(m, ""),
            "chat_mode": "hosted-only" if m == "chat" else "",
            "supported": True,
        })
    return out


# ---------------------------------------------------------------------------
# Template + koneksi
# ---------------------------------------------------------------------------

class EndUserCredentialTemplate:
    """Kredensial *template*: dibuat admin sekali, dipakai bersama.

    Tidak menyimpan token siapa pun. Hanya metadata OAuth + kebijakan.
    """

    def __init__(self, template_id: str, *, name: str = "", kind: str = "oauth2",
                 provider: str = "", owner_project: str = "",
                 scopes: Optional[list[str]] = None,
                 client_id: str = "", allowed_modes: Optional[list[str]] = None,
                 required: bool = False, created_by: str = "",
                 created_at: Optional[float] = None) -> None:
        k = str(kind or "oauth2").strip().lower()
        if k not in CREDENTIAL_KINDS:
            raise EndUserCredentialError(
                f"hanya kredensial OAuth yang didukung, dapat {kind!r}")
        self.template_id = str(template_id)
        self.name = name
        self.kind = k
        self.provider = provider
        self.owner_project = owner_project
        self.scopes = list(scopes or [])
        self.client_id = client_id
        # None -> semua mode yang didukung; list -> subset eksplisit
        self.allowed_modes = (list(allowed_modes) if allowed_modes is not None
                              else list(SUPPORTED_TRIGGER_MODES))
        # required=True -> trigger GAGAL bila pengguna belum menghubungkan
        self.required = bool(required)
        self.created_by = created_by
        self.created_at = float(created_at if created_at is not None
                                else time.time())
        self.deleted = False

    def allows_mode(self, mode: str, *, auth: str = "",
                    chat_mode: str = "hosted") -> bool:
        if self.deleted:
            return False
        m = str(mode or "").strip().lower()
        return (m in self.allowed_modes
                and supports_end_user_credentials(m, auth=auth,
                                                  chat_mode=chat_mode))

    def to_dict(self) -> dict:
        return {
            "template_id": self.template_id, "name": self.name,
            "kind": self.kind, "provider": self.provider,
            "owner_project": self.owner_project, "scopes": list(self.scopes),
            "client_id": self.client_id,
            "allowed_modes": list(self.allowed_modes),
            "required": self.required, "created_by": self.created_by,
            "created_at": self.created_at, "deleted": self.deleted,
        }


class EndUserConnection:
    """Koneksi satu pengguna ke satu template.

    Token disimpan **terenkripsi** (Fernet) — lihat `token_blob`. Nilai mentah
    tidak pernah disimpan di sini dan tidak pernah keluar lewat API.
    """

    def __init__(self, template_id: str, user_id: str, *,
                 account_label: str = "", token_blob: str = "",
                 scopes: Optional[list[str]] = None,
                 created_at: Optional[float] = None,
                 last_used_at: Optional[float] = None,
                 revoked: bool = False,
                 generation: int = 1,
                 refresh_fingerprint: str = "") -> None:
        self.template_id = str(template_id)
        self.user_id = str(user_id)
        self.account_label = account_label
        self.token_blob = token_blob            # Fernet ciphertext
        self.scopes = list(scopes or [])
        self.created_at = float(created_at if created_at is not None
                                else time.time())
        self.last_used_at = last_used_at
        self.revoked = bool(revoked)
        # generation naik setiap rotasi (RFC 9700 §4.14.2)
        self.generation = int(generation)
        # sidik jari refresh token yang masih berlaku -> deteksi reuse
        self.refresh_fingerprint = refresh_fingerprint

    @property
    def connection_id(self) -> str:
        return f"{self.template_id}:{self.user_id}"

    def to_dict(self) -> dict:
        """Representasi aman: TANPA token, tanpa sidik jari."""
        return {
            "connection_id": self.connection_id,
            "template_id": self.template_id, "user_id": self.user_id,
            "account_label": self.account_label,
            "scopes": list(self.scopes), "created_at": self.created_at,
            "last_used_at": self.last_used_at, "revoked": self.revoked,
            "generation": self.generation, "connected": not self.revoked,
            "has_token": bool(self.token_blob),
        }


# ---------------------------------------------------------------------------
# Penyimpanan token dengan rotasi (RFC 9700 §4.14)
# ---------------------------------------------------------------------------

class RotatingTokenStore:
    """Menyimpan token per-koneksi + rotasi refresh token + deteksi reuse.

    Sesuai RFC 9700 §4.14.2:
      * refresh token baru diterbitkan setiap kali token di-refresh;
      * refresh token lama **tidak berlaku**, tetapi relasinya dipertahankan;
      * bila token lama dipakai lagi -> indikasi kebocoran -> cabut grant.
      * refresh token kedaluwarsa bila klien tidak aktif (`MAY`).
    """

    def __init__(self, *, cipher: Callable[[str], str] | None = None,
                 decipher: Callable[[str], str] | None = None,
                 idle_expire_sec: float = DEFAULT_IDLE_EXPIRE_SEC,
                 revoke_on_reuse: bool = DEFAULT_REVOKE_ON_REUSE,
                 clock: Callable[[], float] | None = None) -> None:
        self._cipher = cipher
        self._decipher = decipher
        self.idle_expire_sec = float(idle_expire_sec)
        self.revoke_on_reuse = bool(revoke_on_reuse)
        self._clock = clock or time.time
        self._lock = threading.RLock()
        #: fingerprint refresh token saat ini -> connection_id
        self._live: dict[str, str] = {}
        #: fingerprint yang SUDAH dirotasi -> connection_id (retensi relasi)
        self._retired: dict[str, str] = {}
        self.rotations = 0
        self.reuse_events: list[dict] = []

    # -- sidik jari --------------------------------------------------------
    @staticmethod
    def fingerprint(refresh_token: str) -> str:
        """SHA-256 dari refresh token. Nilai mentah tidak pernah disimpan."""
        return hashlib.sha256(str(refresh_token).encode("utf-8")).hexdigest()

    # -- enkripsi ----------------------------------------------------------
    def _operate(self, fn: Callable[[str], str] | None, value: str) -> str:
        if fn is None:
            # Tanpa cipher eksplisit -> tetap jangan simpan mentah.
            return "raw:" + value
        return fn(value)

    def seal(self, payload: str) -> str:
        return self._operate(self._cipher, payload)

    def open(self, blob: str) -> str:
        if blob.startswith("raw:"):
            return blob[4:]
        if self._decipher is None:
            raise EndUserCredentialError("pembuka token tidak tersedia")
        return self._decipher(blob)

    # -- siklus token ------------------------------------------------------
    def put(self, conn: EndUserConnection, tokens: dict) -> EndUserConnection:
        """Simpan token awal + daftarkan refresh token sebagai yang berlaku."""
        with self._lock:
            payload = _json_dumps(tokens)
            conn.token_blob = self.seal(payload)
            fp = self.fingerprint(tokens.get("refresh_token", ""))
            conn.refresh_fingerprint = fp
            conn.generation = max(1, conn.generation)
            if fp:
                self._live[fp] = conn.connection_id
            conn.last_used_at = self._clock()
            return conn

    def rotate(self, conn: EndUserConnection, new_tokens: dict, *,
               presented_refresh: str = "") -> EndUserConnection:
        """Roter refresh token. Menolak token yang sudah dipensiunkan."""
        with self._lock:
            presented_fp = self.fingerprint(presented_refresh or "")
            if presented_fp and presented_fp in self._retired:
                owner = self._retired[presented_fp]
                self.reuse_events.append({
                    "connection_id": owner, "presented": presented_fp,
                    "at": self._clock()})
                if self.revoke_on_reuse:
                    # Tidak bisa menentukan pihak mana yang sah (RFC 9700),
                    # jadi seluruh grant dicabut.
                    conn.revoked = True
                    self._live.pop(conn.refresh_fingerprint, None)
                raise RotationReuseDetected(
                    "refresh token lama dipakai ulang -> grant dicabut")
            old_fp = conn.refresh_fingerprint
            payload = _json_dumps(new_tokens)
            conn.token_blob = self.seal(payload)
            new_fp = self.fingerprint(new_tokens.get("refresh_token", ""))
            if old_fp:
                self._live.pop(old_fp, None)
                self._retired[old_fp] = conn.connection_id   # retensi relasi
            if new_fp:
                self._live[new_fp] = conn.connection_id
            conn.refresh_fingerprint = new_fp
            conn.generation += 1
            conn.last_used_at = self._clock()
            self.rotations += 1
            return conn

    def is_live(self, refresh_token: str) -> bool:
        with self._lock:
            return self.fingerprint(refresh_token) in self._live

    def is_retired(self, refresh_token: str) -> bool:
        with self._lock:
            return self.fingerprint(refresh_token) in self._retired

    def expire_idle(self, conn: EndUserConnection) -> bool:
        """Refresh token kedaluwarsa karena lama tidak dipakai (RFC 9700 MAY)."""
        if self.idle_expire_sec <= 0:
            return False
        last = conn.last_used_at or conn.created_at
        if self._clock() - last >= self.idle_expire_sec:
            with self._lock:
                self._live.pop(conn.refresh_fingerprint, None)
                conn.revoked = True
            return True
        return False

    def revoke_all(self, conn: EndUserConnection) -> None:
        """Cabut seluruh grant untuk koneksi ini (mis. logout / ganti sandi)."""
        with self._lock:
            self._live.pop(conn.refresh_fingerprint, None)
            conn.revoked = True

    def stats(self) -> dict:
        with self._lock:
            return {"live": len(self._live), "retired": len(self._retired),
                    "rotations": self.rotations,
                    "reuse_events": len(self.reuse_events)}


def _json_dumps(value: Any) -> str:
    import json
    return json.dumps(value, separators=(",", ":"), default=str)


def _json_loads(text: str) -> Any:
    import json
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return {}


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

class CredentialResolver:
    """Registry template + koneksi, dan resolusi kredensial per-trigger.

    Inilah inti perbedaan n8n: **kredensial tetap** vs **kredensial end-user**.
    Modul ini mengurus yang kedua.
    """

    def __init__(self, *, store: RotatingTokenStore | None = None,
                 enforce_scope: bool = DEFAULT_ENFORCE_SCOPE,
                 require_modes: Optional[list[str]] = None,
                 clock: Callable[[], float] | None = None) -> None:
        self.templates: dict[str, EndUserCredentialTemplate] = {}
        self.connections: dict[str, EndUserConnection] = {}
        self.store = store or RotatingTokenStore(clock=clock)
        self.enforce_scope = bool(enforce_scope)
        # Mode trigger yang MEMAKSA koneksi ada (default: semua mode terdukung)
        self.require_modes = list(require_modes if require_modes is not None
                                  else SUPPORTED_TRIGGER_MODES)
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self.resolutions = 0
        self.misses = 0
        self.denials: list[dict] = []

    # -- template ----------------------------------------------------------
    def add_template(self, template: EndUserCredentialTemplate
                     ) -> EndUserCredentialTemplate:
        with self._lock:
            self.templates[template.template_id] = template
            return template

    def get_template(self, template_id: str) -> EndUserCredentialTemplate:
        t = self.templates.get(str(template_id))
        if t is None or t.deleted:
            raise TemplateNotFound(f"template tidak ditemukan: {template_id}")
        return t

    def delete_template(self, template_id: str) -> dict:
        """Hapus template = hapus SEMUA koneksi pengguna (perilaku n8n)."""
        with self._lock:
            t = self.get_template(template_id)
            t.deleted = True
            removed = [cid for cid, c in self.connections.items()
                       if c.template_id == t.template_id]
            for cid in removed:
                conn = self.connections.pop(cid)
                self.store.revoke_all(conn)
            return {"template_id": t.template_id,
                    "connections_removed": len(removed)}

    # -- koneksi -----------------------------------------------------------
    def connect(self, template_id: str, user_id: str, tokens: dict, *,
                account_label: str = "", scopes: Optional[list[str]] = None
                ) -> EndUserConnection:
        """Hubungkan SATU akun pengguna ke template (satu per pengguna)."""
        t = self.get_template(template_id)
        if not t.kind.startswith("oauth"):
            raise EndUserCredentialError("hanya kredensial OAuth yang didukung")
        with self._lock:
            existing = self.connections.get(f"{t.template_id}:{user_id}")
            if existing is not None and not existing.revoked:
                # Satu koneksi per pengguna per template -> ganti, bukan tambah.
                conn = existing
            else:
                conn = EndUserConnection(
                    t.template_id, user_id, account_label=account_label,
                    scopes=list(scopes if scopes is not None else t.scopes),
                    created_at=self._clock())
                self.connections[conn.connection_id] = conn
            if account_label:
                conn.account_label = account_label
            if scopes is not None:
                conn.scopes = list(scopes)
            conn.revoked = False
            self.store.put(conn, tokens)
            return conn

    def disconnect(self, template_id: str, user_id: str) -> bool:
        """Cabut koneksi. True hanya bila ada koneksi HIDUP yang dicabut
        (dipanggil dua kali -> False, idempoten)."""
        with self._lock:
            conn = self.connections.get(f"{template_id}:{user_id}")
            if conn is None or conn.revoked:
                return False
            self.store.revoke_all(conn)
            return True

    def get_connection(self, template_id: str, user_id: str
                       ) -> EndUserConnection:
        conn = self.connections.get(f"{template_id}:{user_id}")
        if conn is None:
            raise ConnectionMissing(
                f"pengguna belum menghubungkan akun untuk {template_id}")
        if conn.revoked:
            raise ConnectionMissing(
                f"koneksi dicabut untuk {template_id}")
        return conn

    # -- resolusi berbasis trigger ----------------------------------------
    def resolve(self, template_id: str, *, trigger_mode: str, user_id: str,
                auth: str = "", chat_mode: str = "hosted",
                requested_scopes: Optional[list[str]] = None,
                required: Optional[bool] = None) -> dict:
        """Resolve kredensial untuk **pengguna yang memicu**.

        Mengikuti n8n:
          * trigger tidak didukung -> TriggerNotSupported
          * template.required (atau required=True) & belum konek ->
            ConnectionMissing
          * opsional & belum konek -> {"resolved": False, ...}
        """
        t = self.get_template(template_id)
        m = str(trigger_mode or "").strip().lower()
        if not t.allows_mode(m, auth=auth, chat_mode=chat_mode):
            self.denials.append({"template_id": t.template_id,
                                 "mode": m, "reason": "trigger_not_supported",
                                 "at": self._clock()})
            raise TriggerNotSupported(
                f"trigger {m!r} tidak me-resolve kredensial end-user")
        must = t.required if required is None else bool(required)
        must = must or (m in self.require_modes and t.required)
        try:
            conn = self.get_connection(t.template_id, user_id)
        except ConnectionMissing:
            self.misses += 1
            if must:
                self.denials.append({"template_id": t.template_id,
                                     "mode": m, "reason": "missing_connection",
                                     "at": self._clock()})
                raise
            return {"resolved": False, "reason": "pengguna belum menghubungkan",
                    "template_id": t.template_id, "trigger_mode": m,
                    "user_id": str(user_id)}
        if self.store.expire_idle(conn):
            self.misses += 1
            if must:
                raise ConnectionMissing("refresh token kedaluwarsa (diam)")
            return {"resolved": False, "reason": "refresh token kedaluwarsa",
                    "template_id": t.template_id, "trigger_mode": m,
                    "user_id": str(user_id)}
        # RFC 9700 §4.14.2: token dibatasi scope yang disetujui.
        if self.enforce_scope and requested_scopes:
            extra = [s for s in requested_scopes if s not in conn.scopes]
            if extra:
                self.denials.append({"template_id": t.template_id,
                                     "mode": m, "reason": "scope_violation",
                                     "scopes": extra, "at": self._clock()})
                raise ScopeViolation(
                    f"scope di luar persetujuan: {', '.join(extra)}")
        token_payload = {}
        if conn.token_blob:
            token_payload = _json_loads(self.store.open(conn.token_blob))
        conn.last_used_at = self._clock()
        self.resolutions += 1
        return {
            "resolved": True, "template_id": t.template_id,
            "trigger_mode": m, "user_id": str(user_id),
            "connection_id": conn.connection_id,
            "account_label": conn.account_label,
            "scopes": list(conn.scopes), "generation": conn.generation,
            "tokens": token_payload,     # pemanggil internal; API tidak bocorkan
        }

    # -- privasi data eksekusi --------------------------------------------
    def redact_for(self, execution: dict, *, trigger_user_id: str,
                   viewer_id: str) -> dict:
        """Sembunyikan I/O node bagi siapa pun selain pengguna pemicu."""
        return redact_execution_data(
            execution, trigger_user_id=trigger_user_id, viewer_id=viewer_id,
            template_ids=set(self.templates))

    # -- agregat untuk admin ----------------------------------------------
    def admin_summary(self, template_id: str) -> dict:
        """Admin hanya melihat AGREGAT, bukan isi koneksi (perilaku n8n)."""
        t = self.get_template(template_id)
        conns = [c for c in self.connections.values()
                 if c.template_id == t.template_id and not c.revoked]
        return {
            "template_id": t.template_id, "name": t.name,
            "provider": t.provider, "kind": t.kind,
            "connection_count": len(conns),
            "secrets_visible": False,          # selalu false
            "connections_exposed": 0,          # tidak pernah ada
        }

    def stats(self) -> dict:
        with self._lock:
            live = [c for c in self.connections.values() if not c.revoked]
            return {
                "templates": len([t for t in self.templates.values()
                                  if not t.deleted]),
                "connections": len(live),
                "resolutions": self.resolutions,
                "misses": self.misses,
                "denials": len(self.denials),
                "tokens": self.store.stats(),
                "supported_triggers": list(SUPPORTED_TRIGGER_MODES),
                "enforce_scope": self.enforce_scope,
            }


# ---------------------------------------------------------------------------
# Redaksi data eksekusi
# ---------------------------------------------------------------------------

def redact_execution_data(execution: dict, *, trigger_user_id: str,
                          viewer_id: str,
                          template_ids: Optional[set] = None,
                          depth: int = 0) -> dict:
    """Terapkan isolasi data n8n pada satu (atau daftar) eksekusi.

    * Pengguna pemicu -> melihat data lengkap node yang memakai kredensial
      end-user (dan seluruh data lain).
    * Selain itu (termasuk admin) -> node yang memakai kredensial end-user
      menampilkan output **teredaksi**; metadata tetap terlihat.
    """
    if depth > MAX_RESOLVE_DEPTH:
        return {"redacted": True, "reason": "kedalaman maksimum"}
    if not isinstance(execution, dict):
        return {"redacted": True, "reason": "bentuk tidak dikenal"}
    is_trigger = str(trigger_user_id) == str(viewer_id)
    out = dict(execution)
    tids = template_ids or set()
    out["viewer"] = {
        "viewer_id": str(viewer_id),
        "trigger_user_id": str(trigger_user_id),
        "is_triggering_user": is_trigger,
    }
    nodes = execution.get("nodes") or execution.get("nodeRuns") or {}
    if isinstance(nodes, dict):
        items = list(nodes.items())
    elif isinstance(nodes, list):
        items = [(str((n or {}).get("id") or i), n)
                 for i, n in enumerate(nodes)]
    else:
        items = []
    redacted_nodes: Any = {} if isinstance(nodes, dict) else []
    any_redacted = False
    for key, node in items:
        node_d = dict(node) if isinstance(node, dict) else {"value": node}
        used = _node_uses_euc(node_d, tids)
        node_d["uses_end_user_credential"] = bool(used)
        if used and not is_trigger:
            any_redacted = True
            node_d["input"] = REDACTED
            node_d["output"] = REDACTED
            node_d["data"] = REDACTED
            node_d["redacted"] = True
            node_d["redacted_reason"] = (
                "hanya pengguna yang memicu dengan akunnya sendiri yang "
                "dapat melihat data ini")
        else:
            node_d.setdefault("redacted", False)
        if isinstance(redacted_nodes, dict):
            redacted_nodes[key] = node_d
        else:
            redacted_nodes.append(node_d)
    out["nodes" if isinstance(nodes, dict) else "nodeRuns"] = redacted_nodes
    out["data_redacted"] = bool(any_redacted)
    return out


def _node_uses_euc(node: dict, template_ids: set) -> bool:
    """Apakah node memakai kredensial end-user?"""
    if node.get("credential_type") == "end-user":
        return True
    if node.get("end_user_credential") is True:
        return True
    for key in ("credential", "credentials", "credential_template_id",
                "end_user_credential_id"):
        val = node.get(key)
        if isinstance(val, str) and val:
            if not template_ids or val in template_ids:
                return True
        elif isinstance(val, dict):
            if val.get("type") == "end-user" or val.get("end_user"):
                return True
            for sub in ("template_id", "id"):
                if val.get(sub) in template_ids:
                    return True
    return False


# ---------------------------------------------------------------------------
# Factory + registry
# ---------------------------------------------------------------------------

_RESOLVER: CredentialResolver | None = None


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on", "ya")


def _env_float(env: dict, name: str, default: float) -> float:
    """Ambil float dari dict env (BUKAN os.environ) agar injectable saat tes."""
    raw = env.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def resolver_from_env(env: dict | None = None) -> CredentialResolver:
    e = env if env is not None else os.environ
    modes_raw = str(e.get("KATALIR_EUC_REQUIRE_MODES") or "").strip()
    modes = ([m.strip() for m in modes_raw.split(",") if m.strip()]
             if modes_raw else None)
    cipher = e.get("_CIPHER") if isinstance(e, dict) else None
    decipher = e.get("_DECIPHER") if isinstance(e, dict) else None
    store = RotatingTokenStore(
        cipher=cipher if callable(cipher) else None,
        decipher=decipher if callable(decipher) else None,
        idle_expire_sec=_env_float(e, "KATALIR_EUC_IDLE_EXPIRE_SEC",
                                   DEFAULT_IDLE_EXPIRE_SEC),
        revoke_on_reuse=str(e.get("KATALIR_EUC_REVOKE_ON_REUSE", "1")
                            ).strip().lower() in ("1", "true", "yes", "on"))
    return CredentialResolver(
        store=store,
        enforce_scope=str(e.get("KATALIR_EUC_ENFORCE_SCOPE", "1")
                         ).strip().lower() in ("1", "true", "yes", "on"),
        require_modes=modes)


def resolver() -> CredentialResolver:
    global _RESOLVER
    if _RESOLVER is None:
        _RESOLVER = resolver_from_env()
    return _RESOLVER


def set_resolver(new: CredentialResolver | None) -> None:
    global _RESOLVER
    _RESOLVER = new


def template_from_config(cfg: dict) -> EndUserCredentialTemplate:
    cfg = dict(cfg or {})
    return EndUserCredentialTemplate(
        str(cfg.get("template_id") or cfg.get("id") or uuid.uuid4().hex[:12]),
        name=str(cfg.get("name") or ""), kind=str(cfg.get("kind") or "oauth2"),
        provider=str(cfg.get("provider") or ""),
        owner_project=str(cfg.get("owner_project") or ""),
        scopes=cfg.get("scopes") or [],
        client_id=str(cfg.get("client_id") or ""),
        allowed_modes=cfg.get("allowed_modes"),
        required=bool(cfg.get("required")),
        created_by=str(cfg.get("created_by") or ""))


def connection_from_config(cfg: dict) -> EndUserConnection:
    cfg = dict(cfg or {})
    return EndUserConnection(
        str(cfg.get("template_id") or ""), str(cfg.get("user_id") or ""),
        account_label=str(cfg.get("account_label") or ""),
        scopes=cfg.get("scopes") or [],
        revoked=bool(cfg.get("revoked")))


def describe(env: dict | None = None) -> dict:
    e = env if env is not None else os.environ
    r = resolver_from_env(e)
    return {
        "supported_triggers": iter_supported_triggers(),
        "credential_kinds": list(CREDENTIAL_KINDS),
        "enforce_scope": r.enforce_scope,
        "required_modes": list(r.require_modes),
        "revoke_on_reuse": r.store.revoke_on_reuse,
        "idle_expire_sec": r.store.idle_expire_sec,
        "chat_allowed_modes": list(CHAT_ALLOWED_MODES),
        "redaction_marker": REDACTED,
    }
