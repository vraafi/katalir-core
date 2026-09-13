# api_server.py - API Gateway (FastAPI) pemisah Frontend/Backend
# =====================================================================
# Jembatan antara UI modern (Next.js nanti) dan mesin Python agent.
#
# Endpoint:
#   POST /chat         -> {prompt, session_id?}     (identitas via JWT)
#   POST /integrations -> {provider, token}        (identitas via JWT)
#   POST /api/vault/save -> {provider, api_key}    (identitas via JWT)
#
# Menangkap CredentialMissingError -> HTTP 200 {status:"needs_credential"}.
#
# Jalankan:
#   uvicorn api_server:app --reload
# =====================================================================

import os

# ---------------------------------------------------------------------------
# MODEL REGISTRY (Tugas 2 / hermes-agent #5880): tier-gate per model.
# Mirror frontend nexus-frontend/src/lib/models.ts. 'free' = semua user,
# 'plus' = hanya user tier plus/pro. Tier user dari public.users.tier.
# ---------------------------------------------------------------------------
# Daftar model free yang memang diizinkan dipilih (hanya ini yang di-serve
# oleh Gemini/Google keys). Model plus di-reject bila tier user = free.
FREE_CHAT_MODELS = frozenset({
    "gemma-4-31b-it",
    "gemini-2.5-flash",
    "gemma-4-9b-it",
})
PLUS_CHAT_MODELS = frozenset({
    "gemini-1.5-pro",
})
ALLOWED_CHAT_MODELS = FREE_CHAT_MODELS | PLUS_CHAT_MODELS
PLUS_TIERS = frozenset({"plus", "pro", "ultra"})


def _resolve_model(requested: str | None, user_tier: str) -> tuple[str, bool]:
    """Validasi model pilihan user + tier-gate.

    Returns:
        (model_id, tier_fallback): tier_fallback=True bila model plus
        diminta user free -> jatuh ke default server (bukan 403, agar UX
        composer tidak putus; badge fallback/transparansi di meta).
    """
    default_id = os.getenv("AGENT_MODEL", "gemma-4-31b-it")
    tier = (user_tier or "free").strip().lower()
    if not requested:
        return default_id, False
    req = requested.strip()
    if req in FREE_CHAT_MODELS:
        return req, False
    if req in PLUS_CHAT_MODELS:
        if tier in PLUS_TIERS:
            return req, False
        return default_id, True  # free user minta plus -> fallback default
    return default_id, False  # unknown id -> abaikan, pakai default

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Any

from dotenv import load_dotenv
load_dotenv()

import database as db
import security
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
    session_id: str | None = Field(default=None)
    # Idempotensi (openclaw #69266): UUID per kiriman logis dari frontend. Bila
    # POST /chat tiba 2x untuk pesan yang sama (retry setelah server-commit),
    # backend mengenali & tidak meng-insert user-message dua kali.
    client_request_id: str | None = Field(default=None)
    # Model yang dipilih user dari composer (ModelSelector). Bila None, pakai
    # AGENT_MODEL (default server). Hanya model yang ada di ALLOWED_MODELS.
    model: str | None = Field(default=None)


class IntegrationRequest(BaseModel):
    provider: str
    token: str


class VaultSaveRequest(BaseModel):
    provider: str
    api_key: str


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
def _agentic_run_direct(prompt: str, email: str, model: str | None = None, user_tier: str = "free") -> dict:
    """Jalankan Gemini dengan tool calling; eksekusi alat; loop.

    Apabila alat butuh kredensial, melempar CredentialMissingError (dibiarkan
    menyebar ke caller / endpoint untuk diubah jadi respons needs_credential).
    Errores del modelo (503/quota) se reintentan con backoff; si persisten,
    lanza HTTPException(503) con mensaje claro.

    Returns:
        dict {reply, meta} dengan meta = {model, latency_ms,
        prompt_tokens, completion_tokens, total_tokens, fallback}.
    """
    import time as _time

    api_key = (
        os.getenv("GOOGLE_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GEMINI_KEY_1")
    )
    if not api_key:
        raise HTTPException(500, "API key tidak ditemukan.")

    model_id, tier_fallback = _resolve_model(model, user_tier)
    fallback_used = bool(tier_fallback)

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

    fallback_model = os.getenv("AGENT_FALLBACK_MODEL", "gemini-2.5-flash")

    def _send_guarded(chat_obj, msg):
        """Enviar con reintentos contra errores transitorios del modelo (500/503)."""
        nonlocal model_id, fallback_used, chat
        for attempt in range(4):
            try:
                return chat_obj.send_message(msg)
            except Exception as exc:  # noqa: BLE001
                msg_str = str(exc)
                transient = ("503" in msg_str or "UNAVAILABLE" in msg_str
                             or "Internal error" in msg_str
                             or "overloaded" in msg_str.lower()
                             or "quota" in msg_str.lower())
                if not transient:
                    raise
                # Fallback 1x ke model ringan bila model utama overload/quota.
                if not fallback_used and fallback_model and fallback_model != model_id:
                    try:
                        chat2 = client.chats.create(model=fallback_model, config=config)
                        out = chat2.send_message(msg)
                        fallback_used = True
                        model_id = fallback_model
                        chat = chat2
                        return out
                    except Exception:
                        pass
                _time.sleep(1.5 * (attempt + 1))
        raise HTTPException(503, "Model sedang sibuk (quota/overload). Coba lagi dalam 1 menit.")

    _t0 = _time.time()
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

    reply = response.text.strip() if response.text else "Tugas selesai dieksekusi."
    latency_ms = int((_time.time() - _t0) * 1000)
    usage = getattr(response, "usage_metadata", None)
    try:
        pt = usage.prompt_token_count if usage is not None else 0
        ct = usage.candidates_token_count if usage is not None else 0
        tt = usage.total_token_count if usage is not None else 0
    except Exception:
        pt, ct, tt = 0, 0, 0
    meta = {
        "model": model_id,
        "latency_ms": latency_ms,
        "prompt_tokens": int(pt or 0),
        "completion_tokens": int(ct or 0),
        "total_tokens": int(tt or 0),
        "fallback": bool(fallback_used),
    }
    return {"reply": reply, "meta": meta}


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
def chat(req: ChatRequest, authorization: str | None = Header(None)):
    """Proses prompt via Agentic Loop + persist pesan ke session.

    KEAMANAN: user dari JWT (Authorization Bearer), BUKAN dari body email.
    Bila credential hilang -> HTTP 200 {status: needs_credential} (bukan 500).

    Returns:
        status=success     -> {status, reply, session_id}
        status=needs_credential -> {status, provider, message}
    """
    user = security.get_current_user(authorization)
    user_email = user["email"]
    user_id = user["id"]
    req_id = req.client_request_id
    # Tier user untuk tier-gate model (hermes-agent #5880): free -> model plus
    # di-fallback ke default (bukan 403). Resolve via get_or_create_user
    # (row users dibuat bila belum ada — sama seperti session flow).
    try:
        _u = db.get_or_create_user(user_email, "", auth_id=user_id)
        user_tier = str((_u or {}).get("tier", "free") or "free")
    except Exception:
        user_tier = "free"

    # Idempotensi (openclaw #69266): kalau kiriman logis ini sudah pernah diproses
    # (mis. respons hilang saat timeout, lalu frontend retry), JANGAN double-insert.
    # - Prior + reply sudah ada  -> kembalikan reply tersimpan, tanpa jalankan ulang.
    # - Prior + reply belum ada   -> lanjutkan sesi tsb & selesaikan reply.
    prior_session = None
    if req_id:
        prior = db.find_user_message_by_request(req_id)
        if prior and prior.get("session_id"):
            prev_reply = db.get_last_assistant_reply(prior["session_id"])
            if prev_reply:
                return {
                    "status": "success",
                    "reply": prev_reply,
                    "session_id": prior["session_id"],
                }
            prior_session = prior["session_id"]

    # Pastikan punya session (buat baru bila belum ada).
    # prior_session dipakai saat retry-yang-tanpa-session (tak buat sesi baru 2x).
    session_id = req.session_id or prior_session
    if not session_id:
        title = _derive_title(req.prompt)
        try:
            session_id = db.create_session(user_id, title, auth_id=user_id, email=user_email)["id"]
        except HTTPException:
            raise  # status terpetakan dari database (503 RLS / 409 FK) — jangan dibungkus ulang jadi 500
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()  # full stack ke Railway log
            raise HTTPException(500, f"Gagal membuat session: {type(exc).__name__}: {exc}")

    # Simpan prompt user ke riwayat (kepemilikan session divalidasi via auth_id).
    # Idempoten: bila client_request_id sudah tercatat, add_message return False
    # dan TIDAK meng-insert — mencegah pesan user duplikat dalam 1 sesi.
    try:
        db.add_message(user_email, session_id, "user", req.prompt, auth_id=user_id, client_request_id=req_id)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Gagal menyimpan pesan: {type(exc).__name__}: {exc}")

    try:
        _run = _agentic_run_direct(req.prompt, user_email, model=req.model, user_tier=user_tier)
        reply = _run["reply"]
        meta = _run.get("meta") or {}
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
        import traceback
        traceback.print_exc()  # full stack ke Railway log (Fase 2b)
        raise HTTPException(500, f"Terjadi kesalahan internal: {type(exc).__name__}: {exc}")

    # Simpan balasan AI
    try:
        db.add_message(user_email, session_id, "assistant", reply, auth_id=user_id, client_request_id=req_id)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Gagal menyimpan balasan: {type(exc).__name__}: {exc}")

    return {"status": "success", "reply": reply, "session_id": session_id, "meta": meta}


# ---------------------------------------------------------------------------
# ENDPOINT: GET /me  (profil user: email + tier) — untuk tier-gate ModelSelector.
# ---------------------------------------------------------------------------
@app.get("/me")
def me(authorization: str | None = Header(None)):
    """Kembalikan {email, tier} user JWT (tier dari public.users, default free)."""
    user = security.get_current_user(authorization)
    try:
        _u = db.get_or_create_user(user["email"], "", auth_id=user["id"])
        tier = str((_u or {}).get("tier", "free") or "free").strip().lower()
    except Exception:
        tier = "free"
    return {"status": "success", "email": user["email"], "tier": tier}


# ---------------------------------------------------------------------------
# ENDPOINT 1b: GET /models  (daftar model + flag locked per tier user)
# ---------------------------------------------------------------------------
@app.get("/models")
def list_models(authorization: str | None = Header(None)):
    """Daftar model chat dengan flag `locked` sesuai tier user (hermes #5880).

    locked=False -> bisa dipilih. locked=True -> tampil redup + Upgrade link.
    """
    user = security.get_current_user(authorization)
    try:
        _u = db.get_or_create_user(user["email"], "", auth_id=user["id"])
        tier = str((_u or {}).get("tier", "free") or "free").strip().lower()
    except Exception:
        tier = "free"
    is_plus = tier in PLUS_TIERS
    default_id = os.getenv("AGENT_MODEL", "gemma-4-31b-it")
    items = [
        {"id": "gemma-4-31b-it", "name": "Gemma 4 31B", "provider": "Google (Gemini)", "tier": "free", "locked": False},
        {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "provider": "Google (Gemini)", "tier": "free", "locked": False, "hint": "Cepat, hemat token"},
        {"id": "gemma-4-9b-it", "name": "Gemma 4 9B", "provider": "Google (Gemini)", "tier": "free", "locked": False, "hint": "Ringan & hemat"},
        {"id": "gemini-1.5-pro", "name": "Gemini Advanced", "provider": "Google (Gemini)", "tier": "plus", "locked": not is_plus},
    ]
    return {"status": "success", "tier": tier, "default": default_id, "models": items}


# ---------------------------------------------------------------------------
# ENDPOINT 2: POST /integrations
# ---------------------------------------------------------------------------
@app.post("/integrations")
def save_integration(req: IntegrationRequest, authorization: str | None = Header(None)):
    """Simpan token kredensial user (BYOK)."""
    if not req.token or not req.provider:
        raise HTTPException(422, "provider dan token wajib diisi.")
    user = security.get_current_user(authorization)
    ok = db.save_integration(user["email"], req.provider, req.token)
    if not ok:
        raise HTTPException(500, "Gagal menyimpan kredensial.")
    return {"status": "success", "provider": req.provider}


# ---------------------------------------------------------------------------
# ENDPOINT: POST /api/vault/save   (Brankas: enkripsi + upsert user_vault)
#   KEAMANAN: user TARGET dari JWT (Authorization Bearer), BUKAN dari body.
# ---------------------------------------------------------------------------
@app.post("/api/vault/save")
def vault_save_endpoint(req: VaultSaveRequest, authorization: str | None = Header(None)):
    """Enkriptoi API key (Fernet) ja simpan user_vault (ei plaintext koskaan)."""
    if not req.provider or not req.api_key:
        raise HTTPException(422, "provider, api_key wajib diisi.")
    user = security.get_current_user(authorization)
    email = user["email"]  # dari JWT verified, bukan param/body
    import vault_security as vs
    cipher = vs.encrypt_key(req.api_key)     # palauta ciphertext str
    ok = db.vault_save(email, req.provider.strip(), cipher)
    if not ok:
        raise HTTPException(500, "Gagal menyimpan vault.")
    return {"status": "saved", "provider": req.provider, "saved": True}


# ---------------------------------------------------------------------------
# ENDPOINT: GET /api/vault/list   (daftar provider, EI koskaan palauta avainta)
#   KEAMANAN: user dari JWT, query param email TIDAK lebih.
# ---------------------------------------------------------------------------
@app.get("/api/vault/list")
def vault_list_endpoint(authorization: str | None = Header(None)):
    user = security.get_current_user(authorization)
    email = user["email"]
    items = db.vault_list(email)
    return {"status": "success", "items": items}


# ---------------------------------------------------------------------------
# ENDPOINT: POST /workflows  (simpan Visual AI Workflow JSON)
#   KEAMANAN: user_id dari JWT (Authorization Bearer), BUKAN dari body.
# ---------------------------------------------------------------------------
@app.post("/workflows", status_code=201)
def create_workflow(req: WorkflowCreateRequest, authorization: str | None = Header(None)):
    """Simpan un workflow de nodos/edges (JSONB a tabla workflows)."""
    user = security.get_current_user(authorization)
    try:
        row = db.create_workflow(user["id"], req.name, req.description, req.flow_data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal menyimpan workflow: {exc}")
    return {"status": "success", "workflow": row}


# ---------------------------------------------------------------------------
# ENDPOINT: GET /workflows  (listar workflows) — SOLO milik user JWT
# ---------------------------------------------------------------------------
@app.get("/workflows")
def get_workflows(authorization: str | None = Header(None)):
    user = security.get_current_user(authorization)
    try:
        rows = db.list_workflows(user["id"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal memuat workflows: {exc}")
    return {"status": "success", "workflows": rows}


# ---------------------------------------------------------------------------
# ENDPOINTS: POST /workflows/{id}/execute + GET /executions/{id}
#   Execution Engine — instan, non-blocking, devuelve {execution_id, status: pending}
# ---------------------------------------------------------------------------
@app.post("/workflows/{workflow_id}/execute", status_code=202)
async def execute_workflow(workflow_id: str, req: ExecuteRequest = None,
                           authorization: str | None = Header(None)):  # type: ignore[assignment]
    """Inicia la ejecucion de un workflow en background (status pending)."""
    user = security.get_current_user(authorization)
    owner = db.get_workflow_owner(workflow_id)
    if owner is None or owner != user["id"]:
        raise HTTPException(404, "Workflow tidak ditemukan.")
    flow_data = req.flow_data if (req and req.flow_data) else None
    if not flow_data:
        found = next((w for w in (db.list_workflows(user["id"]) or []) if w.get("id") == workflow_id), None)
        if not found:
            raise HTTPException(404, f"Workflow {workflow_id} tidak ditemukan.")
        flow_data = found.get("flow_data") or {}
    try:
        execution_id = engine.launch_execution(workflow_id, flow_data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal melanjar ejekution: {exc}")
    return {"execution_id": execution_id, "workflow_id": workflow_id, "status": "pending"}


@app.get("/executions/{execution_id}")
def get_execution(execution_id: str, authorization: str | None = Header(None)):
    """Devuelve estado y logs de una ejecucion."""
    user = security.get_current_user(authorization)
    try:
        data = db.get_execution(execution_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal memuat ejekution: {exc}")
    # Keamanan: verificar que la ejecucion pertenezca a un workflow del user
    ex = (data or {}).get("execution") or {}
    wid = ex.get("workflow_id")
    if wid:
        owner = db.get_workflow_owner(str(wid))
        if owner != user["id"]:
            raise HTTPException(404, "Ejecucion tidak ditemukan.")
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
                          background: BackgroundTasks,
                          authorization: str | None = Header(None)) -> dict:
    """Terima webhook eksternal dan antrekan eksekusi DAG di background.

    Gembok eksekusi: 400 jika workflow tidak punya node Trigger yang valid.
    Keamanan: ownership workflow via JWT (Authorization Bearer).
    Mengembalikan 202 Accepted + execution_id dengan cepat (non-blocking).
    """
    user = security.get_current_user(authorization)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - body kosong/bukan JSON tetap diterima
        body = {}
    headers: dict[str, str] = {k.lower(): v for k, v in request.headers.items()}
    trigger_input: dict = {
        "headers": headers,
        "body": body if isinstance(body, dict) else {"value": body},
    }

    owner = db.get_workflow_owner(workflow_id)
    if owner is None or owner != user["id"]:
        raise HTTPException(404, "Workflow tidak ditemukan.")
    found = next(
        (w for w in (db.list_workflows(user["id"]) or []) if w.get("id") == workflow_id),
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
# ENDPOINT 3: GET /sessions  (riwayat obrolan milik user JWT)
# ---------------------------------------------------------------------------
@app.get("/sessions")
def sessions(authorization: str | None = Header(None)):
    user = security.get_current_user(authorization)
    try:
        # FIX regresi: resolve identitas via EMAIL (bukan JWT sub). Alasan:
        # chat_sessions.user_id diisi public.users.id (kanonis via
        # get_or_create_user(email)), yang bisa BERBEDA dari auth.users.id
        # (JWT sub). _resolve_user_id(email) memakai id kanonis yang SAMA
        # dengan create_session/add_message -> login + insert + lookup converge.
        data = db.list_sessions(user["email"])
        return {"status": "success", "sessions": data}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal memuat session: {exc}")


# ---------------------------------------------------------------------------
# ENDPOINT 4: GET /messages/{session_id}  (isi percakapan satu sesi)
# ---------------------------------------------------------------------------
@app.get("/messages/{session_id}")
def messages(session_id: str, authorization: str | None = Header(None)):
    if not session_id:
        raise HTTPException(422, "session_id wajib diisi.")
    user = security.get_current_user(authorization)
    try:
        # FIX regresi: resolve via EMAIL (liat /sessions) supaya id kanonis
        # (public.users.id) dipakai, SAMA dengan yang menginsert session.
        data = db.get_messages(user["email"], session_id)
        return {"status": "success", "messages": data}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal memuat pesan: {exc}")


# ---------------------------------------------------------------------------
# ENDPOINT 4b: DELETE /sessions/{session_id}  (hapus riwayat milik user)
# ---------------------------------------------------------------------------
@app.delete("/sessions/{session_id}")
def delete_session(session_id: str, authorization: str | None = Header(None)):
    if not session_id:
        raise HTTPException(422, "session_id wajib diisi.")
    user = security.get_current_user(authorization)
    try:
        ok = db.delete_session(user["email"], session_id)
        if not ok:
            raise HTTPException(404, "Session tidak ditemukan.")
        return {"status": "success", "deleted": True}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal menghapus session: {exc}")


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
async def dodo_webhook(request: Request):
    """Dodo Payments webhook -> topup saldo.

    KEAMANAN: Standard Webhooks signature (webhook-id + webhook-timestamp +
    webhook-signature headers) geverifieerd via dodopayments SDK unwrap().
    Zonder geldige signature -> 401 (anti-spoof).
    """
    import dodo_verify as dv
    raw = await request.body()
    headers = {
        "webhook-id": request.headers.get("webhook-id", ""),
        "webhook-timestamp": request.headers.get("webhook-timestamp", ""),
        "webhook-signature": request.headers.get("webhook-signature", ""),
    }
    if not dv.verify_dodo_webhook(raw, headers):
        raise HTTPException(401, "Webhook signature invalid (anti-spoof).")
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "Body moet JSON zijn.")
    data = (payload or {}).get("data") or {}
    # email/credits: ondersteunt zowel top-level als genest in data
    email = (payload or {}).get("email") or (payload or {}).get("customer_email") \
        or data.get("email") or data.get("customer_email")
    if not email:
        raise HTTPException(422, "email wajib diisi.")
    topup = (payload or {}).get("credits") or (payload or {}).get("amount") \
        or data.get("credits") or data.get("amount") or 0
    if topup <= 0:
        raise HTTPException(422, "nominal topup harus > 0.")
    try:
        db.topup_balance(email, float(topup))
        return {"status": "success", "email": email, "credited": float(topup),
                "event": (payload or {}).get("type") or (payload or {}).get("event", "payment.succeeded")}
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