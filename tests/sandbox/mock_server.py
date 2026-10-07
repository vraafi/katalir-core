"""mock_server.py — server mock untuk E2E test (tanpa kredensial asli).

PRINSIP (mockworld-mcp / apidog, 2026)
--------------------------------------
Mock mengembalikan respons yang **realistis dan sesuai skema**, tanpa
backend maupun kredensial sungguhan. "A misbehaving agent has nothing
real to reach" — tidak ada token asli, tidak ada channel asli, tidak ada
repositori asli yang bisa disentuh.

TRANSPORT
---------
Server ini dijalankan **in-process** lewat `httpx.ASGITransport`, jadi:
  * tidak membuka port,
  * tidak ada paket yang keluar ke jaringan,
  * deterministik dan cepat.

Ini juga menghindari (dengan sengaja) SSRF guard `tools._host_blocked`,
yang MENOLAK host loopback/metadata — guard itu diuji terpisah sebagai
bukti kebijakan jaringan sandbox benar-benar aktif.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="katalir-sandbox-mock", version="1.0.0")

#: Penghitung untuk endpoint "flaky" (gagal N kali lalu sukses).
_FLAKY_COUNTER: dict[str, int] = {}


@app.get("/mock/health")
def mock_health() -> dict:
    return {"ok": True, "service": "katalir-sandbox-mock"}


@app.get("/mock/telegram/sendMessage")
def mock_telegram_send(chat_id: str, text: str) -> dict:
    """Meniru Telegram sendMessage — respons skema-valid."""
    return {"ok": True, "result": {"message_id": 999, "chat": {"id": chat_id},
                                   "text": text}}


@app.get("/mock/telegram/echo_token")
def mock_telegram_echo_token(token: str) -> dict:
    """Mengembalikan token yang diterima APA ADANYA.

    Dipakai untuk membuktikan redaktor menangkap kredensial yang muncul di
    BODY respons (bukan hanya di header) — jalur kebocoran yang realistis.
    """
    return {"ok": True, "result": {"echoed": token}}


@app.get("/mock/sheets/write")
def mock_sheets_write(spreadsheet_id: str, range: str = "A1",
                      values: str = "") -> dict:
    cells = [v for v in values.split(",") if v != ""]
    return {"updatedCells": len(cells), "spreadsheetId": spreadsheet_id,
            "range": range}


class GithubCommit(BaseModel):
    repo: str
    path: str
    content: str


@app.post("/mock/github/commit")
def mock_github_commit(payload: GithubCommit) -> dict:
    return {"sha": "abc123def456",
            "url": f"https://github.com/{payload.repo}/blob/main/{payload.path}"}


@app.get("/mock/http/echo")
def mock_http_echo(url: str) -> dict:
    return {"status": 200, "data": {"id": 1, "title": "Mock Post", "url": url}}


@app.get("/mock/http/fail")
def mock_http_fail(code: int = 500) -> dict:
    """Endpoint yang SELALU gagal — untuk menguji penanganan error."""
    raise HTTPException(status_code=code, detail="mock failure (disengaja)")


@app.get("/mock/http/notfound")
def mock_http_notfound() -> dict:
    raise HTTPException(status_code=404, detail="mock not found (disengaja)")


@app.get("/mock/http/flaky")
def mock_http_flaky(key: str = "default", fail_times: int = 2) -> dict:
    """Gagal `fail_times` kali lalu sukses — untuk menguji retry/healing."""
    seen = _FLAKY_COUNTER.get(key, 0)
    _FLAKY_COUNTER[key] = seen + 1
    if seen < fail_times:
        raise HTTPException(status_code=503, detail=f"mock sibuk (ke-{seen + 1})")
    return {"ok": True, "attempt": seen + 1, "key": key}


def reset_flaky() -> None:
    """Kosongkan penghitung flaky (dipakai antar-test)."""
    _FLAKY_COUNTER.clear()


def client():
    """Klien httpx yang menuju app ini in-process (tanpa jaringan)."""
    import httpx

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://sandbox.mock",
        timeout=10.0,
    )


if __name__ == "__main__":  # pragma: no cover - utilitas manual
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8899, log_level="info")
