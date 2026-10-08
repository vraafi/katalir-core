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

import re
import secrets
import time
import urllib.parse
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional
from xml.etree import ElementTree as ET

#: Urutan prioritas peran (indeks lebih tinggi = lebih berkuasa).
ROLE_PRIORITY = ["viewer", "developer", "admin", "owner"]

MASK = "***"
_TOKEN_RE = re.compile(
    r"(eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}|"
    r"Bearer\s+[A-Za-z0-9._\-]{8,}|SAMLResponse=[A-Za-z0-9+/=]{16,})")


class SsoError(Exception):
    pass


class StateMismatch(SsoError):
    """CSRF: `state` tidak cocok dengan yang disimpan."""


class SessionExpired(SsoError):
    pass


class AuthFailed(SsoError):
    pass


def redact(text: Any) -> Any:
    if isinstance(text, str):
        return _TOKEN_RE.sub(MASK, text)
    if isinstance(text, dict):
        return {k: redact(v) for k, v in text.items()}
    if isinstance(text, list):
        return [redact(v) for v in text]
    return text


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
            elif tag == "AttributeValue" and nama_atr is not None and el.text:
                attrs[nama_atr].append(el.text.strip())
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
        """Selesaikan login: verifikasi state, provisioning JIT, buat sesi."""
        if expect_state:
            verify_state(expect_state, state)
            # state bersifat SEKALI PAKAI (anti-replay)
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
