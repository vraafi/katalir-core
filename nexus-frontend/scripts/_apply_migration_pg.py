import os, sys, re
from pathlib import Path

# baca root .env
envtext = Path(__file__).resolve().parent.parent.parent / ".env"
vars_ = {}
for line in envtext.read_text(encoding="utf-8").splitlines():
    m = re.match(r"\s*([A-Z0-9_]+)=(.*)", line)
    if m:
        vars_[m.group(1)] = m.group(2).strip()

url = vars_.get("SUPABASE_URL", "")
pw = vars_.get("SUPABASE_DB_PASSWORD", "")
if not url or not pw:
    print("ERR env supabase url/password missing")
    sys.exit(2)
ref = url.replace("https://", "").split(".")[0]
host = f"db.{ref}.supabase.co"

import pg8000.native

try:
    con = pg8000.native.Connection(
        user="postgres",
        password=pw,
        database="postgres",
        host=host,
        port=5432,
        ssl_context=True,
        timeout=20,
    )
except Exception as e:
    print("CONNECT_ERR=" + str(e)[:300])
    sys.exit(3)
print("CONNECTED host=" + host)

sql = Path(__file__).resolve().parent.parent.parent / "migrations" / "2026_dedupe_chat_messages.sql"
runs = sql.read_text(encoding="utf-8").split(";")
ok = 0
for stmt in runs:
    s = stmt.strip()
    if not s:
        continue
    try:
        con.run(s)
        ok += 1
    except Exception as e:
        print("STMT_ERR=" + str(e)[:300])
print("STMT_RAN=" + str(ok))

# verifikasi kolom + index
try:
    cols = con.run("select column_name from information_schema.columns where table_name='chat_messages' and column_name='client_request_id'")
    idx = con.run("select indexname from pg_indexes where indexname like 'uq_chat_messages%'")
    print("COLUMN_EXISTS=" + str(len(cols) > 0))
    print("INDEXES=" + str([r[0] for r in idx]))
except Exception as e:
    print("VERIFY_ERR=" + str(e)[:300])
con.close()
print("DONE")