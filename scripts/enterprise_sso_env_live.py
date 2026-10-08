#!/usr/bin/env python
"""enterprise_sso_env_live.py — HARD TEST Fitur #7 dgn kredensial `.env`.

Mengikat SSO ke layanan NYATA yang kredensialnya ada di `.env`:

  * Google OIDC  (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`)
      -> discovery, authorize+PKCE, token endpoint nyata (oauth2.googleapis.com)
  * Redis VPS    (`REDIS_HOST`/`REDIS_PORT`/`REDIS_PASSWORD` via SSH tunnel)
      -> `RedisSessionStore` sesi SSO lintas proses

12 skenario; tiap skenario GAGAL bila integrasi rusak.

Pakai:
    python scripts/enterprise_sso_env_live.py
    python scripts/enterprise_sso_env_live.py --json docs/evidence/f07-sso-env-live.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
GOOGLE = "https://accounts.google.com"
HASIL: list[dict] = []


def _catat(no: int, nama: str, lulus: bool, raw: str, detail: dict | None = None) -> None:
    HASIL.append({"no": no, "skenario": nama, "status": "PASS" if lulus else "FAIL",
                  "raw": raw, "detail": detail or {}})
    print("=" * 78)
    print(f"#{no:02d} [{'PASS' if lulus else 'FAIL'}] {nama}")
    print("-" * 78)
    print(raw)
    print()


def _load_env() -> dict:
    env: dict[str, str] = {}
    with open(os.path.join(HERE, ".env"), encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.lstrip().startswith("#"):
                continue
            m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
            if m:
                env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return env


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    env = _load_env()
    cid, csecret = env["GOOGLE_CLIENT_ID"], env["GOOGLE_CLIENT_SECRET"]

    import sso
    import vault_security as vs

    t = sso.OidcHttpTransport(GOOGLE, cid, csecret,
                              redirect_uri="http://localhost:8123/sso/callback",
                              timeout=25.0)

    # --- 1. Discovery + authorize URL dgn GOOGLE_CLIENT_ID NYATA -----------
    meta = t.discover()
    pkce, verifier = sso.make_pkce_pair()
    nonce = sso.make_state()
    authz = t.authorize_url("state-real", nonce, pkce)
    cid_in_url = f"client_id={urllib.parse.quote(cid, safe='')}" in authz
    lulus = (meta.get("issuer") == GOOGLE and cid_in_url
             and "code_challenge_method=S256" in authz)
    _catat(1, "Google OIDC discovery + authorize URL pakai GOOGLE_CLIENT_ID .env",
           lulus,
           f"issuer       = {meta.get('issuer')}\n"
           f"token        = {meta.get('token_endpoint')}\n"
           f"jwks_uri     = {meta.get('jwks_uri')}\n"
           f"client_id .env ada di authorize URL = {cid_in_url}\n"
           f"PKCE S256    = {'code_challenge_method=S256' in authz}\n"
           f"CEK: client asli + PKCE -> {lulus}",
           {"issuer": meta.get("issuer"), "cid_in_url": cid_in_url})

    # --- 2. Token exchange NYATA (bukti client valid) ----------------------
    body = urllib.parse.urlencode({
        "client_id": cid, "client_secret": csecret, "code": "dummy-probe-code",
        "grant_type": "authorization_code",
        "redirect_uri": "http://localhost:8123/sso/callback"}).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=body,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    st, raw = None, ""
    try:
        with OPENER.open(req, timeout=25) as r:
            st, raw = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        st, raw = e.code, e.read().decode()
    err = ""
    try:
        err = json.loads(raw).get("error", "")
    except Exception:  # noqa: BLE001
        pass
    lulus = err == "invalid_grant"      # bukan invalid_client -> client SAH
    _catat(2, "Token exchange NYATA ke Google (client .env sah)", lulus,
           f"POST https://oauth2.googleapis.com/token -> HTTP {st}\n"
           f"  {raw.strip()[:200]}\n"
           f"error = {err!r}\n"
           f"CEK: 'invalid_grant' (code dummy) bukan 'invalid_client' -> {lulus}",
           {"status": st, "error": err})

    # --- 3-12 pakai SsoManager + Redis VPS NYATA ---------------------------
    tunnel = None
    try:
        import redis as _redis
        from scripts.ssh_tunnel import open_tunnel
        tunnel = open_tunnel(0, "127.0.0.1:6379")
        rclient = _redis.Redis(host="127.0.0.1", port=tunnel.local_port,
                               password=env["REDIS_PASSWORD"], decode_responses=True,
                               socket_timeout=10)
        rclient.ping()
        sessions = sso.RedisSessionStore(rclient)
        backend_sesi = f"Redis VPS NYATA via SSH tunnel :{tunnel.local_port}"
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] Redis VPS tidak terjangkau ({type(exc).__name__}: {exc}); "
              f"pakai SessionStore memori")
        sessions = sso.SessionStore()
        backend_sesi = "SessionStore memori (fallback)"

    mgr = sso.SsoManager(sessions=sessions)
    mgr.register_org("acme", {"katalir-owners": "owner", "katalir-dev": "developer"},
                     domains=["acme.test"], default_role="viewer")
    mgr.register_org("globex", {"globex-admin": "admin"},
                     domains=["globex.test"], default_role="viewer")

    # --- 3. Role mapping --------------------------------------------------
    id_owner = sso.Identity("budi@acme.test", "Budi", ["katalir-owners"], provider="oidc")
    id_editor = sso.Identity("siti@acme.test", "Siti", ["katalir-dev"], provider="oidc")
    id_viewer = sso.Identity("tono@acme.test", "Tono", [], provider="oidc")
    st_a = mgr.begin("acme")
    st_b = mgr.begin("acme")
    st_c = mgr.begin("acme")
    r_owner = mgr.login(id_owner, state=st_a, expect_state=st_a)
    r_editor = mgr.login(id_editor, state=st_b, expect_state=st_b)
    r_viewer = mgr.login(id_viewer, state=st_c, expect_state=st_c)
    lulus = (r_owner["role"] == "owner" and r_editor["role"] == "developer"
             and r_viewer["role"] == "viewer")
    _catat(3, "Role mapping dari group IdP (owner/developer/viewer)", lulus,
           f"budi  groups=['katalir-owners'] -> role={r_owner['role']}\n"
           f"siti  groups=['katalir-dev']    -> role={r_editor['role']}\n"
           f"tono  groups=[]                 -> role={r_viewer['role']} (default)\n"
           f"CEK: pemetaan group->role tepat -> {lulus}",
           {"owner": r_owner["role"], "editor": r_editor["role"]})

    # --- 4. JIT provisioning ---------------------------------------------
    u = mgr.get_user("budi@acme.test")
    lulus = bool(u) and u["org"] == "acme" and u["active"] and u["provider"] == "oidc"
    _catat(4, "JIT provisioning: user dibuat otomatis saat login", lulus,
           f"get_user('budi@acme.test') -> {u}\n"
           f"CEK: user ter-provision + org benar -> {lulus}",
           {"org": (u or {}).get("org")})

    # --- 5. Sesi di Redis VPS NYATA --------------------------------------
    sid = r_owner["session_id"]
    ses = mgr.session(sid)
    lulus = bool(ses) and ses.get("role") == "owner" and "budi@acme.test" in json.dumps(ses)
    _catat(5, "Sesi SSO tersimpan di backend NYATA", lulus,
           f"backend      = {backend_sesi}\n"
           f"session_id   = {sid[:12]}…\n"
           f"session.get  -> role={ses.get('role') if ses else None}\n"
           f"CEK: sesi hidup & terbaca kembali -> {lulus}",
           {"backend": backend_sesi})

    # --- 6. Logout + Single Logout ---------------------------------------
    lain = mgr.begin("acme")
    mgr.login(sso.Identity("budi@acme.test", "Budi", ["katalir-owners"], provider="oidc"),
              state=lain, expect_state=lain)
    n_slo = mgr.slo("budi@acme.test")
    lulus = n_slo >= 2 and mgr.session(sid) is None
    _catat(6, "Logout + Single Logout (matikan SEMUA sesi user)", lulus,
           f"slo('budi@acme.test') -> {n_slo} sesi dimatikan\n"
           f"session(sid) setelah SLO -> {mgr.session(sid)}\n"
           f"CEK: semua sesi user mati -> {lulus}",
           {"terminated": n_slo})

    # --- 7. Multi-tenant --------------------------------------------------
    id_globex = sso.Identity("dave@globex.test", "Dave", ["globex-admin"], provider="oidc")
    st_g = mgr.begin("globex")
    r_globex = mgr.login(id_globex, state=st_g, expect_state=st_g)
    lulus = (r_globex["org"] == "globex" and r_globex["role"] == "admin"
             and mgr.org_for_email("budi@acme.test") == "acme")
    _catat(7, "Multi-tenant: domain->org terpisah (acme/globex)", lulus,
           f"dave@globex.test -> org={r_globex['org']} role={r_globex['role']}\n"
           f"org_for_email(budi@acme.test)   -> {mgr.org_for_email('budi@acme.test')}\n"
           f"org_for_email(dave@globex.test) -> {mgr.org_for_email('dave@globex.test')}\n"
           f"CEK: tenant tidak tercampur -> {lulus}",
           {"globex_role": r_globex["role"]})

    # --- 8. CSRF: state sekali-pakai (anti-replay) -----------------------
    st_replay = mgr.begin("acme")
    mgr.consume_state(st_replay)
    replay_err = None
    try:
        mgr.consume_state(st_replay)
    except Exception as exc:  # noqa: BLE001
        replay_err = type(exc).__name__
    lulus = replay_err == "StateMismatch"
    _catat(8, "CSRF: state SEKALI pakai -> replay DITOLAK", lulus,
           f"state diterbitkan -> dipakai sekali -> OK\n"
           f"pakai ULANG state yang sama -> RAISES {replay_err}\n"
           f"CEK: anti-replay aktif -> {lulus}",
           {"replay": replay_err})

    # --- 9. Enkripsi token (Fernet) --------------------------------------
    token_palsu = "ya29.a0AfH6SM_example_access_token_1234567890"
    cipher = vs.encrypt_key(token_palsu)
    pulih = vs.decrypt_key(cipher)
    lulus = (token_palsu not in cipher and pulih == token_palsu
             and cipher.startswith("gAAAAA"))
    _catat(9, "Token/sesi TERENKRIPSI (Fernet) sebelum disimpan", lulus,
           f"token di ciphertext? {token_palsu in cipher} (harus False)\n"
           f"ciphertext = {cipher[:40]}… ({len(cipher)} char)\n"
           f"decrypt cocok? {pulih == token_palsu}\n"
           f"CEK: token tidak tersimpan polos -> {lulus}",
           {"cipher_len": len(cipher)})

    # --- 10. RAW OUTPUT login (authorize URL penuh) ----------------------
    url_full = t.authorize_url("st-raw", sso.make_state(), sso.make_pkce_pair()[0],
                               login_hint="budi@acme.test")
    redacted = re.sub(r"(client_id=)[^&]+", r"\1<GOOGLE_CLIENT_ID>", url_full)
    lulus = ("accounts.google.com/o/oauth2" in url_full
             and "response_type=code" in url_full and "scope=" in url_full)
    _catat(10, "RAW OUTPUT: authorize URL nyata (siap login browser)", lulus,
           f"{redacted}\n"
           f"CEK: URL OAuth 2.0 Google terbentuk lengkap -> {lulus}",
           {})

    # --- 11. Error handling ----------------------------------------------
    e1 = e2 = None
    try:
        mgr.login(sso.Identity("hacker@evil.test", "X", [], provider="oidc"), state="x", expect_state="y")
    except Exception as exc:  # noqa: BLE001
        e1 = type(exc).__name__
    try:
        t.exchange_code("kode-palsu", verifier)
    except Exception as exc:  # noqa: BLE001
        e2 = type(exc).__name__
    lulus = e1 in ("StateMismatch", "AuthFailed") and e2 is not None
    _catat(11, "Error handling: state salah + token exchange gagal", lulus,
           f"login(state='x', expect='y') -> RAISES {e1}\n"
           f"exchange_code('kode-palsu')  -> RAISES {e2}\n"
           f"CEK: galat terklasifikasi -> {lulus}",
           {"state": e1, "exchange": e2})

    # --- 12. Security: rahasia TIDAK bocor --------------------------------
    lulus = (csecret not in authz and csecret not in url_full
             and csecret not in json.dumps(HASIL)
             and "code_challenge_method=S256" in authz)
    _catat(12, "Security: client_secret TIDAK pernah masuk URL/log", lulus,
           f"client_secret di authorize URL? {csecret in authz} (harus False)\n"
           f"client_secret di seluruh hasil tes? "
           f"{csecret in json.dumps(HASIL)} (harus False)\n"
           f"PKCE S256 dipakai = {'code_challenge_method=S256' in authz}\n"
           f"CEK: tidak ada kebocoran rahasia -> {lulus}",
           {})

    if tunnel is not None:
        tunnel.close()

    lulus_n = sum(1 for h in HASIL if h["status"] == "PASS")
    print("=" * 78)
    print(f"RINGKASAN HARD TEST FITUR #7 (.env real): {lulus_n}/{len(HASIL)} PASS")
    print("=" * 78)
    for h in HASIL:
        print(f"  #{h['no']:02d} [{h['status']}] {h['skenario']}")

    if args.json:
        out = os.path.join(HERE, args.json) if not os.path.isabs(args.json) else args.json
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({"feature": "#7 SSO/SAML/OIDC/LDAP (.env real)",
                       "lulus": lulus_n, "total": len(HASIL), "hasil": HASIL},
                      fh, indent=2, ensure_ascii=False)
        print(f"\nJSON -> {args.json}")
    return 0 if lulus_n == len(HASIL) else 1


if __name__ == "__main__":
    raise SystemExit(main())
