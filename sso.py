# sso.py — Fitur #7: SSO / SAML / OIDC / LDAP (Okt 2026)
# ======================================================================
# Enterprise single sign-on: OIDC (Okta/Auth0/Google Workspace), SAML 2.0,
# dan LDAP. Termasuk pemetaan grup->peran, provisioning JIT, manajemen sesi,
# logout tunggal (SLO), proteksi session fixation, dan proteksi CSRF.
#
# RISET (Okt 2026): Supabase Auth sudah mendukung OAuth/OIDC; untuk SAML
# enterprise & LDAP on-prem tetap perlu jalur sendiri. KEPUTUSAN: antarmuka
# provider yang dapat disuntik (transport/directory) -> diuji deterministik
# tanpa jaringan; nol dependensi berat (xml.etree stdlib untuk SAML).
# ======================================================================

from __future__ import annotations

import base64
import json
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional
from xml.etree import ElementTree as ET

#: Urutan prioritas peran (indeks lebih tinggi = lebih berkuasa).
ROLE_PRIORITY = ["viewer", "developer", "admin", "owner"]

MASK = "***"
_TOKEN_RE = re.compile(
    r"(eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}|"
    r"Bearer\s+[A-Za-z0-9._\-]{8,}|SAMLResponse=[A-Za-z0-9+/=]{16,})")

#: Kunci yang isinya SELALU kredensial. Redaksi berbasis POLA saja tidak cukup:
#: access_token OIDC bersifat OPAQUE (base64url 43 char, tanpa awalan `eyJ`),
#: sehingga lolos dari `_TOKEN_RE`. Ini bug nyata yang tertangkap hard test
#: #12 — token mentah ikut tercetak di JSON log. Redaksi karena itu dilakukan
#: pada NAMA KUNCI juga, bukan hanya pada bentuk string-nya.
SENSITIVE_KEYS = frozenset({
    "access_token", "refresh_token", "id_token", "token", "tokens",
    "authorization", "client_secret", "secret", "password", "passwd",
    "code", "code_verifier", "saml_response", "samlresponse", "assertion",
    "api_key", "apikey", "private_key", "session_token", "cookie",
})


class SsoError(Exception):
    pass


class StateMismatch(SsoError):
    """CSRF: `state` tidak cocok dengan yang disimpan."""


class SessionExpired(SsoError):
    pass


class AuthFailed(SsoError):
    pass


def redact(text: Any) -> Any:
    """Buang kredensial dari teks/struktur sebelum dicatat.

    Dua lapis: (1) nama kunci yang sensitif -> seluruh nilai jadi `MASK`;
    (2) pola token yang dikenal (JWT/Bearer/SAMLResponse) di dalam string.
    """
    if isinstance(text, dict):
        out = {}
        for k, v in text.items():
            if str(k).lower() in SENSITIVE_KEYS and isinstance(v, (str, bytes)):
                out[k] = MASK
            else:
                out[k] = redact(v)
        return out
    if isinstance(text, str):
        return _TOKEN_RE.sub(MASK, text)
    if isinstance(text, list):
        return [redact(v) for v in text]
    return text


def decode_saml_response(value: Any) -> str:
    """Normalisasi assertion SAML menjadi XML.

    Binding POST SAML mengirim `SAMLResponse` sebagai **base64**, sedangkan
    binding Redirect/API mengirim XML mentah. Fungsi ini menerima keduanya
    (plus bytes) dan selalu mengembalikan XML agar verifikasi XML-DSig dan
    penguraian atribut bekerja pada bentuk yang sama.

    BUG NYATA (ditemukan saat verifikasi endpoint): sebelumnya XML-DSig
    dijalankan langsung atas string base64 sehingga selalu gagal dengan
    `XMLSyntaxError: Start tag expected, '<' not found` — semua login SAML
    asli ditolak meski assertion-nya sah.
    """
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if not isinstance(value, str):
        raise AuthFailed("assertion SAML bukan string/bytes")
    s = value.strip()
    if not s:
        raise AuthFailed("assertion SAML kosong")
    if s.startswith("<"):
        return s                                   # sudah XML
    try:
        pad = "=" * (-len(s) % 4)
        raw = base64.b64decode(s + pad, validate=False)
        xml = raw.decode("utf-8", "replace").strip()
    except Exception as exc:  # noqa: BLE001
        raise AuthFailed(f"SAMLResponse base64 tidak dapat didekode: {exc}") from exc
    if not xml.startswith("<"):
        raise AuthFailed("hasil dekode SAMLResponse bukan XML")
    return xml


# ---------------------------------------------------------------------------
# CSRF state + identity
# ---------------------------------------------------------------------------

def make_state() -> str:
    """Token anti-CSRF acak (dipakai pada authorize & diverifikasi di callback)."""
    return secrets.token_urlsafe(24)


def verify_state(expected: str, got: str) -> bool:
    """Perbandingan konstan-waktu. Raise StateMismatch bila beda/kosong."""
    if not expected or not got or not secrets.compare_digest(str(expected),
                                                             str(got)):
        raise StateMismatch("state OAuth tidak cocok (potensi CSRF)")
    return True


class Identity:
    """Identitas hasil login SSO."""

    def __init__(self, email: str, name: str = "", groups: Optional[list] = None,
                 provider: str = "", org: str = "", subject: str = "") -> None:
        self.email = (email or "").strip().lower()
        self.name = name or ""
        self.groups = list(groups or [])
        self.provider = provider
        self.org = org
        self.subject = subject

    def to_dict(self) -> dict:
        return {"email": self.email, "name": self.name, "groups": self.groups,
                "provider": self.provider, "org": self.org,
                "subject": self.subject}


# ---------------------------------------------------------------------------
# Pemetaan peran
# ---------------------------------------------------------------------------

def map_role(groups: list[str], mapping: dict[str, str],
             default: str = "viewer") -> str:
    """Grup SSO -> peran Katalir. Bila banyak cocok, ambil yang TERKUAT."""
    terpilih = default
    for g in groups or []:
        role = mapping.get(g)
        if role in ROLE_PRIORITY:
            if ROLE_PRIORITY.index(role) > ROLE_PRIORITY.index(terpilih):
                terpilih = role
    return terpilih


# ---------------------------------------------------------------------------
# Manajemen sesi (fixation protection + timeout)
# ---------------------------------------------------------------------------

class SessionStore:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._sessions: dict[str, dict] = {}

    def create(self, identity: Identity, role: str, ttl: float = 3600.0,
               session_id: Optional[str] = None) -> str:
        sid = session_id or secrets.token_urlsafe(32)
        self._sessions[sid] = {"identity": identity.to_dict(), "role": role,
                               "created_at": self._clock(),
                               "expires_at": self._clock() + float(ttl)}
        return sid

    def get(self, session_id: str) -> Optional[dict]:
        rec = self._sessions.get(session_id)
        if not rec:
            return None
        if self._clock() >= rec["expires_at"]:
            self._sessions.pop(session_id, None)
            return None
        return rec

    def rotate(self, old_id: str) -> Optional[str]:
        """Proteksi session fixation: buang id lama, terbitkan id BARU."""
        rec = self._sessions.pop(old_id, None)
        if rec is None:
            return None
        return self.create(Identity(**{k: rec["identity"][k] for k in
                                       ("email", "name", "groups", "provider",
                                        "org", "subject")}),
                           rec["role"], ttl=rec["expires_at"] - self._clock())

    def destroy(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None

    def destroy_all(self, email: str) -> int:
        email = (email or "").lower()
        mati = [sid for sid, r in self._sessions.items()
                if r["identity"]["email"] == email]
        for sid in mati:
            self._sessions.pop(sid, None)
        return len(mati)

    def touch(self, session_id: str, ttl: float) -> bool:
        rec = self._sessions.get(session_id)
        if not rec:
            return False
        rec["expires_at"] = self._clock() + float(ttl)
        return True


class RedisSessionStore(SessionStore):
    """Penyimpan sesi SSO di Redis — BERTAHAN restart & lintas PROSES.

    Antarmuka identik dengan `SessionStore` (create/get/rotate/destroy/
    destroy_all/touch) supaya bisa ditukar tanpa mengubah pemanggil.

    Kenapa perlu: pada produksi, satu aplikasi dapat berjalan di beberapa
    proses/worker; sesi di memori proses tidak terlihat oleh proses lain
    sehingga `/sso/session/{id}` bisa 404 dan SLO tidak menutup semua sesi.
    Redis juga memberi kedaluwarsa otomatis (TTL asli) sehingga "session
    timeout" tidak bergantung pada sapuan manual.

    Riset Okt 2026: pola session-store di Redis (hash + TTL per kunci + indeks
    per-user) adalah pendekatan standar; lihat link di
    docs/enterprise-100-percent-log.md.
    """

    NS = "katalir:sso:sess"

    def __init__(self, client: Any, clock: Callable[[], float] = time.time,
                 namespace: str = NS) -> None:
        super().__init__(clock=clock)
        self.r = client
        self.ns = namespace

    # -- kunci -------------------------------------------------------------
    def _k(self, sid: str) -> str:
        return f"{self.ns}:{sid}"

    def _idx(self, email: str) -> str:
        return f"{self.ns}:idx:{(email or '').lower()}"

    # -- tulis -------------------------------------------------------------
    def create(self, identity: Identity, role: str, ttl: float = 3600.0,
               session_id: Optional[str] = None) -> str:
        sid = session_id or secrets.token_urlsafe(32)
        now = self._clock()
        rec = {"identity": identity.to_dict(), "role": role,
               "created_at": now, "expires_at": now + float(ttl)}
        pipe = self.r.pipeline(transaction=True)
        pipe.hset(self._k(sid), mapping={"data": json.dumps(rec)})
        pipe.expire(self._k(sid), max(1, int(float(ttl))))
        pipe.sadd(self._idx(identity.email), sid)
        pipe.expire(self._idx(identity.email), max(1, int(float(ttl)) + 60))
        pipe.execute()
        return sid

    def get(self, session_id: str) -> Optional[dict]:
        raw = self.r.hget(self._k(session_id), "data")
        if not raw:
            return None
        rec = json.loads(raw if isinstance(raw, str) else raw.decode())
        if self._clock() >= rec["expires_at"]:
            self.destroy(session_id)
            return None
        return rec

    def rotate(self, old_id: str) -> Optional[str]:
        rec = self.get(old_id)
        if rec is None:
            return None
        ident = Identity(**{k: rec["identity"][k] for k in
                            ("email", "name", "groups", "provider",
                             "org", "subject")})
        baru = self.create(ident, rec["role"],
                           ttl=max(1.0, rec["expires_at"] - self._clock()))
        self.destroy(old_id)
        return baru

    def destroy(self, session_id: str) -> bool:
        rec = self.get(session_id)
        n = self.r.delete(self._k(session_id))
        if rec:
            try:
                self.r.srem(self._idx(rec["identity"]["email"]), session_id)
            except Exception:  # noqa: BLE001 - indeks best-effort
                pass
        return bool(n)

    def destroy_all(self, email: str) -> int:
        email = (email or "").lower()
        sids = [s if isinstance(s, str) else s.decode()
                for s in self.r.smembers(self._idx(email))]
        if not sids:
            return 0
        pipe = self.r.pipeline(transaction=True)
        for sid in sids:
            pipe.delete(self._k(sid))
        pipe.delete(self._idx(email))
        pipe.execute()
        return len(sids)

    def touch(self, session_id: str, ttl: float) -> bool:
        if not self.get(session_id):
            return False
        raw = self.r.hget(self._k(session_id), "data")
        rec = json.loads(raw if isinstance(raw, str) else raw.decode())
        rec["expires_at"] = self._clock() + float(ttl)
        pipe = self.r.pipeline(transaction=True)
        pipe.hset(self._k(session_id), mapping={"data": json.dumps(rec)})
        pipe.expire(self._k(session_id), max(1, int(float(ttl))))
        pipe.execute()
        return True

    def count(self) -> int:
        """Jumlah sesi aktif (untuk verifikasi/observabilitas)."""
        n = 0
        for key in self.r.scan_iter(match=f"{self.ns}:*", count=200):
            k = key if isinstance(key, str) else key.decode()
            if ":idx:" in k:
                continue
            n += 1
        return n


# ---------------------------------------------------------------------------
# Provider: OIDC
# ---------------------------------------------------------------------------

class OidcProvider:
    """OIDC Authorization Code flow. `transport` disuntik untuk test."""

    def __init__(self, client_id: str, issuer: str, scopes: Optional[list] = None,
                 transport: Optional[Callable[[str, dict], dict]] = None) -> None:
        self.client_id = client_id
        self.issuer = issuer.rstrip("/")
        self.scopes = scopes or ["openid", "email", "profile", "groups"]
        self._transport = transport

    def authorize_url(self, redirect_uri: str, state: str) -> str:
        q = urllib.parse.urlencode({
            "response_type": "code", "client_id": self.client_id,
            "redirect_uri": redirect_uri, "scope": " ".join(self.scopes),
            "state": state})
        return f"{self.issuer}/authorize?{q}"

    def exchange(self, code: str, claims: Optional[dict] = None,
                 org: str = "") -> Identity:
        """Tukar `code` -> Identity. Bila `claims` disuntik, dipakai langsung."""
        if claims is None:
            if self._transport is None:
                raise AuthFailed("transport OIDC tidak tersedia")
            data = self._transport("token", {"code": code,
                                             "client_id": self.client_id})
            claims = data.get("claims") or data
        return self._identity_from_claims(claims, org)

    def _identity_from_claims(self, claims: dict, org: str) -> Identity:
        email = claims.get("email") or claims.get("preferred_username") or ""
        if not email:
            raise AuthFailed("klaim OIDC tidak memuat email")
        groups = claims.get("groups") or claims.get("roles") or []
        if isinstance(groups, str):
            groups = [groups]
        return Identity(email=email, name=claims.get("name", ""),
                        groups=list(groups), provider="oidc", org=org,
                        subject=str(claims.get("sub", "")))


# ---------------------------------------------------------------------------
# Provider: SAML 2.0
# ---------------------------------------------------------------------------

class SamlProvider:
    """SAML 2.0: urai assertion (dict siap-pakai ATAU XML) -> Identity."""

    def __init__(self, entity_id: str = "", acs_url: str = "",
                 idp_cert: str = "") -> None:
        self.entity_id = entity_id
        self.acs_url = acs_url
        self.idp_cert = idp_cert

    def login_url(self, state: str) -> str:
        q = urllib.parse.urlencode({"SAMLRequest": "stub", "RelayState": state})
        return f"{self.entity_id}?{q}"

    def parse_assertion(self, assertion: Any, org: str = "") -> Identity:
        """Terima dict {email, name, groups} atau XML SAML."""
        if isinstance(assertion, dict):
            data = assertion
        elif isinstance(assertion, (str, bytes)):
            data = self._parse_xml(assertion)
        else:
            raise AuthFailed("assertion SAML tidak dikenali")
        email = data.get("email") or data.get("name_id") or ""
        if not email:
            raise AuthFailed("assertion SAML tidak memuat email")
        groups = data.get("groups") or []
        if isinstance(groups, str):
            groups = [g for g in re.split(r"[,;]", groups) if g]
        return Identity(email=email, name=data.get("name", ""),
                        groups=list(groups), provider="saml", org=org,
                        subject=str(data.get("subject", "")))

    @staticmethod
    def _parse_xml(xml: str) -> dict:
        xml = decode_saml_response(xml)
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            raise AuthFailed(f"XML SAML tidak valid: {exc}") from exc
        data: dict[str, Any] = {}
        # NameID
        for el in root.iter():
            tag = el.tag.split("}")[-1]
            if tag == "NameID" and el.text:
                data.setdefault("name_id", el.text.strip())
        # Attributes: <Attribute Name="email"><AttributeValue>..
        attrs: dict[str, list[str]] = {}
        nama_atr = None
        for el in root.iter():
            tag = el.tag.split("}")[-1]
            if tag == "Attribute":
                nama_atr = (el.attrib.get("Name") or "").lower()
                attrs.setdefault(nama_atr, [])
            elif tag == "AttributeValue" and nama_atr is not None:
                # `itertext()` menangani dua bentuk yang dipakai IdP nyata:
                # teks langsung, atau teks di dalam elemen anak (xs:string).
                nilai = "".join(el.itertext()).strip()
                if nilai:
                    attrs[nama_atr].append(nilai)
        for k, v in attrs.items():
            if len(v) == 1:
                data[k] = v[0]
            else:
                data[k] = v
        return data


# ---------------------------------------------------------------------------
# Provider: LDAP
# ---------------------------------------------------------------------------

class LdapProvider:
    """LDAP bind + pencarian. `directory` disuntik (dict) untuk test.

    `directory` bentuk: {uid: {"password": ..., "email": ..., "groups": [...]}}
    """

    def __init__(self, base_dn: str = "", directory: Optional[dict] = None,
                 bind_fn: Optional[Callable[[str, str], bool]] = None) -> None:
        self.base_dn = base_dn
        self._dir = directory or {}
        self._bind = bind_fn

    def bind(self, username: str, password: str) -> bool:
        if self._bind is not None:
            return bool(self._bind(username, password))
        rec = self._dir.get(username)
        if not rec or not password:
            return False
        return secrets.compare_digest(str(rec.get("password", "")), str(password))

    def identity(self, username: str, org: str = "") -> Identity:
        rec = self._dir.get(username)
        if not rec:
            raise AuthFailed(f"user LDAP tidak ditemukan: {username}")
        return Identity(email=rec.get("email", f"{username}@{self.base_dn}"),
                        name=rec.get("name", username),
                        groups=list(rec.get("groups", [])),
                        provider="ldap", org=org, subject=username)


# ---------------------------------------------------------------------------
# Manajer SSO: login, JIT provisioning, deprovision, SLO, multi-tenant
# ---------------------------------------------------------------------------

class SsoManager:
    """Orkestrasi login SSO + provisioning + sesi + logout tunggal."""

    def __init__(self, sessions: Optional[SessionStore] = None,
                 orgs: Optional[dict] = None) -> None:
        self.sessions = sessions or SessionStore()
        # org -> {"role_mapping": {...}, "domains": [...], "default_role": "viewer"}
        self.orgs = orgs or {}
        self._users: dict[str, dict] = {}          # email -> user
        self._states: dict[str, dict] = {}         # state -> {org, created_at}
        self._clock = self.sessions._clock

    # -- multi-tenant ------------------------------------------------------
    def register_org(self, org: str, role_mapping: dict,
                     domains: Optional[list] = None,
                     default_role: str = "viewer") -> None:
        self.orgs[org] = {"role_mapping": role_mapping or {},
                          "domains": [d.lower() for d in (domains or [])],
                          "default_role": default_role}

    def org_for_email(self, email: str) -> Optional[str]:
        dom = (email or "").split("@")[-1].lower()
        for org, cfg in self.orgs.items():
            if dom in cfg.get("domains", []):
                return org
        return None

    # -- CSRF state --------------------------------------------------------
    def begin(self, org: str = "") -> str:
        st = make_state()
        self._states[st] = {"org": org, "created_at": self._clock()}
        return st

    def consume_state(self, state: str) -> str:
        rec = self._states.pop(state, None)
        if rec is None:
            raise StateMismatch("state tidak dikenal / sudah dipakai")
        return rec.get("org", "")

    # -- login -------------------------------------------------------------
    def login(self, identity: Identity, state: str = "",
              expect_state: str = "", ttl: float = 3600.0,
              existing_session: str = "") -> dict:
        """Selesaikan login: verifikasi state, provisioning JIT, buat sesi.

        State WAJIB pernah diterbitkan `begin()` dan bersifat SEKALI PAKAI.
        Sebelumnya `login()` hanya membandingkan `expect_state` dengan `state`
        — keduanya datang dari pemanggil, jadi perbandingan itu SIRKULAR dan
        `state` yang sama bisa dipakai ulang berkali-kali (replay). Bug nyata
        yang tertangkap hard test #11.
        """
        if expect_state:
            verify_state(expect_state, state)
            # Anti-replay: state harus terdaftar (hasil begin()) dan dihapus
            # setelah dipakai. State yang tidak dikenal / sudah terpakai DITOLAK.
            if state not in self._states:
                raise StateMismatch(
                    "state tidak dikenal atau sudah dipakai (anti-replay)")
            self._states.pop(state, None)
        org = identity.org or self.org_for_email(identity.email) or ""
        if not org and self.orgs:
            raise AuthFailed("domain email tidak terdaftar di org mana pun")
        cfg = self.orgs.get(org, {})
        role = map_role(identity.groups, cfg.get("role_mapping", {}),
                        cfg.get("default_role", "viewer"))
        user = self.provision(identity, org)
        # proteksi session fixation: buang sesi lama bila ada
        if existing_session:
            self.sessions.destroy(existing_session)
        sid = self.sessions.create(identity, role, ttl=ttl)
        return {"session_id": sid, "role": role, "org": org,
                "identity": identity.to_dict(), "user": user}

    # -- provisioning ------------------------------------------------------
    def provision(self, identity: Identity, org: str = "") -> dict:
        """JIT provisioning: buat/perbarui user dari identitas SSO."""
        email = identity.email
        ada = self._users.get(email)
        user = {"email": email, "name": identity.name or
                (ada or {}).get("name", ""), "org": org or (ada or {}).get("org", ""),
                "groups": identity.groups, "provider": identity.provider,
                "active": True, "created_at": (ada or {}).get("created_at",
                                                              self._clock()),
                "updated_at": self._clock()}
        self._users[email] = user
        return dict(user)

    def deprovision(self, email: str) -> dict:
        """Nonaktifkan user + matikan SEMUA sesinya (SLO per-user)."""
        email = (email or "").lower()
        user = self._users.get(email)
        if user:
            user["active"] = False
            user["updated_at"] = self._clock()
        mati = self.sessions.destroy_all(email)
        return {"email": email, "deactivated": bool(user),
                "sessions_terminated": mati}

    def get_user(self, email: str) -> Optional[dict]:
        u = self._users.get((email or "").lower())
        return dict(u) if u else None

    # -- session -----------------------------------------------------------
    def session(self, session_id: str) -> Optional[dict]:
        return self.sessions.get(session_id)

    def logout(self, session_id: str) -> bool:
        return self.sessions.destroy(session_id)

    def slo(self, email: str) -> int:
        """Single Logout: matikan semua sesi milik email. Return jumlah."""
        return self.sessions.destroy_all(email)


# ===========================================================================
# BINDING NYATA (Okt 2026) — jaringan SUNGGUHAN, bukan seam yang disuntik
# ===========================================================================
# Sebelumnya `OidcProvider.transport` dan `LdapProvider.directory/bind_fn`
# hanya SEAM: unit test menyuntik dict sehingga tidak ada satu pun paket yang
# benar-benar keluar ke jaringan. Bagian ini mengikat seam itu ke layanan
# nyata:
#
#   OIDC  -> HTTP nyata (discovery, authorize+PKCE, token, JWKS, userinfo)
#   LDAP  -> TCP nyata via ldap3 (bind layanan -> cari -> bind user)
#   SAML  -> assertion bertanda tangan nyata + verifikasi XML-DSig (signxml)
#
# Riset Okt 2026 (link di docs/enterprise-100-percent-log.md):
#   * panva/oidc-provider 9.12.2 — OpenID Certified, aktif (npm 2026-08-27)
#   * ldap3 2.9.1 — klien LDAP pure-Python (PyPI)
#   * glauth v2.5.4 (2026-09-13) — server LDAP Go; dipilih karena ldapjs
#     DICOMMISSION (2024-05-14) dan OpenLDAP Windows tidak terpelihara
#   * signxml 5.1.0 — verifikasi XML-DSig SAML tanpa libxmlsec native
# ===========================================================================

import hashlib


def http_opener():
    """Opener TANPA proxy.

    `HTTP_PROXY`/`HTTPS_PROXY` di lingkungan ini menunjuk proxy lokal; tanpa
    dimatikan, request ke `localhost` ikut dicegat dan gagal.
    """
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def make_pkce_pair() -> tuple[str, str]:
    """(code_verifier, code_challenge) untuk PKCE S256 (RFC 7636)."""
    verifier = secrets.token_urlsafe(48)
    challenge = b64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


class OidcHttpTransport:
    """Transport OIDC NYATA: HTTP ke issuer, verifikasi ID token vs JWKS.

    Menggantikan seam `transport` lama. `issuer` adalah URL IdP sungguhan
    (mis. `http://localhost:9443` untuk oidc-provider, atau
    `https://accounts.google.com` untuk Google Workspace).
    """

    def __init__(self, issuer: str, client_id: str, client_secret: str = "",
                 redirect_uri: str = "", timeout: float = 20.0,
                 opener: Any = None) -> None:
        self.issuer = issuer.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.timeout = float(timeout)
        self._op = opener or http_opener()
        self._meta: Optional[dict] = None
        self._jwks: Optional[dict] = None

    # -- HTTP dasar --------------------------------------------------------
    def _request(self, url: str, data: Optional[bytes] = None,
                 headers: Optional[dict] = None,
                 method: str = "GET") -> tuple[int, str]:
        h = {"User-Agent": "Katalir-SSO/1.0", "Accept": "application/json"}
        h.update(headers or {})
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        try:
            r = self._op.open(req, timeout=self.timeout)
            return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    def _json(self, url: str, data: Optional[bytes] = None,
              headers: Optional[dict] = None,
              method: str = "GET") -> tuple[int, Any]:
        st, body = self._request(url, data=data, headers=headers, method=method)
        try:
            return st, json.loads(body)
        except Exception:  # noqa: BLE001
            return st, {"raw": body}

    # -- discovery / jwks --------------------------------------------------
    def discover(self, refresh: bool = False) -> dict:
        if self._meta is None or refresh:
            url = f"{self.issuer}/.well-known/openid-configuration"
            st, meta = self._json(url)
            if st != 200 or not isinstance(meta, dict) or "issuer" not in meta:
                raise AuthFailed(f"discovery OIDC gagal (HTTP {st}): {meta}")
            self._meta = meta
        return self._meta

    def jwks(self, refresh: bool = False) -> dict:
        if self._jwks is None or refresh:
            uri = self.discover().get("jwks_uri")
            if not uri:
                raise AuthFailed("discovery tidak memuat jwks_uri")
            st, data = self._json(uri)
            if st != 200 or not isinstance(data, dict) or "keys" not in data:
                raise AuthFailed(f"unduh JWKS gagal (HTTP {st})")
            self._jwks = data
        return self._jwks

    # -- authorize ---------------------------------------------------------
    def authorize_url(self, state: str, nonce: str = "",
                      code_verifier: str = "", scope: Optional[list] = None,
                      login_hint: str = "", extra: Optional[dict] = None) -> str:
        meta = self.discover()
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(scope or ["openid", "email", "profile", "groups"]),
            "state": state,
        }
        if nonce:
            params["nonce"] = nonce
        if login_hint:
            params["login_hint"] = login_hint
        if code_verifier:
            params["code_challenge"] = b64url(
                hashlib.sha256(code_verifier.encode()).digest())
            params["code_challenge_method"] = "S256"
        params.update(extra or {})
        return f"{meta['authorization_endpoint']}?{urllib.parse.urlencode(params)}"

    # -- token -------------------------------------------------------------
    def exchange_code(self, code: str, code_verifier: str = "") -> dict:
        meta = self.discover()
        form = {"grant_type": "authorization_code", "code": code,
                "redirect_uri": self.redirect_uri,
                "client_id": self.client_id}
        if code_verifier:
            form["code_verifier"] = code_verifier
        if self.client_secret:
            form["client_secret"] = self.client_secret
        st, data = self._json(
            meta["token_endpoint"], data=urllib.parse.urlencode(form).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST")
        if st != 200 or "id_token" not in data:
            raise AuthFailed(f"token exchange gagal (HTTP {st}): "
                             f"{redact(data)}")
        return data

    # -- verifikasi ID token ----------------------------------------------
    def verify_id_token(self, id_token: str, nonce: str = "",
                        audience: str = "") -> dict:
        """Verifikasi signature (JWKS) + iss/aud/exp/nonce. Return claims."""
        import jwt as pyjwt
        header = pyjwt.get_unverified_header(id_token)
        kid = header.get("kid")
        jwk = None
        for k in self.jwks().get("keys", []):
            if not kid or k.get("kid") == kid:
                jwk = k
                break
        if jwk is None:
            raise AuthFailed(f"kid {kid!r} tidak ada di JWKS IdP")
        key = pyjwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
        claims = pyjwt.decode(
            id_token, key, algorithms=[jwk.get("alg") or "RS256"],
            audience=audience or self.client_id,
            issuer=self.discover().get("issuer"), options={"verify_exp": True})
        if nonce and claims.get("nonce") != nonce:
            raise AuthFailed("nonce ID token tidak cocok (potensi replay)")
        return claims

    # -- userinfo ----------------------------------------------------------
    def userinfo(self, access_token: str) -> dict:
        meta = self.discover()
        uri = meta.get("userinfo_endpoint")
        if not uri:
            raise AuthFailed("discovery tidak memuat userinfo_endpoint")
        st, data = self._json(uri, headers={"Authorization": f"Bearer {access_token}"})
        if st != 200:
            raise AuthFailed(f"userinfo gagal (HTTP {st})")
        return data

    def end_session_url(self, id_token: str = "",
                        post_logout_redirect: str = "") -> str:
        meta = self.discover()
        uri = meta.get("end_session_endpoint")
        if not uri:
            raise AuthFailed("discovery tidak memuat end_session_endpoint")
        q = {}
        if id_token:
            q["id_token_hint"] = id_token
        if post_logout_redirect:
            q["post_logout_redirect_uri"] = post_logout_redirect
        return f"{uri}?{urllib.parse.urlencode(q)}" if q else uri


class LdapDirectory:
    """Direktori LDAP NYATA (ldap3): bind akun layanan -> cari -> bind user.

    Pola dua langkah adalah cara standar LDAP: akun layanan (punya capability
    `search`) menemukan DN pengguna, lalu koneksi BARU mencoba bind dengan DN
    itu + password yang diketik pengguna. Password TIDAK pernah dibandingkan
    di sisi aplikasi — server LDAP yang memutuskan.
    """

    def __init__(self, server_url: str = "ldap://127.0.0.1:3893",
                 base_dn: str = "dc=katalir,dc=test",
                 bind_dn: str = "", bind_password: str = "",
                 user_filter: str = "(mail={login})",
                 attrs: Optional[list] = None, timeout: float = 10.0) -> None:
        self.server_url = server_url
        self.base_dn = base_dn
        self.bind_dn = bind_dn
        self.bind_password = bind_password
        self.user_filter = user_filter
        self.attrs = attrs or ["cn", "mail", "givenName", "sn", "memberOf",
                               "uidNumber", "accountStatus"]
        self.timeout = float(timeout)

    # -- koneksi -----------------------------------------------------------
    def _server(self):
        import ldap3
        parsed = urllib.parse.urlparse(self.server_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (636 if parsed.scheme == "ldaps" else 389)
        use_ssl = parsed.scheme == "ldaps"
        # get_info=NONE WAJIB: glauth menutup koneksi saat diminta schema
        # (subschemaSubentry), sehingga bind gagal dengan "invalidCredentials"
        # yang menyesatkan. Ini temuan nyata saat binding, bukan teori.
        return ldap3.Server(host, port=port, use_ssl=use_ssl,
                            get_info=ldap3.NONE, connect_timeout=self.timeout)

    def _service_conn(self):
        import ldap3
        return ldap3.Connection(self._server(), user=self.bind_dn,
                                password=self.bind_password, auto_bind=True,
                                receive_timeout=self.timeout)

    def available(self) -> bool:
        try:
            import ldap3  # noqa: F401
        except ImportError:
            return False
        try:
            c = self._service_conn()
            c.unbind()
            return True
        except Exception:  # noqa: BLE001
            return False

    # -- pencarian ---------------------------------------------------------
    def find_user(self, login: str) -> Optional[dict]:
        """Cari pengguna berdasarkan `user_filter` ({login} disubstitusi)."""
        import ldap3
        filt = self.user_filter.replace("{login}", str(login))
        c = self._service_conn()
        try:
            c.search(self.base_dn, filt, search_scope=ldap3.SUBTREE,
                     attributes=self.attrs)
            if not c.entries:
                return None
            e = c.entries[0]
            d = {k: (e[k].values if e[k] else []) for k in e.entry_attributes}
            flat = {k: (v[0] if isinstance(v, list) and len(v) == 1 else v)
                    for k, v in d.items()}
            groups = flat.get("memberOf") or []
            if isinstance(groups, str):
                groups = [groups]
            return {"dn": e.entry_dn,
                    "email": str(flat.get("mail") or ""),
                    "name": str(flat.get("givenName") or flat.get("cn") or ""),
                    "cn": str(flat.get("cn") or ""),
                    "groups": list(groups),
                    "raw": d}
        finally:
            try:
                c.unbind()
            except Exception:  # noqa: BLE001
                pass

    # -- autentikasi -------------------------------------------------------
    def bind(self, login: str, password: str) -> bool:
        """Bind sebagai pengguna (password dinilai oleh SERVER LDAP)."""
        if not password:
            return False
        rec = self.find_user(login)
        if not rec:
            return False
        import ldap3
        try:
            c = ldap3.Connection(self._server(), user=rec["dn"],
                                 password=password, auto_bind=True,
                                 receive_timeout=self.timeout)
            c.unbind()
            return True
        except ldap3.core.exceptions.LDAPBindError:
            return False
        except Exception:  # noqa: BLE001 - jaringan/limit -> anggap gagal
            return False

    def identity(self, login: str, password: str = "", org: str = "") -> Identity:
        rec = self.find_user(login)
        if not rec:
            raise AuthFailed(f"pengguna LDAP tidak ditemukan: {login}")
        if password and not self.bind(login, password):
            raise AuthFailed("bind LDAP gagal (kredensial salah)")
        status = rec["raw"].get("accountStatus")
        if status and (status[0] if isinstance(status, list) else status) \
                not in ("active", None):
            raise AuthFailed(f"akun LDAP tidak aktif: {login}")
        return Identity(email=rec["email"] or f"{login}@{self.base_dn}",
                        name=rec["name"], groups=rec["groups"], provider="ldap",
                        org=org, subject=rec["cn"] or login)


class SamlVerifier:
    """Verifikasi XML-DSig assertion SAML NYATA memakai signxml (X.509)."""

    def __init__(self, cert_pem: str = "") -> None:
        self.cert_pem = cert_pem

    def verify(self, assertion_xml: str, cert_pem: str = "") -> str:
        """Verifikasi tanda tangan. Return XML (string) yang sudah tervalidasi.

        Menerima XML mentah ATAU `SAMLResponse` base64 (binding POST) —
        dinormalisasi dulu lewat `decode_saml_response`.
        """
        from signxml import XMLVerifier
        cert = cert_pem or self.cert_pem
        if not cert:
            raise AuthFailed("sertifikat IdP SAML tidak tersedia")
        assertion_xml = decode_saml_response(assertion_xml)
        try:
            hasil = XMLVerifier().verify(assertion_xml, x509_cert=cert)
        except Exception as exc:  # noqa: BLE001
            raise AuthFailed(f"verifikasi tanda tangan SAML gagal: "
                             f"{type(exc).__name__}: {exc}") from exc
        # `signed_xml` adalah elemen lxml, bukan string -> serialisasi ulang
        # supaya pemanggil bisa meneruskannya ke parser yang mengharap teks.
        signed = getattr(hasil, "signed_xml", None)
        if signed is None:
            return assertion_xml
        if isinstance(signed, (str, bytes)):
            return signed if isinstance(signed, str) else signed.decode()
        try:
            return ET.tostring(signed, encoding="unicode")
        except Exception:  # noqa: BLE001
            return assertion_xml

    @staticmethod
    def fetch_idp_metadata(url: str, timeout: float = 20.0) -> dict:
        """Ambil metadata IdP SAML NYATA dan tarik SSO URL + sertifikatnya."""
        op = http_opener()
        req = urllib.request.Request(url, headers={"User-Agent": "Katalir-SSO/1.0"})
        try:
            xml = op.open(req, timeout=timeout).read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            raise AuthFailed(f"unduh metadata IdP gagal: "
                             f"{type(exc).__name__}: {exc}") from exc
        out = {"raw": xml}
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            raise AuthFailed(f"metadata IdP bukan XML valid: {exc}") from exc
        for el in root.iter():
            tag = el.tag.split("}")[-1]
            if tag == "SingleSignOnService" and el.attrib.get("Binding", "").endswith("HTTP-Redirect"):
                out.setdefault("sso_url", el.attrib.get("Location", ""))
            elif tag == "X509Certificate" and el.text:
                out.setdefault("cert", el.text.strip())
            elif tag == "EntityDescriptor":
                out.setdefault("entity_id", el.attrib.get("entityID", ""))
        return out
