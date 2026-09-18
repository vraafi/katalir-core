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
import json
import threading
import time
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Any

from dotenv import load_dotenv
load_dotenv()

import database as db
import gemini_key_pool
import model_discovery as md
import security
import tools
import execution_engine as engine
from tools import CredentialMissingError
from google import genai
from google.genai import types

@asynccontextmanager
async def _lifespan(_app: "FastAPI"):
    """Hook startup/shutdown (pengganti @app.on_event yang sudah deprecated).

    Warm-up roster gateway dijalankan di sini supaya deploy BARU (tanpa
    `.gw_roster_cache.json` seed) tidak menunggu probe sinkron di request
    /chat pertama. `_warm_gateway_roster` didefinisikan di bawah (name lookup
    terjadi saat runtime, bukan saat import) dan langsung return — probe
    sesungguhnya berjalan di thread daemon.

    Warm-up JWKS juga dijalankan di sini (alasan yang sama, dan lebih kritis):
    verifikasi token bergantung pada public key. Kalau unduhan JWKS terjadi
    lazily di request pertama lalu timeout, SELURUH endpoint ber-JWT menjawab
    401 `Token invalid: ConnectTimeout` — walau token browser sah.
    """
    security.warm_jwks()
    _warm_gateway_roster()
    yield


app = FastAPI(title="Nexus Agent API Gateway", version="1.0.0",
              lifespan=_lifespan)

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


# MODEL SELECTION: discovery dinamis via model_discovery (runtime query,
# bukan hardcode — Google ubah/tambah/hapus model tiap kuartal).
# 'plus' = kebijakan bisnis (hermes #5880), tetap eksplisit per model.
# Didefinisikan SETELAH import md (NameError `md` = crash 502 saat startup).
PLUS_CHAT_MODELS = md.PLUS_CHAT_MODELS
PLUS_TIERS = frozenset({"plus", "pro", "ultra"})


# ---------------------------------------------------------------------------
# FREE-LLM-GATEWAY (self-hosted di VPS) — SATU PINTU trafik LLM
# ---------------------------------------------------------------------------
def _gateway_target() -> tuple[str, str, list[str]] | None:
    """(base_url, master_key, roster) bila gateway aktif; None bila tidak.

    Roster berasal dari probe EMPIRIS (gateway_roster) dan disajikan dari cache
    sehingga helper ini tidak menahan request /chat (probe hanya di latar).
    """
    try:
        import gateway_roster as gr

        url, key = gr.gateway_config()
        if not url or not key:
            return None
        return url, key, gr.gw_models()
    except Exception as exc:  # noqa: BLE001 - gateway opsional
        print(f"[api_server] roster gateway dilewati: {exc}")
        return None


def _warm_gateway_roster() -> None:
    """Isi cache roster saat startup TANPA menahan startup (thread daemon).

    Deploy baru tidak punya `.gw_roster_cache.json`: tanpa warm-up, request
    /chat pertama jatuh ke probe sinkron `probe_roster()` (satu request HTTP
    per kandidat, timeout `LLM_GATEWAY_PROBE_TIMEOUT`) sehingga balasan
    pertama frontend menggantung. Di sini probe dijalankan di latar, jadi
    startup tetap instan dan request pertama menyusul setelah probe selesai.
    """
    try:
        import gateway_roster as gr

        if not gr.gateway_config()[0]:
            return  # gateway belum dikonfigurasi -> tidak ada yang dihangatkan
        # HANYA lihat cache: `probe_roster()` TANPA cache melakukan probe
        # sinkron (puluhan detik) sehingga justru menahan startup. Cache segar
        # -> tidak ada kerja; cache kosong/kedaluwarsa -> probe di latar.
        if gr.cached_roster(gr.CACHE_TTL_S):
            return
        threading.Thread(
            target=gr.probe_roster,
            kwargs={"force": True, "blocking": True},
            name="gw-roster-warmup",
            daemon=True,
        ).start()
        print("[api_server] warm-up roster gateway di latar belakang.")
    except Exception as exc:  # noqa: BLE001 - gateway opsional
        print(f"[api_server] warm-up roster dilewati: {exc}")


def _default_model_id() -> str:
    """Default server: model roster gateway bila gateway aktif.

    Tanpa ini default legacy `gemma-4-31b-it` (id Gemini-only, tak ada di
    roster) diarahkan ke gateway -> 404; sebaliknya id gateway
    (`qwen/qwen3.8-27b`) tidak dikenal genai.Client.
    """
    gw = _gateway_target()
    if gw and gw[2]:
        env_default = (os.getenv("AGENT_MODEL") or "").strip()
        if env_default and env_default in gw[2]:
            return env_default
        return gw[2][0]
    return os.getenv("AGENT_MODEL", "gemma-4-31b-it")


def _fallback_reason(err: object) -> str:
    """Klasifikasi alasan fallback -> kode yang dipetakan frontend ke bahasa user.

    Kode: `quota_exhausted` | `rate_limit` | `overloaded` | `model_unavailable`;
    `gateway_down` dipakai pemanggil (bukan fungsi ini) saat gateway gagal total.
    Sengaja teks-based (bukan type-based) karena error datang dari tiga lapis
    berbeda: SDK genai, LangChain/OpenAI client, dan HTTPException gateway.

    CATATAN: `quota` dicek SEBELUM `rate_limit` — pesan 429 Gemini sering
    memuat keduanya ("quota exceeded ... rate limit"), dan penyebab yang
    berguna bagi user adalah kuota harian habis, bukan rate sesaat.
    """
    text = str(getattr(err, "detail", "") or err or "").lower()
    if not text:
        return "model_unavailable"
    if ("quota" in text or "resource_exhausted" in text
            or "insufficient_quota" in text or "rpd" in text or "402" in text):
        return "quota_exhausted"
    if "429" in text or ("rate" in text and "limit" in text) or "too many" in text:
        return "rate_limit"
    if ("503" in text or "unavailable" in text or "overload" in text
            # "server error"/"servererror" = spasi & nama kelas "InternalServerError"
            # saat kandidat hulu menolak payload (terbukti: groq/compound +
            # bind_tools -> 500, sedangkan tanpa tools -> 200). Tanpa token ini
            # teks itu tak memuat "internal error" (terpisah kata "server")
            # maupun digit "500", sehingga jatuh ke default model_unavailable
            # -> frontend menuduh "tidak tersedia untuk tier Anda" padahal 500.
            or "sibuk" in text or "internal error" in text or "500" in text or "server error" in text or "servererror" in text):
        return "overloaded"
    if ("401" in text or "unauthenticated" in text or "unauthorized" in text
            or "invalid authentication credentials" in text
            or "tidak valid" in text):
        # Kunci cadangan ditolak hulu (401). Dari sudut user ini gangguan
        # layanan yang sementara -- BUKAN "model tidak tersedia untuk tier
        # Anda" (pesan itu dulu muncul karena 401 jatuh ke default).
        return "overloaded"
    if ("404" in text or "410" in text or "not found" in text or "gone" in text
            or "tidak dikenal" in text):
        return "model_unavailable"
    # Sisa: gateway tak terhubung / id tak tersaji (mis. model paid-only yang
    # baru difilter) -> dari sudut pandang user, model yang diminta tak tersedia.
    return "model_unavailable"


def _tools_unsupported(exc: Exception) -> bool:
    """True bila kegagalan konsisten dengan hulu yang MENOLAK payload ber-tools.

    Bukti empiris (2026-09-17, gateway free-llm-gateway): `groq/compound` dan
    `openai/gpt-oss-20b` menjawab 200 TANPA `tools`, tetapi 500 polos
    ("Internal Server Error") BILA `tools` disertakan. Dipakai untuk memicu
    SATU retry tanpa tools — bukan pengulangan tak terbatas.
    """
    text = f"{type(exc).__name__}: {exc}".lower()
    if not text.strip():
        return False
    # Kuota/rate/auth BUKAN masalah bentuk payload -> tools jangan dibuang.
    if any(tok in text for tok in ("quota", "rate limit", "too many", "429",
                                   "401", "403", "api key", "unauthorized")):
        return False
    return ("internal server error" in text or "servererror" in text
            or "server error" in text or "500" in text)


def _resolve_model(requested: str | None, user_tier: str) -> tuple[str, bool, str | None]:
    """Validasi model + tier-gate terhadap hasil discovery (cache 1 jam).

    Returns:
        (model_id, fallback, reason). `fallback=True` bila model yang dipakai
        BEDA dari yang diminta user, dengan `reason` kode alasan (lihat
        `_fallback_reason`). Tiga penyebab fallback di sini:
          - model plus diminta user free      -> `model_unavailable` (tier);
          - id tak ada di daftar discovery    -> `model_unavailable`
            (termasuk id paid-only yang baru difilter TUGAS 1, dan pilihan
            lama di localStorage yang sudah tidak disajikan lagi).
    """
    default_id = _default_model_id()
    tier = (user_tier or "free").strip().lower()
    if not requested:
        return default_id, False, None
    req = requested.strip()
    available = {m["id"] for m in md.get_available_models()}
    if req not in available:
        # Sebelumnya ini mengembalikan fallback=False -> user diam-diam
        # mendapat model lain TANPA badge. Itu persis keluhan "reply dari
        # gemini-2.5-flash" saat memilih Pro. Sekarang ditandai jujur.
        return default_id, True, "model_unavailable"
    if req in PLUS_CHAT_MODELS:
        if tier in PLUS_TIERS:
            return req, False, None
        return default_id, True, "model_unavailable"  # free minta plus
    return req, False, None


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
# AGENTIC LOOP VIA GATEWAY (OpenAI-compatible /v1)
# ---------------------------------------------------------------------------
_AGENT_SYSTEM = (
    "Anda adalah Nexus Autonomous Agent. Rencanakan & lakukan tindakan dengan "
    "alat yang tersedia. Setelah eksekusi alat, rangkum hasil untuk pengguna "
    "secara ringkas dalam Bahasa Indonesia."
)


def _content_text(resp: Any) -> str:
    """Teks balasan dari respons LangChain (str, atau list blok thinking/text)."""
    raw = getattr(resp, "content", resp)
    if isinstance(raw, list):
        parts: list[str] = []
        for block in raw:
            if isinstance(block, dict) and block.get("text"):
                parts.append(str(block["text"]))
            elif isinstance(block, str):
                parts.append(block)
        raw = "\n".join(parts)
    text = str(raw or "").strip()
    return text or "Tugas selesai dieksekusi."


# ---------------------------------------------------------------------------
# KONTEKS MULTI-TURN: riwayat percakapan dari DB -> pesan untuk model
# ---------------------------------------------------------------------------
# MASALAH YANG DIPERBAIKI: prompt_tokens turn-1 vs turn-2 hanya naik +1
# (547 -> 548) dan model menjawab "Anda belum meminta saya mengingat apa pun"
# padahal riwayatnya TERSIMPAN rapi di Supabase. Penyebabnya bukan database,
# melainkan `/chat` memanggil `_agentic_run_direct(req.prompt, ...)` sehingga
# daftar pesan ke model HANYA [system, prompt-terakhir] — riwayat tidak pernah
# dikirim sebagai konteks. Akibatnya agen amnesia di setiap turn lanjutan.
def _history_limit() -> int:
    """Banyaknya pesan riwayat yang dikirim sebagai konteks (default 20).

    Dibatasi agar prompt tidak membengkak (biaya + latensi) pada percakapan
    panjang. 0 = matikan konteks (berguna untuk membandingkan perilaku).
    """
    try:
        return max(0, int(os.getenv("AGENT_HISTORY_MESSAGES", "20")))
    except (TypeError, ValueError):
        return 20


def _history_char_cap() -> int:
    """Batas karakter per pesan riwayat (default 4000).

    Balasan agen bisa sangat panjang; memotongnya mencegah satu pesan lama
    menghabiskan jendela konteks. Dipotong dari depan-potongan teks tetap
    menyimpan bagian pembuka yang biasanya memuat inti jawaban.
    """
    try:
        return max(200, int(os.getenv("AGENT_HISTORY_CHARS", "4000")))
    except (TypeError, ValueError):
        return 4000


def load_history(user_email: str, session_id: str | None,
                 current_prompt: str | None = None) -> list[dict]:
    """Riwayat percakapan sesi (urut lama -> baru) untuk konteks LLM.

    Args:
        user_email: pemilik sesi (kepemilikan divalidasi di `db.get_messages`).
        session_id: sesi yang sedang berjalan; None/"" -> riwayat kosong.
        current_prompt: prompt yang SEDANG dikirim. Bila pesan terakhir di DB
            sama dengan ini, pesan itu dibuang agar prompt tidak terkirim dua
            kali (jalur retry/idempoten: pesan user sudah ter-insert sebelum
            request ulang masuk).

    Returns:
        [{"role": "user"|"assistant", "content": str}, ...]

    Tidak pernah melempar: kegagalan DB -> [] (percakapan tetap jalan, hanya
    tanpa konteks) supaya gangguan riwayat tidak mematikan fitur chat.
    """
    limit = _history_limit()
    if not session_id or limit <= 0:
        return []
    try:
        rows = db.get_messages(user_email, session_id) or []
    except Exception as exc:  # noqa: BLE001 - riwayat opsional, jangan 500
        print(f"[load_history] {type(exc).__name__}: {str(exc)[:200]}")
        return []

    cap = _history_char_cap()
    out: list[dict] = []
    for row in rows:
        role = str((row or {}).get("role") or "").strip().lower()
        if role not in ("user", "assistant"):
            continue  # 'system'/'tool' tidak dikirim sebagai konteks obrolan
        text = str((row or {}).get("content") or "").strip()
        if not text:
            continue
        if len(text) > cap:
            text = text[:cap] + "…"
        out.append({"role": role, "content": text})

    # Buang pesan user terakhir bila identik dengan prompt yang sedang dikirim
    # (jalur retry: pesan sudah tersimpan sebelum agen dijalankan).
    if (current_prompt and out and out[-1]["role"] == "user"
            and out[-1]["content"].strip() == current_prompt.strip()):
        out.pop()

    return out[-limit:] if limit else []


def _to_genai_history(history: list[dict] | None) -> list[Any]:
    """Riwayat -> format `types.Content` untuk `client.chats.create(history=...)`.

    Gemini memakai peran "user" dan "model" (bukan "assistant").
    """
    from google.genai import types as _types

    contents: list[Any] = []
    for h in history or []:
        role = "user" if h.get("role") == "user" else "model"
        contents.append(_types.Content(role=role, parts=[_types.Part(text=str(h.get("content") or ""))]))
    return contents


def _to_lc_history(history: list[dict] | None) -> list[Any]:
    """Riwayat -> HumanMessage/AIMessage untuk jalur free-llm-gateway."""
    from langchain_core.messages import AIMessage, HumanMessage

    msgs: list[Any] = []
    for h in history or []:
        if h.get("role") == "user":
            msgs.append(HumanMessage(content=str(h.get("content") or "")))
        else:
            msgs.append(AIMessage(content=str(h.get("content") or "")))
    return msgs


def _agentic_run_gateway(prompt: str, email: str, model_id: str,
                         gw_url: str, gw_key: str,
                         roster: list[str] | None = None,
                         history: list[dict] | None = None) -> dict:
    """Agentic loop via free-llm-gateway (self-hosted, OpenAI-compatible).

    Kontrak sama dengan `_agentic_run_direct` -> {reply, meta}, sehingga
    endpoint /chat tidak perlu tahu jalur mana yang dipakai. Tool calling
    memakai skema JSON `tools.TOOL_SCHEMAS_OPENAI` (turunan TOOL_DECLARATIONS
    Gemini) dan dieksekusi `tools.execute_tool`; CredentialMissingError
    dibiarkan menyebar agar endpoint mengubahnya jadi needs_credential.

    Args:
        history: riwayat percakapan (lama->baru) sebagai konteks multi-turn.
            None/[] -> hanya prompt terbaru yang dikirim (perilaku lama).

    Kegagalan transport/kuota gateway -> coba model roster berikutnya
    (fallback antar-provider tetap ditangani gateway itu sendiri).
    """
    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
    from langchain_openai import ChatOpenAI

    def _bound(model_name: str, timeout: float | None = None,
               with_tools: bool = True):
        llm = ChatOpenAI(
            model=model_name,
            api_key=gw_key,
            base_url=f"{gw_url}/v1",
            temperature=float(os.getenv("AGENT_TEMPERATURE", "0.1")),
            # Tunnel cloudflared bisa "menggantung" (koneksi terbuka, tak ada
            # balasan). Tanpa timeout eksplisit LangChain menunggu tanpa henti
            # sehingga fallback Gemini di `_agentic_run_direct` tak pernah
            # tercapai. max_retries=0: failover antar-model ditangani loop ini.
            timeout=timeout or _gateway_attempt_timeout_sec(),
            max_retries=0,
        )
        if not with_tools:
            # Retry tanpa tools: sebagian kandidat hulu menolak payload
            # ber-tools dengan 500 polos (lihat `_tools_unsupported`).
            return llm
        try:
            return llm.bind_tools(tools.TOOL_SCHEMAS_OPENAI)
        except Exception as exc:  # noqa: BLE001 - model tanpa tool calling
            print(f"[api_server] bind_tools dilewati ({model_name}): {exc}")
            return llm

    order = [model_id] + [m for m in (roster or []) if m != model_id][:2]
    # ANGGARAN TOTAL, bukan per model (lihat INVARIANT di blok "ANGGARAN WAKTU
    # LLM PER REQUEST"). Deadline fase gateway ini sudah MENGURANGI jatah yang
    # direservasi untuk Gemini cadangan, sehingga habisnya anggaran gateway
    # tidak langsung berarti user menerima error.
    deadline = time.time() + max(5.0, _llm_budget_sec() - _FALLBACK_RESERVE_SEC)
    last_err: Exception | None = None
    for cand in order:
        # Deadline diperiksa SETIAP iterasi (dulu hanya bila sudah ada error)
        # dan timeout percobaan dipangkas ke sisa anggaran: satu model yang
        # menggantung tidak boleh menelan seluruh anggaran.
        remaining = deadline - time.time()
        if remaining <= 1.0:
            print("[api_server] anggaran waktu gateway habis -> fallback Gemini")
            break
        chat_model = _bound(cand, min(remaining, _gateway_attempt_timeout_sec()))
        # KONTEKS MULTI-TURN: system -> riwayat sesi -> prompt terbaru. Tanpa
        # riwayat, model "amnesia" dan mengabaikan hal yang sudah dibahas user.
        messages: list[Any] = [SystemMessage(content=_AGENT_SYSTEM)]
        messages.extend(_to_lc_history(history))
        messages.append(HumanMessage(content=prompt))
        _t0 = time.time()
        tools_dropped = False
        try:
            try:
                resp = chat_model.invoke(messages)
            except Exception as exc:  # noqa: BLE001 - payload ber-tools ditolak?
                if not _tools_unsupported(exc):
                    raise
                # Retry SEKALI tanpa tools: model yang diminta TETAP dipakai,
                # dan kejadiannya ditandai di meta agar bisa dibedakan dari
                # fallback antar-provider.
                print(f"[api_server] {cand}: tools ditolak "
                      f"({type(exc).__name__}) -> retry tanpa tools")
                chat_model = _bound(
                    cand, min(remaining, _gateway_attempt_timeout_sec()),
                    with_tools=False)
                tools_dropped = True
                resp = chat_model.invoke(messages)
            for _ in range(3):  # maksimal 3 ronde tool calling
                calls = getattr(resp, "tool_calls", None) or []
                if not calls:
                    break
                messages.append(resp)
                for call in calls:
                    name = str((call or {}).get("name") or "")
                    args = dict((call or {}).get("args") or {})
                    try:
                        result = tools.execute_tool(name, args, email)
                    except CredentialMissingError:
                        raise  # -> endpoint ubah jadi needs_credential
                    except Exception as exc:  # noqa: BLE001 - alat gagal
                        result = f"Gagal menjalankan {name}: {exc}"
                    messages.append(ToolMessage(
                        content=str(result),
                        tool_call_id=str((call or {}).get("id") or name),
                    ))
                resp = chat_model.invoke(messages)
            usage = getattr(resp, "usage_metadata", None) or {}
            return {
                "reply": _content_text(resp),
                "meta": {
                    "model": cand,
                    "requested_model": model_id,
                    "latency_ms": int((time.time() - _t0) * 1000),
                    "prompt_tokens": int(usage.get("input_tokens") or 0),
                    "completion_tokens": int(usage.get("output_tokens") or 0),
                    "total_tokens": int(usage.get("total_tokens") or 0),
                    "fallback": bool(cand != model_id),
                    # Alasan HANYA diisi saat benar-benar fallback: tanpa itu,
                    # frontend akan menampilkan badge pada request normal.
                    "fallback_reason": (_fallback_reason(last_err)
                                        if cand != model_id and last_err is not None
                                        else None),
                    "gateway": True,
                    # True = model yang diminta TETAP dipakai, hanya `tools`
                    # yang dibuang karena hulu menolaknya (lihat
                    # `_tools_unsupported`). Bukan fallback provider lain.
                    "tools_dropped": tools_dropped,
                },
            }
        except CredentialMissingError:
            raise
        except Exception as exc:  # noqa: BLE001 - coba model roster berikutnya
            last_err = exc
            print(f"[api_server] gateway {cand} gagal: {type(exc).__name__}: {exc}")
    raise HTTPException(
        503,
        f"Gateway belum bisa melayani permintaan ({type(last_err).__name__}). "
        "Coba lagi dalam 1 menit.",
    )


# ---------------------------------------------------------------------------
# ANGGARAN WAKTU LLM PER REQUEST (satu sumber kebenaran)
# ---------------------------------------------------------------------------
# INVARIANT (dibuktikan empiris 2026-09-16): seluruh kerja LLM satu request
# `/chat` HARUS selesai JAUH SEBELUM klien membatalkan request.
#   - frontend: `FETCH_TIMEOUT_MS` = 90s (`AbortController` di lib/api.ts)
#   - E2E: `page.waitForResponse(...)` + `timeout` per-test di playwright.config
# Bug nyata yang diperbaiki: `LLM_GATEWAY_BUDGET` dulu 90s — SAMA PERSIS dengan
# abort klien — dan fase Gemini cadangan tidak dibatasi sama sekali (4 percobaan
# tanpa timeout + sleep 9s). Akibatnya backend masih bekerja saat klien sudah
# menyerah: user melihat "Server lambat, coba lagi" padahal jawabannya hampir
# siap, dan pekerjaan itu terbuang. E2E ikut merah palsu.
# Sekarang: budget = TOTAL (gateway + cadangan), dan `_FALLBACK_RESERVE_SEC`
# disisihkan untuk jalur Gemini supaya outage gateway TIDAK otomatis menjadi
# error ke user.
_LLM_BUDGET_DEFAULT_SEC = 45.0
_FALLBACK_RESERVE_SEC = 15.0


def _llm_budget_sec() -> float:
    """Anggaran TOTAL kerja LLM satu request (gateway + Gemini cadangan)."""
    try:
        return max(5.0, float(os.getenv("LLM_GATEWAY_BUDGET",
                                        str(_LLM_BUDGET_DEFAULT_SEC))))
    except ValueError:
        return _LLM_BUDGET_DEFAULT_SEC


def _gateway_attempt_timeout_sec() -> float:
    """Timeout SATU percobaan model lewat gateway (default 20s).

    Dulu 45s. Terlalu panjang relatif terhadap anggaran TOTAL: dua model yang
    menggantung sudah menelan seluruh anggaran sebelum fallback Gemini sempat
    berjalan.
    """
    try:
        return max(5.0, float(os.getenv("LLM_GATEWAY_TIMEOUT", "20")))
    except ValueError:
        return 20.0


# ---------------------------------------------------------------------------
# AGENTIC LOOP (setara _agentic_run, bebas dari Streamlit)
# ---------------------------------------------------------------------------
def _agentic_run_direct(prompt: str, email: str, model: str | None = None,
                        user_tier: str = "free",
                        history: list[dict] | None = None) -> dict:
    """Jalankan Gemini dengan tool calling; eksekusi alat; loop.

    Apabila alat butuh kredensial, melempar CredentialMissingError (dibiarkan
    menyebar ke caller / endpoint untuk diubah jadi respons needs_credential).
    Errores del modelo (503/quota) se reintentan con backoff; si persisten,
    lanza HTTPException(503) con mensaje claro.

    Args:
        history: riwayat percakapan (lama->baru) untuk konteks multi-turn.
            Dikirim sebagai `history` pada `client.chats.create` (Gemini) dan
            sebagai HumanMessage/AIMessage (jalur gateway), sehingga agen ingat
            apa yang sudah dibahas di sesi yang sama.

    Returns:
        dict {reply, meta} dengan meta = {model, requested_model, latency_ms,
        prompt_tokens, completion_tokens, total_tokens, fallback, fallback_reason}.
        `requested_model` = model yang DIMINTA user (None bila user tidak
        memilih); `model` = model yang benar-benar menjawab. Keduanya dikirim
        agar UI bisa menampilkan "diminta vs dipakai" (claude-jacked 0.89.0).
    """
    import time as _time

    # Disimpan SEBELUM `model` ditimpa oleh fallback gateway di bawah, supaya
    # meta tetap melaporkan apa yang sebenarnya diminta user.
    requested_model = (model or "").strip() or None
    # Awal hitungan anggaran request ini. Dipakai jalur Gemini di bawah supaya
    # batas waktunya TIDAK bergantung pada berapa lama fase gateway berjalan
    # (lihat INVARIANT di blok "ANGGARAN WAKTU LLM PER REQUEST").
    _t_req = time.time()

    # Jalur utama: free-llm-gateway (self-hosted) bila model ada di roster.
    gw = _gateway_target()
    gw_err: HTTPException | None = None
    if gw and model and model in gw[2]:
        try:
            return _agentic_run_gateway(prompt, email, model, gw[0], gw[1], gw[2],
                                        history=history)
        except HTTPException as exc:
            if exc.status_code != 503:
                raise
            # Tunnel/gateway sedang turun (URL cloudflared quick-tunnel berganti
            # tiap restart): jangan sampai Nexus ikut mati -> teruskan ke jalur
            # Gemini langsung (kunci server) dengan model cadangan.
            gw_err = exc
            print(f"[api_server] gateway 503 -> fallback Gemini: {exc.detail}")

    # ---- Pool kunci Gemini: rotasi + cooldown PER KUNCI --------------------
    # Sebelumnya hanya SATU kunci yang dipakai (`GOOGLE_API_KEY or GEMINI_API_KEY
    # or GEMINI_KEY_1`), sehingga satu respons 429 mematikan seluruh jalur
    # cadangan (single point of failure yang membuat 2 tes E2E `/chat` skip).
    # Bukti 2026-09-16: `.env` memuat `GEMINI_KEY_1..13` (13 kunci UNIK —
    # fingerprint SHA-256 berbeda) dan kuota 429 bersifat per PROJECT
    # (`quotaId=GenerateRequestsPerMinutePerProjectPerModel-FreeTier`), jadi
    # rotasi kunci benar-benar memulihkan, bukan sekadar mengganti nama slot.
    _pool = gemini_key_pool.pool()
    if not _pool.size:
        if gw_err is not None:
            raise gw_err  # tanpa kunci Gemini, laporkan kegagalan gateway apa adanya
        # Pool kosong = kondisi KONFIGURASI/LAYANAN (env server tidak memuat
        # `GEMINI_KEY_*`), bukan bug server. Sebelumnya ini 500, sehingga UI
        # menampilkan "Terjadi kesalahan internal" dan menyembunyikan penyebab
        # sebenarnya; 503 adalah kontrak yang benar untuk "coba lagi nanti".
        raise HTTPException(
            503, "Semua kunci API tidak tersedia. Coba lagi dalam 1 menit.")

    if gw_err is not None:
        model = os.getenv("AGENT_FALLBACK_MODEL", "gemini-2.5-flash")
    model_id, tier_fallback, resolve_reason = _resolve_model(model, user_tier)
    # Kunci pertama untuk model ini. `acquire` menghormati cooldown per kunci DAN
    # blokir per (kunci, model), jadi kunci yang baru kena 429/404 tidak dipakai.
    # `None` = semua kunci sedang dihukum -> kegagalan SEMENTARA (503), bukan 401/
    # 500: menebak kunci yang sedang cooldown hanya memperpanjang hukuman.
    _acquired = _pool.acquire(model_id)
    if _acquired is None:
        raise HTTPException(
            503, "Semua kunci model ini sedang cooldown (kuota). Coba lagi.")
    cur_fp, _ = _acquired
    print(f"[api_server] Gemini {_pool.label(cur_fp)} model={model_id} "
          f"(pool={_pool.size} kunci)")
    fallback_used = bool(tier_fallback) or gw_err is not None
    # Alasan fallback, berurut prioritas:
    #   1. penolakan tier/id tak tersedia (resolve) — paling informatif;
    #   2. kegagalan gateway (kuota/overload/tunnel turun) — klasifikasi teks;
    #   3. tanpa tanda apa pun -> None (request normal, badge TIDAK muncul).
    if resolve_reason:
        fallback_reason: str | None = resolve_reason
    elif gw_err is not None:
        # `_agentic_run_gateway` melempar 503 hanya setelah SEMUA kandidat
        # gagal. Bila pesannya memuat sinyal spesifik (kuota/rate/overload)
        # pakai itu — lebih informatif; selain itu penyebab sebenarnya adalah
        # gateway tak bisa dihubungi (tunnel turun), bukan model yang hilang.
        # Tanpa pemetaan ini user melihat "Model tidak tersedia untuk tier
        # Anda" padahal masalahnya di sisi gateway.
        _gw_reason = _fallback_reason(gw_err)
        fallback_reason = _gw_reason if _gw_reason != "model_unavailable" else "gateway_down"
    else:
        fallback_reason = None

    # Batas TOTAL jalur Gemini. Bila gateway gagal cepat, jatah ini tetap utuh
    # karena dihitung dari AWAL request, bukan dari akhir fase gateway.
    deadline = _t_req + max(5.0, _llm_budget_sec())
    # Klien ter-cache per kunci (pembuatan baru terukur ~0,86s -> mahal di loop).
    client = _pool.client(cur_fp)
    config = types.GenerateContentConfig(
        temperature=0.1,
        system_instruction=_AGENT_SYSTEM,
        tools=tools.TOOL_DECLARATIONS,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    chat = client.chats.create(model=model_id, config=config,
                               history=_to_genai_history(history))

    fallback_model = os.getenv("AGENT_FALLBACK_MODEL", "gemini-2.5-flash")

    def _chat_with(fp: str, mid: str):
        """Chat baru untuk (kunci, model) — riwayat percakapan tetap dibawa.

        Dipakai saat rotasi kunci/model: `Chat` terikat pada satu klien, jadi
        berganti kunci berarti membuat objek chat baru. `history` DB (bukan
        `get_history()`) sengaja dipakai supaya konteks deterministik dan
        percobaan yang gagal di tengah tidak ikut terduplikasi.
        """
        return _pool.client(fp).chats.create(
            model=mid, config=config, history=_to_genai_history(history))

    def _send_guarded(chat_obj, msg):
        """Kirim pesan; saat kuota/overload -> ROTASI KUNCI, lalu pindah model 1x.

        Perubahan 2026-09-16 (memulihkan 2 tes E2E `/chat` yang selalu skip):
        dulu 429/503 di-retry 4x pada KUNCI dan MODEL yang SAMA dengan sleep
        1,5/3/4,5/6s. Padahal kuota bersifat per PROJECT (`quotaId=...PerMinute
        PerProjectPerModel`, limit 5) dan per MODEL, jadi retry seperti itu tidak
        mungkin pulih sebelum anggaran habis -> selalu berakhir `503 "Model
        sedang sibuk"`. Sekarang kunci yang gagal DIHUKUM sesuai payload
        (`gemini_key_pool.classify_error`) lalu rotasi ke kunci berikutnya; bila
        semua kunci habis untuk model ini barulah pindah model — model lain
        memakai ember kuota berbeda, jadi ini benar-benar menambah peluang sukses
        (bukan sekadar mengganti nama).
        """
        nonlocal model_id, fallback_used, chat, cur_fp, fallback_reason
        ctx = chat_obj
        model_switches = 0
        # True bila setidaknya satu kunci ditolak hulu karena 401 (kunci dicabut).
        # Menentukan PESAN 503 terakhir supaya tidak salah dilaporkan sebagai
        # "sibuk/kuota" padahal masalahnya kredensial.
        dead_seen = False

        def _final_503():
            """503 KONKLUSIF setelah semua kunci/model dicoba (bukan 500)."""
            if dead_seen:
                return HTTPException(
                    503,
                    "Semua kunci Gemini ditolak hulu (401 UNAUTHENTICATED). "
                    "Periksa GEMINI_KEY_* / GOOGLE_API_KEY di server.")
            return HTTPException(
                503, "Model sedang sibuk (quota/overload). Coba lagi dalam 1 menit.")

        while True:
            # Batas TOTAL request: percobaan Gemini juga tidak boleh melewati
            # anggaran. Tanpa guard ini klien sudah abort saat jawaban datang
            # (bug "Server lambat, coba lagi" pada backend yang sebenarnya sehat).
            if time.time() > deadline - 1.0:
                raise HTTPException(503, "Batas waktu agen tercapai. Coba lagi.")
            try:
                return ctx.send_message(msg)
            except Exception as exc:  # noqa: BLE001
                # Klasifikasi berbasis payload, bukan tebakan: `unknown` berarti
                # bukan urusan kuota/overload -> jangan dibajak oleh pool.
                kind, ttl = gemini_key_pool.classify_error(exc)
                if kind == "unknown":
                    raise
                if kind == "key_dead":
                    dead_seen = True
                _pool.mark(cur_fp, model_id, kind=kind, ttl=ttl)
                print(f"[api_server] Gemini {_pool.label(cur_fp)} model={model_id} "
                      f"gagal ({kind}) -> rotasi kunci; cooldown={ttl:.0f}s "
                      f"stats={_pool.stats()}")
                nxt = _pool.acquire(model_id)
                if nxt is not None:
                    cur_fp, _ = nxt
                    ctx = chat = _chat_with(cur_fp, model_id)
                    continue
                # Semua kunci habis untuk model ini -> pindah model (1x saja).
                # Model cadangan default (`gemini-2.5-flash`) justru model yang
                # ikut kehabisan; karena kuota per-model, cadangan tetap masuk
                # akal, tetapi hanya sebagai percobaan terakhir.
                model_switches += 1
                if (model_switches > 1 or fallback_used or not fallback_model
                        or fallback_model == model_id):
                    raise _final_503()
                fallback_used = True
                # `fallback_reason` yang sudah terisi (gateway/tier) tetap
                # dipertahankan: penyebab pertama lebih informatif bagi user.
                if fallback_reason is None:
                    fallback_reason = _fallback_reason(exc)
                model_id = fallback_model
                nxt = _pool.acquire(model_id)
                if nxt is None:
                    raise _final_503()
                cur_fp, _ = nxt
                ctx = chat = _chat_with(cur_fp, model_id)

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
        "requested_model": requested_model,
        "latency_ms": latency_ms,
        "prompt_tokens": int(pt or 0),
        "completion_tokens": int(ct or 0),
        "total_tokens": int(tt or 0),
        "fallback": bool(fallback_used),
        # `fallback_reason` hanya terisi saat fallback — UI memakainya sebagai
        # teks penyebab di badge, bukan sekadar penanda "terjadi fallback".
        "fallback_reason": fallback_reason if fallback_used else None,
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


# ---------------------------------------------------------------------------
# KUOTA HARIAN — helper (struktur bisnis final 2026-09-18)
# ---------------------------------------------------------------------------
QUOTA_LABELS = {
    "gemma": "Gemma 4 (default)",
    "flash": "DeepSeek Flash",
    "pro": "DeepSeek Pro",
}


def _bucket_model_id(bucket: str) -> str | None:
    """Id model NYATA untuk sebuah bucket kuota, diambil dari roster live.

    Id tidak di-hardcode: katalog gateway memakai prefix provider
    (`deepseek-ai/deepseek-v4-flash-0731`, `google/gemma-4-31b-it`), dan id bisa
    berganti. Bucket `pro` bergantung pada ketersediaan varian Pro di katalog
    (belum tersedia 2026-09-18) — bila kosong, fallback ke bucket berikutnya.
    """
    try:
        ids = [str(m.get("id") or "") for m in md.get_available_models()]
    except Exception:  # noqa: BLE001 - discovery opsional; jangan gagalkan chat
        return None
    if bucket == "pro":
        cand = [i for i in ids if "deepseek" in i.lower() and "pro" in i.lower()]
    elif bucket == "flash":
        cand = [i for i in ids if "deepseek" in i.lower()]
    else:
        cand = [i for i in ids if "gemma" in i.lower()]
    return cand[0] if cand else None


def _quota_exhausted_message(info: dict, tier: str) -> str:
    """Pesan 429 yang menjelaskan SISA dan KAPAN reset (tanpa menyalahkan user)."""
    label = QUOTA_LABELS.get(info.get("bucket", ""), info.get("bucket", "model"))
    return (
        "Kuota harian habis untuk %s: %d/%d request terpakai (tier %s). "
        "Kuota direset 00:00 WIB. Naikkan tier untuk kuota lebih besar."
        % (label, info.get("used", 0), info.get("limit", 0), (tier or "free"))
    )


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

    # ---- KUOTA HARIAN (struktur bisnis final 2026-09-18) -------------------
    # Diletakkan SETELAH early-return idempotensi dan SEBELUM menulis pesan:
    #  * request yang di-replay (sudah dijawab) TIDAK memakan kuota lagi;
    #  * request yang ditolak kuota TIDAK meninggalkan pesan setengah jadi.
    _q_requested = (req.model or "").strip() or None
    _q_run_model = _q_requested
    _q_allowed, _q_info = db.check_quota(user_email, _q_requested or "", user_tier)
    _q_fallback_from = None
    if not _q_allowed:
        # AUTO-FALLBACK Pro -> Flash -> Gemma: user tidak langsung ditolak hanya
        # karena bucket termahal habis.
        _q_fb = db.quota_fallback_bucket(user_email, user_tier, _q_info["bucket"])
        _q_fb_model = _bucket_model_id(_q_fb) if _q_fb else None
        if not _q_fb or not _q_fb_model:
            raise HTTPException(429, _quota_exhausted_message(_q_info, user_tier))
        _q_fallback_from = _q_info["bucket"]
        _q_run_model = _q_fb_model
        print(f"[api_server] kuota {_q_info['bucket']} habis -> fallback "
              f"{_q_fb} ({_q_fb_model}) untuk {user_email}")

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

    # KONTEKS MULTI-TURN: muat riwayat sesi SEBELUM pesan baru disimpan, supaya
    # prompt yang sedang dikirim tidak ikut terkirim dua kali (sebagai riwayat
    # DAN sebagai prompt). Tanpa ini agen lupa isi percakapan turn sebelumnya.
    history = load_history(user_email, session_id, current_prompt=req.prompt)

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
        _run = _agentic_run_direct(req.prompt, user_email, model=_q_run_model,
                                   user_tier=user_tier, history=history)
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

    # ---- CATAT KUOTA (setelah jawaban BENAR-BENAR tersimpan) ---------------
    # Yang dihitung = model yang benar-benar dipakai (`meta.model`), bukan yang
    # diminta: fallback internal (tier-gate/gateway) harus masuk ember yang
    # benar supaya hitungannya jujur.
    _q_counted_model = str(meta.get("model") or _q_run_model or "")
    try:
        db.increment_quota(user_email, _q_counted_model)
    except Exception as exc:  # noqa: BLE001
        # Pencatatan kuota gagal BUKAN alasan membatalkan jawaban yang sudah jadi;
        # dicatat ke log supaya tetap terlihat (bukan gagal senyap).
        print(f"[api_server] gagal mencatat kuota: {type(exc).__name__}: {exc}")
    try:
        meta["quota"] = db.quota_status(user_email, user_tier)
    except Exception as exc:  # noqa: BLE001
        print(f"[api_server] gagal membaca status kuota: {type(exc).__name__}: {exc}")
    meta["quota_bucket"] = db.quota_bucket(_q_counted_model)
    if _q_fallback_from:
        meta["quota_fallback"] = True
        meta["quota_fallback_from"] = _q_fallback_from

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
# ENDPOINT 1a-2: GET /quota  (kuota HARIAN per model — untuk dashboard & warning)
# ---------------------------------------------------------------------------
@app.get("/quota")
def get_quota(authorization: str | None = Header(None)):
    """Kuota hari ini untuk user JWT: dipakai progress bar + warning pre-flight.

    Satuannya **REQUEST** (1 request = 1 RPD), bukan "chat": satu percakapan bisa
    berisi beberapa request (agent loop), jadi menampilkan "chat" akan menipu.
    """
    user = security.get_current_user(authorization)
    email = user["email"]
    try:
        _u = db.get_or_create_user(email, "", auth_id=user.get("id"))
        tier = str((_u or {}).get("tier", "free") or "free").strip().lower()
    except Exception:  # noqa: BLE001
        tier = "free"
    try:
        st = db.quota_status(email, tier)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"Gagal membaca kuota: {type(exc).__name__}: {exc}")
    # Label manusiawi + penanda bucket mana yang boleh dipakai tier ini.
    st["labels"] = dict(QUOTA_LABELS)
    st["unit"] = "request"
    st["enabled_buckets"] = [b for b, v in st["buckets"].items() if v["limit"] > 0]
    return {"status": "success", "email": email, **st}


# ---------------------------------------------------------------------------
# ENDPOINT 1b: GET /models  (daftar model + flag locked per tier user)
# ---------------------------------------------------------------------------
@app.get("/models")
def list_models(authorization: str | None = Header(None)):
    """Daftar model dari DISCOVERY live (bukan hardcode) + flag locked.

    locked=False -> bisa dipilih. locked=True -> redup + Upgrade link.
    `refreshed_at` menandai umur cache discovery (TTL 1 jam).
    """
    user = security.get_current_user(authorization)
    try:
        _u = db.get_or_create_user(user["email"], "", auth_id=user["id"])
        tier = str((_u or {}).get("tier", "free") or "free").strip().lower()
    except Exception:
        tier = "free"
    is_plus = tier in PLUS_TIERS
    default_id = _default_model_id()
    discovered = md.get_available_models()
    items = [
        {**m, "locked": bool(m.get("tier") == "plus" and not is_plus)}
        for m in discovered
    ]
    return {"status": "success", "tier": tier, "default": default_id,
            "models": items,
            "refreshed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(md._cache["ts"]))}


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


def _dodo_amount(payload: dict, data: dict) -> float:
    """Ambil nominal dari payload Dodo (beberapa bentuk/versi payload diterima).

    SENGAJA TIDAK dikonversi satuan: Dodo mengirim nominal dalam satuan terkecil
    (mis. sen/rupiah terkecil) pada sebagian event. Konversi ke rupiah penuh
    adalah keputusan bisnis -- dicatat sebagai pending, bukan ditebak di sini.
    """
    for src in (data, payload):
        if not isinstance(src, dict):
            continue
        for key in ("amount", "total_amount", "amount_paid", "credits"):
            v = src.get(key)
            if v in (None, ""):
                continue
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return 0.0


@app.post("/api/payments/dodo-webhook")
async def dodo_webhook(request: Request):
    """Dodo Payments webhook -> naik TIER + topup saldo (idempoten).

    KEAMANAN: Standard Webhooks signature (webhook-id + webhook-timestamp +
    webhook-signature) diverifikasi `dodo_verify.verify_dodo_webhook` (SDK
    `webhooks.unwrap`). Tanpa signature sah -> 401. TIDAK ADA dev-bypass.

    IDEMPOTENSI (temuan audit: dulu bisa double-credit): tiap `webhook-id`
    diklaim SEKALI di tabel `payment_events`. Klaim berstatus "processed" ->
    balas `already_processed` tanpa menyentuh tier/saldo. Klaim "pending"
    (percobaan sebelumnya gagal) SENGAJA dilanjutkan supaya retry Dodo tidak
    menghilangkan hak user.

    TIER (keputusan produk 2026-09-18): bayar = naik tier (free -> plus),
    bukan sekadar saldo. Tier diambil dari `metadata.tier` (dipilih di checkout),
    default "plus".
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
        payload = json.loads(raw) if raw else {}
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "Body harus JSON.")

    event_id = headers["webhook-id"]
    event_type = str(payload.get("type") or payload.get("event") or "").strip().lower()
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        data = {}
    customer = data.get("customer") or {}
    if not isinstance(customer, dict):
        customer = {}
    # Bentuk resmi = `data.customer.email`; bentuk lama/uji = `data.email`,
    # `customer_email`, atau top-level. Semua diterima supaya tidak ada
    # pembayaran yang gagal dipetakan hanya karena bentuk payload berbeda.
    email = (customer.get("email") or data.get("email") or payload.get("email")
             or data.get("customer_email") or payload.get("customer_email"))
    if not email:
        raise HTTPException(422, "email customer wajib diisi.")

    amount = _dodo_amount(payload, data)
    payment_id = data.get("payment_id") or payload.get("payment_id")

    # --- KLAIM EVENT (idempotency key = webhook-id) -------------------------
    try:
        state = db.claim_payment_event(event_id, payment_id, event_type, amount, email)
    except Exception as exc:  # noqa: BLE001
        # Gagal mencatat = tidak boleh dikreditkan; 5xx membuat Dodo mengirim
        # ulang (bukan gagal senyap).
        raise HTTPException(500, f"Gagal mencatat event pembayaran: {exc}")
    if state == "processed":
        return {"status": "already_processed", "webhook_id": event_id,
                "event": event_type}

    try:
        if event_type in ("payment.succeeded", "subscription.active",
                          "subscription.renewed", "payment.successful"):
            tier = str((data.get("metadata") or {}).get("tier") or "plus").strip().lower()
            db.update_tier(email, tier)
            credited = db.topup_balance(email, amount) if amount > 0 else None
            result = {"status": "success", "email": email, "tier": tier,
                      "credited": amount if amount > 0 else None,
                      "event": event_type, "retry": state == "pending"}
        elif event_type in ("refund", "refund.succeeded", "payment.refunded",
                            "dispute", "dispute.created"):
            res = db.deduct_balance(email, amount)
            if res is None:
                # Saldo kurang: potong apa pun supaya refund TETAP tercatat
                # (saldo boleh negatif; lebih baik jujur daripada hilang senyap).
                res = db.topup_balance(email, -amount)
            result = {"status": "refunded", "email": email, "deducted": amount,
                      "balance": res, "event": event_type, "retry": state == "pending"}
        else:
            # Event lain (mis. payment.failed) tetap dicatat selesai supaya tidak
            # diulang terus oleh retry Dodo, tanpa menyentuh tier/saldo.
            result = {"status": "ignored", "event": event_type,
                      "webhook_id": event_id}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        # Tier/saldo GAGAL tersimpan -> jangan tandai selesai; 5xx agar Dodo retry.
        raise HTTPException(500, f"Gagal memproses webhook: {exc}")

    try:
        db.mark_payment_event_processed(event_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal menandai event selesai: {exc}")
    return result


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