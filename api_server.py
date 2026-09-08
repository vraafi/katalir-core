# api_server.py - API Gateway (FastAPI) pemisah Frontend/Backend
# =====================================================================
# Jembatan antara UI modern (Next.js nanti) dan mesin Python agent.
#
# Endpoint:
#   POST /chat         -> {prompt, email, session_id?}
#   POST /integrations -> {email, provider, token}
#
# Menangkap CredentialMissingError -> HTTP 200 {status:"needs_credential"}.
#
# Jalankan:
#   uvicorn api_server:app --reload
# =====================================================================

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from dotenv import load_dotenv
load_dotenv()

import database as db
import tools
from tools import CredentialMissingError
from google import genai
from google.genai import types

app = FastAPI(title="Nexus Agent API Gateway", version="1.0.0")

# CORS: izinkan frontend publik Cloudflare Pages + local dev.
# Nota: allow_credentials=True no se puede combinar con origin "*".
allowed = [
    "https://proyek-agent.pages.dev",
    "http://localhost:3000",
    "http://localhost:3001",
]
env_origin = os.getenv("CORS_ORIGIN", "").strip()
if env_origin:
    allowed.append(env_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# SCHEMA REQUEST
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    prompt: str
    email: str
    session_id: str | None = Field(default=None)


class IntegrationRequest(BaseModel):
    email: str
    provider: str
    token: str


class WorkflowCreateRequest(BaseModel):
    name: str = "Draft Workflow"
    description: str = ""
    flow_data: dict = {}


# ---------------------------------------------------------------------------
# AGENTIC LOOP (setara _agentic_run, bebas dari Streamlit)
# ---------------------------------------------------------------------------
def _agentic_run_direct(prompt: str, email: str) -> str:
    """Jalankan Gemini dengan tool calling; eksekusi alat; loop.

    Apabila alat butuh kredensial, melempar CredentialMissingError (dibiarkan
    menyebar ke caller / endpoint untuk diubah jadi respons needs_credential).
    Errores del modelo (503/quota) se reintentan con backoff; si persisten,
    lanza HTTPException(503) con mensaje claro.
    """
    import time as _time

    api_key = (
        os.getenv("GOOGLE_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GEMINI_KEY_1")
    )
    if not api_key:
        raise HTTPException(500, "API key tidak ditemukan.")

    model_id = os.getenv("AGENT_MODEL", "gemma-4-31b-it")

    SYSTEM = (
        "Anda adalah Nexus Autonomous Agent. Rencanakan & lakukan tindakan dengan "
        "alat yang tersedia. Setelah eksekusi alat, rangkum hasil untuk pengguna "
        "secara ringkas dalam Bahasa Indonesia."
    )

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        temperature=0.1,
        system_instruction=SYSTEM,
        tools=tools.TOOL_DECLARATIONS,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    chat = client.chats.create(model=model_id, config=config)

    def _send_guarded(chat, msg):
        """Enviar con reintentos contra errores transitorios del modelo (500/503)."""
        last_status = None
        for attempt in range(4):
            try:
                return chat.send_message(msg)
            except Exception as exc:  # noqa: BLE001
                msg_str = str(exc)
                transient = ("503" in msg_str or "UNAVAILABLE" in msg_str
                             or "Internal error" in msg_str)
                if not transient:
                    raise
                last_status = "503"
                _time.sleep(1.5 * (attempt + 1))
        raise HTTPException(503, "Modelo temporariamente no disponible. Intente otra vez.")

    response = _send_guarded(chat, prompt)
    max_retries = 3
    retry = 0

    while response.function_calls:
        if retry >= max_retries:
            return "Maaf, agen gagal menyelesaikan operasi setelah beberapa percobaan."

        for call in response.function_calls:
            name = call.name
            args = dict(call.args) if call.args else {}

            # CredentialMissingError dibiarkan menyebar -> endpoint menangkapnya.
            tool_result = tools.execute_tool(name, args, email)

            response = _send_guarded(
                chat,
                types.Part.from_function_response(
                    name=name,
                    response={"status": "success", "result": tool_result},
                ),
            )

    return response.text.strip() if response.text else "Tugas selesai dieksekusi."


# ---------------------------------------------------------------------------
# ENDPOINT 1: POST /chat
# ---------------------------------------------------------------------------
def _derive_title(prompt: str, max_len: int = 30, max_words: int = 5) -> str:
    """Buat judul sesi dinamis dari prompt user.

    Mengambil N kata pertama, potong maksimal `max_len` karakter,
    tambahkan '...' bila lebih panjang.
    """
    words = prompt.strip().split()
    if not words:
        return "Chat"
    taken = " ".join(words[:max_words])
    if len(taken) > max_len:
        return taken[:max_len].rstrip() + "..."
    return taken


@app.post("/chat")
def chat(req: ChatRequest):
    """Proses prompt via Agentic Loop + persist pesan ke session.

    Bila credential hilang -> HTTP 200 {status: needs_credential} (bukan 500).

    Returns:
        status=success     -> {status, reply, session_id}
        status=needs_credential -> {status, provider, message}
    """
    if not req.email:
        raise HTTPException(422, "email wajib diisi.")

    # Pastikan punya session (buat baru bila belum ada)
    session_id = req.session_id
    if not session_id:
        title = _derive_title(req.prompt)
        try:
            session_id = db.create_session(req.email, title)["id"]
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"Gagal membuat session: {exc}")

    # Simpan prompt user ke riwayat
    try:
        db.add_message(req.email, session_id, "user", req.prompt)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal menyimpan pesan: {exc}")

    try:
        reply = _agentic_run_direct(req.prompt, req.email)
    except CredentialMissingError as e:
        # Persist hanya pesan user; UI menampilkan form credential & akan submit ulang.
        return {
            "status": "needs_credential",
            "provider": e.provider_name,
            "message": "Akses dibutuhkan",
            "session_id": session_id,
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Terjadi kesalahan internal: {exc}")

    # Simpan balasan AI
    try:
        db.add_message(req.email, session_id, "assistant", reply)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal menyimpan balasan: {exc}")

    return {"status": "success", "reply": reply, "session_id": session_id}


# ---------------------------------------------------------------------------
# ENDPOINT 2: POST /integrations
# ---------------------------------------------------------------------------
@app.post("/integrations")
def save_integration(req: IntegrationRequest):
    """Simpan token kredensial user (BYOK)."""
    if not req.token or not req.provider:
        raise HTTPException(422, "provider dan token wajib diisi.")
    ok = db.save_integration(req.email, req.provider, req.token)
    if not ok:
        raise HTTPException(500, "Gagal menyimpan kredensial.")
    return {"status": "success", "provider": req.provider}


# ---------------------------------------------------------------------------
# ENDPOINT: POST /workflows  (simpan Visual AI Workflow JSON)
# ---------------------------------------------------------------------------
@app.post("/workflows", status_code=201)
def create_workflow(req: WorkflowCreateRequest):
    """Simpan un workflow de nodos/edges (JSONB a tabla workflows)."""
    try:
        row = db.create_workflow(req.name, req.description, req.flow_data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal menyimpan workflow: {exc}")
    return {"status": "success", "workflow": row}


# ---------------------------------------------------------------------------
# ENDPOINT: GET /workflows  (listar workflows)
# ---------------------------------------------------------------------------
@app.get("/workflows")
def get_workflows():
    try:
        rows = db.list_workflows()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal memuat workflows: {exc}")
    return {"status": "success", "workflows": rows}


# ---------------------------------------------------------------------------
# ENDPOINT 3: GET /sessions  (riwayat obrolan milik user)
# ---------------------------------------------------------------------------
@app.get("/sessions")
def sessions(email: str):
    if not email:
        raise HTTPException(422, "email wajib diisi.")
    try:
        data = db.list_sessions(email)
        return {"status": "success", "sessions": data}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal memuat session: {exc}")


# ---------------------------------------------------------------------------
# ENDPOINT 4: GET /messages/{session_id}  (isi percakapan satu sesi)
# ---------------------------------------------------------------------------
@app.get("/messages/{session_id}")
def messages(session_id: str, email: str):
    if not session_id:
        raise HTTPException(422, "session_id wajib diisi.")
    if not email:
        raise HTTPException(422, "email wajib diisi.")
    try:
        data = db.get_messages(email, session_id)
        return {"status": "success", "messages": data}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal memuat pesan: {exc}")


# ---------------------------------------------------------------------------
# HEALTH CHECK (opsional, berguna utk deployment Cloudflare)
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    return {
        "status": "ok",
        "persistence": db.persistence_info(),
    }


# ---------------------------------------------------------------------------
# ENTRYPOINT directo (dev local): uvicorn api_server:app --reload o python api_server.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run("api_server:app", host=host, port=port, reload=os.getenv("RELOAD") == "1")