# CATATAN: jalankan dari ROOT repo (butuh .autonomous_jwt + .env):
#   python scripts/enterprise_sso_shot.py
# Prasyarat: server uvicorn lokal di port 8123 dengan KATALIR_SSO_CONFIG
# menunjuk ke IdP NYATA (oidc-provider :9443, samlp :7000, glauth :3893).
"""Screenshot halaman Admin SSO (bukti visual Fitur #7).

Alur:
  1. buka /sso/ui di Chromium (Playwright); token disuntik ke localStorage
     SEBELUM skrip halaman berjalan.
  2. klik "Uji discovery IdP" -> halaman memanggil /sso/discovery yang
     MELAKUKAN probe NYATA ke OIDC + SAML IdP.
  3. tunggu panel discovery terisi (issuer + jwks_kids), lalu screenshot.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "http://localhost:8123"
OUT = os.path.join(HERE, "docs", "evidence", "f07-sso-admin.png")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TOK = open(os.path.join(HERE, ".autonomous_jwt"), encoding="utf-8").read().strip()

OIDC_ISSUER = "http://localhost:9443"
SAML_META = "http://localhost:7000/metadata"
LDAP_URL = "ldap://127.0.0.1:3893"
SAML_CERT = "C:/katalir-sso/idp-cert.pem"


def _call(path, timeout=30):
    req = urllib.request.Request(
        BASE + path,
        headers={"Authorization": f"Bearer {TOK}", "Accept": "application/json"})
    try:
        r = OPENER.open(req, timeout=timeout)
        return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def main() -> int:
    cert = ""
    if os.path.exists(SAML_CERT):
        cert = open(SAML_CERT, encoding="utf-8").read().strip()
    cfg = {
        "orgs": {"acme": {
            "role_mapping": {"katalir-admins": "admin",
                             "katalir-owners": "owner",
                             "engineering": "developer"},
            "domains": ["acme.test", "globex.test"], "default_role": "viewer"}},
        "oidc": {"issuer": OIDC_ISSUER, "client_id": "katalir-app",
                 "client_secret": "katalir-oidc-secret",
                 "redirect_uri": "http://localhost:8123/sso/callback/oidc"},
        "ldap": {"server_url": LDAP_URL, "base_dn": "dc=katalir,dc=test",
                 "bind_dn": "cn=svc-bind,cn=svcaccts,dc=katalir,dc=test",
                 "bind_password": "KatalirLdap2026!",
                 "user_filter": "(mail={login})"},
        "saml": {"metadata_url": SAML_META, "cert": cert,
                 "sso_url": "http://localhost:7000/saml/sso"},
    }
    env = dict(os.environ)
    env["KATALIR_SSO_CONFIG"] = json.dumps(cfg)
    env["KATALIR_SSO_ADMINS"] = "otonom-test@katalir-internal.dev"
    env["KATALIR_REDIS_URL"] = "redis://127.0.0.1:6379/0"
    env["PYTHONUNBUFFERED"] = "1"
    log = open(os.path.join(HERE, "docs", "evidence", "f07-shot-server.log"),
               "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api_server:app", "--host", "127.0.0.1",
         "--port", "8123", "--log-level", "warning"],
        cwd=HERE, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(90):
            try:
                OPENER.open(BASE + "/health", timeout=3)
                break
            except Exception:  # noqa: BLE001
                time.sleep(1)
        st, body = _call("/sso/providers")
        print("providers:", st, body[:200])
        st, body = _call("/sso/discovery")
        print("discovery:", st, body[:260])

        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-proxy-server"])
            ctx = browser.new_context(viewport={"width": 1440, "height": 1200},
                                      device_scale_factor=2)
            ctx.add_init_script(
                f"try{{localStorage.setItem('katalir_token', {json.dumps(TOK)});}}"
                f"catch(e){{}}")
            page = ctx.new_page()
            page.goto(BASE + "/sso/ui", wait_until="networkidle", timeout=60000)
            page.click("text=Uji discovery IdP")
            page.wait_for_function(
                "() => (document.getElementById('discovery').textContent||'')"
                ".includes('jwks')", timeout=30000)
            page.wait_for_timeout(900)
            os.makedirs(os.path.dirname(OUT), exist_ok=True)
            page.screenshot(path=OUT, full_page=True)
            print("screenshot ->", OUT)
            browser.close()
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=15)
        except Exception:  # noqa: BLE001
            proc.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
