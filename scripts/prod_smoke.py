"""Production smoke check. Status codes and byte counts only, no body dump."""
import urllib.error
import urllib.request

URLS = [
    "https://katalir.de5.net/",
    "https://katalir.de5.net/integrations",
    "https://katalir.de5.net/chat",
    "https://katalir.de5.net/pricing",
]
for u in URLS:
    try:
        r = urllib.request.urlopen(
            urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=45
        )
        body = r.read()
        text = body.decode("utf-8", "replace")
        badges = sum(
            text.count(f"badge-{k}")
            for k in ("ready", "auth", "listed", "catalog")
        )
        print(f"{u:44s} -> {r.status}  len={len(body):>7,d}  badges={badges}")
    except urllib.error.HTTPError as e:
        print(f"{u:44s} -> HTTP {e.code}")
    except Exception as e:
        print(f"{u:44s} -> EXC {type(e).__name__} {str(e)[:80]}")
