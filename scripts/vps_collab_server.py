"""Server kolaborasi real-time (Yjs/CRDT) untuk VPS.

Menjalankan CollabASGIServer dari collab_realtime.py secara berdiri sendiri
(tanpa api_server penuh) — autentikasi JWT tetap NYATA via security.py
(JWKS/fallback jaringan ke Supabase).

Pakai:
    python3 vps_collab_server.py --port 8140 --host 127.0.0.1
Env wajib:
    SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY (atau SUPABASE_KEY)
"""
from __future__ import annotations

import argparse
import contextlib
import os
import sys


def build_app():
    import uvicorn  # noqa: F401 — dipakai caller

    from fastapi import FastAPI

    import collab_realtime as cr

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        # WebsocketServer HARUS di-start (persis seperti lifespan api_server):
        # tanpa ini -> RuntimeError "The WebsocketServer is not running".
        async with cr.WS_SERVER:
            yield

    app = FastAPI(lifespan=lifespan)
    app.mount("/", cr.ASGI)  # path = /<room>?token=<JWT>
    return app


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8140)
    args = ap.parse_args()

    if not os.getenv("SUPABASE_URL"):
        print("!! SUPABASE_URL tidak diset", file=sys.stderr)
        return 2

    import uvicorn

    app = build_app()
    config = uvicorn.Config(app, host=args.host, port=args.port,
                            log_level="warning")
    server = uvicorn.Server(config)
    print(f"collab-vps listening on {args.host}:{args.port}", flush=True)
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
