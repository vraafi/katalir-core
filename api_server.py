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

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from dotenv import load_dotenv
load_dotenv()

import database as db
import tools
import execution_engine as engine
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


class ExecuteRequest(BaseModel):
    # Body opcional; si va vacio, se usa el flow_data guardado del workflow.
    flow_data: dict | None = None


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
# ENDPOINTS: POST /workflows/{id}/execute + GET /executions/{id}
#   Execution Engine — instan, non-blocking, devuelve {execution_id, status: pending}
# ---------------------------------------------------------------------------
@app.post("/workflows/{workflow_id}/execute", status_code=202)
async def execute_workflow(workflow_id: str, req: ExecuteRequest = None):  # type: ignore[assignment]
    """Inicia la ejecucion de un workflow en background (status pending)."""
    flow_data = req.flow_data if (req and req.flow_data) else None
    if not flow_data:
        found = next((w for w in (db.list_workflows() or []) if w.get("id") == workflow_id), None)
        if not found:
            raise HTTPException(404, f"Workflow {workflow_id} tidak ditemukan.")
        flow_data = found.get("flow_data") or {}
    try:
        execution_id = engine.launch_execution(workflow_id, flow_data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal melanjar ejekution: {exc}")
    return {"execution_id": execution_id, "workflow_id": workflow_id, "status": "pending"}


@app.get("/executions/{execution_id}")
def get_execution(execution_id: str):
    """Devuelve estado y logs de una ejecucion."""
    try:
        data = db.get_execution(execution_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal memuat ejekution: {exc}")
    return {"status": "success", **data}


# ---------------------------------------------------------------------------
# REAL WEBHOOK TRIGGER - POST /webhook/{workflow_id}
#   Otomatisasi dunia nyata: payload JSON bebas dari Telegram/WhatsApp/
#   sistem eksternal -> input_data node Trigger -> DAG async non-blocking.
# ---------------------------------------------------------------------------
async def _run_webhook_dag(workflow_id: str, flow_data: dict,
                           trigger_input: dict) -> None:
    """Runner DAG untuk BackgroundTasks (tanpa create_task mentah).

    Menjalankan Trigger -> Agent -> MCP dan mempersist setiap langkah ke
    execution_logs. Error dicatat ke status eksekusi, bukan crash worker.
    """
    import uuid as _uuid

    execution_id = trigger_input.get("_execution_id") or str(_uuid.uuid4())
    try:
        await engine.execute_workflow_async(
            workflow_id, flow_data, trigger_input)
        db.update_execution_status(str(execution_id), "completed")
    except Exception as exc:  # noqa: BLE001
        try:
            db.update_execution_status(str(execution_id), "error")
        except Exception:  # noqa: BLE001
            pass
        print(f"[webhook] eksekusi {execution_id} gagal: {exc}")


# ---------------------------------------------------------------------------
# REAL WEBHOOK TRIGGER - POST /webhook/{workflow_id} (BackgroundTasks)
#   Standar industri 2026: tanpa raw asyncio.create_task (rawan dropped
#   tasks saat worker restart). Tangkap body + headers, injeksi ke Trigger.
# ---------------------------------------------------------------------------
@app.post("/webhook/{workflow_id}", status_code=202)
async def webhook_trigger(workflow_id: str, request: Request,
                          background: BackgroundTasks) -> dict:
    """Terima webhook eksternal dan antrekan eksekusi DAG di background.

    Gembok eksekusi: 400 jika workflow tidak punya node Trigger yang valid.
    Mengembalikan 202 Accepted + execution_id dengan cepat (non-blocking).
    """
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - body kosong/bukan JSON tetap diterima
        body = {}
    headers: dict[str, str] = {k.lower(): v for k, v in request.headers.items()}
    trigger_input: dict = {
        "headers": headers,
        "body": body if isinstance(body, dict) else {"value": body},
    }

    found = next(
        (w for w in (db.list_workflows() or []) if w.get("id") == workflow_id),
        None,
    )
    if not found:
        raise HTTPException(404, f"Workflow {workflow_id} tidak ditemukan.")
    flow_data = found.get("flow_data") or {}

    nodes = flow_data.get("nodes") or []
    has_trigger = any(
        ((n.get("data") or {}).get("kind") == "trigger")
        or (n.get("type") in ("trigger", "triggerNode"))
        for n in nodes
    )
    if not has_trigger:
        raise HTTPException(
            400, "Workflow tidak memiliki trigger yang valid.")

    import uuid as _uuid
    execution_id = str(_uuid.uuid4())
    trigger_input["_execution_id"] = execution_id
    try:
        db.create_execution(execution_id, workflow_id, flow_data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal membuat eksekusi: {exc}")
    background.add_task(_run_webhook_dag, workflow_id, flow_data,
                        trigger_input)
    return {"status": "queued", "execution_id": execution_id,
            "workflow_id": workflow_id}


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
# ENDPOINT 5: POST /api/payments/dodo-webhook  (Dodo Payments -> topup saldo)
# ---------------------------------------------------------------------------
class DodoWebhookPayload(BaseModel):
    email: Optional[str] = None
    customer_email: Optional[str] = None
    amount: Optional[float] = 0
    credits: Optional[float] = 0
    event: Optional[str] = "payment.succeeded"
    payment_id: Optional[str] = None


@app.post("/api/payments/dodo-webhook")
def dodo_webhook(payload: DodoWebhookPayload):
    email = payload.email or payload.customer_email
    if not email:
        raise HTTPException(422, "email wajib diisi.")
    topup = payload.credits or payload.amount or 0
    if topup <= 0:
        raise HTTPException(422, "nominal topup harus > 0.")
    try:
        db.topup_balance(email, float(topup))
        return {"status": "success", "email": email, "credited": float(topup),
                "payment_id": payload.payment_id, "event": payload.event}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal memproses webhook: {exc}")


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