"""Check the dedup toggle end to end: both views must answer, be different, and
keep the tab count equal to the grid total in whichever view is active.
"""
import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"


def get(path):
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=90) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


code, src = get("/mcp/registry/sources")
raw_counts = src["sources"]
uniq_counts = src.get("sources_unique") or {}
print(f"/mcp/registry/sources -> {code}")
print(f"  raw sources     : {json.dumps(raw_counts)}")
print(f"  unique sources  : {json.dumps(uniq_counts)}")

ok = True
for view in ("all", "unique"):
    counts = raw_counts if view == "all" else uniq_counts
    code, d = get(f"/mcp/registry?view={view}&limit=1")
    if code != 200:
        print(f"view={view} -> HTTP {code} {json.dumps(d)[:160]}")
        ok = False
        continue
    print(f"\nview={view:6s} total={d['total']:,d}  view_field={d.get('view', 'all')}  raw_total={d.get('raw_total', '-')}")
    for k in ["glama", "glama-connector", "composio", "toolsdk", "nango", "metorial"]:
        if not counts.get(k):
            continue
        _, g = get(f"/mcp/registry?view={view}&limit=1&source={k}")
        match = g["total"] == counts[k]
        if not match:
            ok = False
        print(f"   {k:18s} tab={counts[k]:>7,d}  grid={g['total']:>7,d}  {'OK' if match else 'MISMATCH'}")

_, a = get("/mcp/registry?view=all&limit=1")
_, u = get("/mcp/registry?view=unique&limit=1")
print(f"\nall={a['total']:,d}  unique={u['total']:,d}  collapsed={a['total']-u['total']:,d}")
if u["total"] >= a["total"]:
    print("FAIL: unique view is not smaller than raw view")
    ok = False

# a rejected view must be a 400, not a silent fallback
code, _ = get("/mcp/registry?view=bogus")
print(f"view=bogus -> {code}", "(want 400)")
if code != 400:
    ok = False

print("\nDEDUP_TOGGLE=OK" if ok else "\nDEDUP_TOGGLE=FAIL")

