"""Independent safety audit of the tools/call run.

Does NOT trust the sweep script's own filter. Re-derives, from the recorded
tool names, that every tool actually called was inside the read-only allowlist
and outside the mutating blocklist. If a mutating tool ever slips through, the
"call_verified" number is not worth publishing.

Also reports what the number does and does not mean.
"""
import json
import pathlib
import sys

REPORT = json.loads(
    pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "glama-connector-call-batch1.json")
    .read_text(encoding="utf-8")
)

READ_VERBS = (
    "get", "list", "fetch", "read", "search", "query", "find", "lookup",
    "describe", "show", "view", "retrieve", "count", "stats", "info",
    "status", "health", "ping", "echo", "check", "validate", "resolve",
    "browse", "enumerate", "about", "capabilities", "schema", "inspect",
)
MUTATING_VERBS = (
    "create", "update", "delete", "remove", "write", "send", "post", "put",
    "patch", "execute", "exec", "run", "invoke", "mutate", "set", "add",
    "insert", "upsert", "destroy", "drop", "truncate", "enable", "disable",
    "start", "stop", "cancel", "refund", "pay", "charge", "transfer",
    "subscribe", "unsubscribe", "import", "generate", "build", "deploy",
    "publish", "notify", "email", "upload", "commit", "merge", "approve",
    "reject", "install", "register", "signup", "password", "credential",
    "token", "secret", "revoke", "grant", "assign", "move", "rename",
    "replace", "clear", "reset", "close", "archive", "restore", "sync",
)

recs = REPORT["records"]
verified = [r for r in recs if r["status"] == "call_verified"]

violations_mutating, violations_notread, empty_tool = [], [], []
for r in verified:
    t = (r.get("tool") or "").strip()
    low = t.lower()
    if not t:
        empty_tool.append(r["id"])
        continue
    hits = [v for v in MUTATING_VERBS if v in low]
    if hits:
        violations_mutating.append((r["id"], t, hits))
    if not any(v in low for v in READ_VERBS):
        violations_notread.append((r["id"], t))

print(f"attempted            = {REPORT['attempted']}")
print(f"call_verified        = {REPORT['call_verified_total']}")
print(f"counts               = {json.dumps(REPORT['counts'])}")
print()
print("--- SAFETY AUDIT (independent re-derivation) ---")
print(f"tools with a MUTATING verb : {len(violations_mutating)}")
for i, (cid, t, hits) in enumerate(violations_mutating[:15], 1):
    print(f"   VIOLATION {cid} tool={t} hits={hits}")
print(f"tools outside read-allowlist: {len(violations_notread)}")
for cid, t in violations_notread[:15]:
    print(f"   OUTSIDE {cid} tool={t}")
print(f"verified rows with no tool name: {len(empty_tool)}")

# how many distinct tools, and the most common ones
from collections import Counter  # noqa: E402

tools = Counter((r.get("tool") or "").strip() for r in verified)
print(f"\ndistinct tools called = {len(tools)}")
print("top 8 =", tools.most_common(8))

ok = not violations_mutating and not violations_notread and not empty_tool
print(f"\nSAFETY_AUDIT={'PASS' if ok else 'FAIL'}")
print("NOTE: call_verified means one read-only tool returned a real result on a")
print("      no-auth connector. It is NOT a full integration test: single call,")
print("      synthetic args, third-party servers, no auth, no persistence.")
sys.exit(0 if ok else 1)
