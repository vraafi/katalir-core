"""PoC harness untuk CVE-2026-48710 (Starlette BadHost).

Memuat aplikasi FastAPI ASLI (bukan replika), lalu mengirim request HTTP
sungguhan lewat uvicorn dengan header `Host` beracun, lalu membandingkan
dengan scope-level check.

Pakai:  python scripts\\security\\poc_badhost.py <path_ke_api_server.py>
"""
import asyncio
import importlib.util
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
os.environ.setdefault("ALLOWED_HOSTS", "katalir.de5.net,web-production-dc90b.up.railway.app,localhost,127.0.0.1")
os.environ.setdefault("RELOAD", "0")

EVIL = "evil.com/health?x="
TARGET_PATH = "/health"


def load_app(path: pathlib.Path):
    # Modul di-load dari path file, jadi `sys.path` TIDAK otomatis memuat root
    # repo - padahal api_server.py meng-import modul-modul root (`database`,
    # `security`, `tools`, ...). Tanpa ini: ModuleNotFoundError: database.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("api_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["api_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod.app


async def raw_asgi(app, host: str, path: str):
    """Scope-crafted: bypass reverse proxy sepenuhnya."""
    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": "GET", "path": path,
        "raw_path": path.encode(), "query_string": b"", "root_path": "",
        "scheme": "http", "headers": [(b"host", host.encode())],
        "client": ("1.1.1.1", 5555), "server": ("backend.internal", 80),
    }
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(m):
        sent.append(m)

    await app(scope, receive, send)
    status = [m for m in sent if m["type"] == "http.response.start"][0]["status"]
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, body


def main() -> int:
    target = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "api_server.py"
    print(f"# PoC target: {target}")
    print(f"# ALLOWED_HOSTS = {os.environ['ALLOWED_HOSTS']}\n")
    app = load_app(target)

    names = [m.cls.__name__ for m in app.user_middleware]
    print("middleware chain (index 0 = OUTERMOST, berjalan pertama):")
    for i, n in enumerate(names):
        print(f"  [{i}] {n}")
    print()

    rows = []
    for label, host in [
        ("LEGIT  (localhost)", "localhost"),
        ("LEGIT  (railway prod domain)", "web-production-dc90b.up.railway.app"),
        ("EVIL   (Host header injection)", EVIL),
    ]:
        status, body = asyncio.run(raw_asgi(app, host, TARGET_PATH))
        rows.append((label, host, status, body[:40]))
        print(f"{label:34s} Host={host:42s} -> HTTP {status}  body={body[:40]!r}")

    evil_status = rows[2][2]
    print()
    print(f"VERDICT: Host-header-injection -> HTTP {evil_status} "
          f"({'TERBLOKIR (mitigasi aktif)' if evil_status == 400 else 'TIDAK TERBLOKIR'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
