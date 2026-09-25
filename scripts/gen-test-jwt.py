"""Generate a short-lived Supabase test JWT for authenticated production audit."""
import os, time, json, pathlib, httpx
from dotenv import load_dotenv
load_dotenv()
url = os.environ["SUPABASE_URL"]
service_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
anon_key = os.environ.get("SUPABASE_PUBLISHABLE_KEY") or os.environ["SUPABASE_KEY"]
email = f"agent-test-{int(time.time())}@katalir.local"
password = "AgentTest123!@#"
with httpx.Client(timeout=30) as c:
    r = c.post(f"{url}/auth/v1/admin/users", headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"}, json={"email": email, "password": password, "email_confirm": True})
    r.raise_for_status(); user_id = r.json()["id"]
    r = c.post(f"{url}/auth/v1/token?grant_type=password", headers={"apikey": anon_key}, json={"email": email, "password": password})
    r.raise_for_status(); session = r.json()
pathlib.Path("test-jwt.txt").write_text(session["access_token"], encoding="utf-8")
pathlib.Path(".agent-test-user-id").write_text(user_id, encoding="utf-8")
pathlib.Path(".agent-test-session.json").write_text(json.dumps({"user_id": user_id, "email": email, "url": url, "access_token": session["access_token"], "refresh_token": session.get("refresh_token", "")}), encoding="utf-8")
print(f"USER_CREATED={user_id}")
print(f"JWT_SAVED=yes LENGTH={len(session['access_token'])}")
