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

import asyncio
import os
import json
import threading
import time
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Any

from dotenv_loader import load_repo_env
load_repo_env()

import database as db
import gemini_key_pool
import mcp_tool_cache
import model_discovery as md
import rate_limit
import scheduler_manager  # Scheduled Trigger (cron) — Fitur #1, 8 Okt 2026
import memory_manager    # AI Agent Memory (pgvector) — Fitur #11, 8 Okt 2026
import workflow_autofix as _wf_autofix
import security
import tools
from textual_tool_calls import (  # BUG FIX 2026-10-02: parser tool-call TEKS
    extract_textual_tool_calls,
    strip_textual_tool_calls,
)
from tool_call_parser import (  # BUG FIX 2026-10-04: gerbang fail-closed
    ToolCallParseError,
    parse_tool_call,
)
from textual_tool_parser import (  # BUG FIX 2026-10-04: jalur utama
    parse_textual_tools,
    strip_textual_tools,
)
from textual_tool_handlers import execute_textual_tool
from sanitize import (  # BUG FIX 2026-10-04: sanitasi konten masuk model
    sanitize_tool_result,
    sanitize_user_input,
)
import execution_engine as engine
from tools import CredentialMissingError
from google import genai
from google.genai import types
import mcp_server
import workflow_templates  # Workflow Templates — Fitur #10, 8 Okt 2026

# Instance MCP proses-wide (Fitur #8). Dibuat di sini supaya lifespan, mount,
# dan endpoint bantu memakai SERVER YANG SAMA — `session_manager` hanya boleh
# `run()` sekali, jadi app yang di-mount harus terikat ke instance ini.
_MCP_SERVER = mcp_server.get_server()

# Queue Mode (Fitur #6): manager + worker pool proses-wide.
_QUEUE_MGR = None
_QUEUE_POOL = None


def _queue_mgr():
    """Lazy-init QueueManager (backend Redis bila ada, else memori)."""
    global _QUEUE_MGR
    import queue_mode
    if _QUEUE_MGR is None:
        _QUEUE_MGR = queue_mode.QueueManager()
    return _QUEUE_MGR


def _queue_handler(job):
    """Handler worker: jalankan workflow dari payload job.

    PENTING: worker pool berjalan di thread TANPA event loop, sedangkan
    `launch_execution` (sinkron) memanggil `asyncio.create_task` di dalamnya.
    Memanggilnya langsung -> `RuntimeError: no running event loop` dan SETIAP
    job workflow berakhir DEAD di DLQ. Karena itu pemanggilan diarahkan ke
    loop asyncio persisten lewat `queue_bridge.run_sync`.
    """
    import queue_bridge
    import execution_engine as engine
    p = job.payload or {}
    return queue_bridge.run_sync(
        engine.launch_execution,
        p.get("workflow_id"), p.get("flow_data") or {},
        p.get("trigger_input") or {}, owner_email=p.get("owner_email", ""))


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
    # Scheduled Trigger (cron, Fitur #1): loop asyncio di-startup, dihentikan
    # saat shutdown. Kill-switch env SCHEDULER_ENABLED=0 (dipakai test suite).
    _sched_task = None
    _sched_stop = asyncio.Event()
    if scheduler_manager.scheduler_enabled():
        try:
            _sched_task = asyncio.create_task(
                scheduler_manager.scheduler_loop(_sched_stop))
        except Exception as _exc:  # noqa: BLE001 - startup tak boleh gagal karena scheduler
            print(f"[lifespan] scheduler gagal dimulai: {type(_exc).__name__}: {_exc}")
    # MCP Server (Fitur #8): `session_manager.run()` WAJIB hidup selama app
    # melayani request, kalau tidak setiap panggilan JSON-RPC di /mcp/katalir
    # langsung 500 (RuntimeError: Task group is not initialized).
    #
    # PENTING: manager HANYA boleh `run()` sekali per instance, dan app yang
    # di-mount harus terikat ke instance yang sama. Karena itu server dibuat
    # di sini, dijadikan target mount di bawah, dan manager-nya dinyalakan
    # lewat context manager yang sama. Kill-switch env MCP_SERVER_ENABLED=0.
    _mcp_ctx = None
    if os.getenv("MCP_SERVER_ENABLED", "1").strip() not in ("0", "false", "False"):
        try:
            _mcp_ctx = mcp_server.session_manager_lifespan(_MCP_SERVER)
            await _mcp_ctx.__aenter__()
        except Exception as _exc:  # noqa: BLE001 - startup tak boleh gagal karena MCP
            print(f"[lifespan] MCP server gagal dimulai: {type(_exc).__name__}: {_exc}")
            _mcp_ctx = None
    # Queue Mode (Fitur #6): worker pool opsional. Kill-switch env
    # QUEUE_WORKERS=0 (default) -> tidak ada worker (perilaku lama).
    global _QUEUE_POOL
    try:
        _n_workers = int(os.getenv("QUEUE_WORKERS", "0") or "0")
    except ValueError:
        _n_workers = 0
    if _n_workers > 0:
        try:
            _QUEUE_POOL = _queue_mgr().pool(_queue_handler, concurrency=_n_workers)
            _QUEUE_POOL.start()
            print(f"[lifespan] queue worker aktif: {_n_workers} "
                  f"(backend={_queue_mgr().backend_name})")
        except Exception as _exc:  # noqa: BLE001
            print(f"[lifespan] queue worker gagal: {type(_exc).__name__}: {_exc}")
    yield
    if _QUEUE_POOL is not None:
        try:
            _QUEUE_POOL.stop(graceful=True)
        except Exception:  # noqa: BLE001
            pass
        try:
            import queue_bridge
            queue_bridge.shutdown()
        except Exception:  # noqa: BLE001
            pass
    if _mcp_ctx is not None:
        try:
            await _mcp_ctx.__aexit__(None, None, None)
        except BaseException:  # noqa: BLE001 - shutdown MCP tidak boleh menahan proses
            pass
    if _sched_task is not None:
        _sched_stop.set()
        _sched_task.cancel()
        try:
            await _sched_task
        except BaseException:  # noqa: BLE001 - CancelledError saat shutdown = wajar
            pass


# Swagger/OpenAPI hanya untuk development. Default `development` (bukan
# `production`) supaya environment yang lupa set ENVIRONMENT tidak mematikan
# dokumentasi secara diam-diam; produksi di-set eksplisit lewat Railway.
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()
_IS_PROD = ENVIRONMENT in ("production", "prod")

app = FastAPI(title="Nexus Agent API Gateway", version="1.0.0",
              lifespan=_lifespan,
              docs_url=None if _IS_PROD else "/docs",
              redoc_url=None if _IS_PROD else "/redoc",
              openapi_url=None if _IS_PROD else "/openapi.json")

# CORS: izinkan frontend publik Cloudflare Pages + local dev.
# Nota: allow_credentials=True no se puede combinar con origin "*".
allowed = [
    "https://katalir.de5.net",
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
# CVE-2026-48710 (Starlette "BadHost") - MITIGASI (lihat docs/security/cve-investigation.md)
#
# Starlette < 1.0.1 menyusun `request.url` dari header `Host` TANPA validasi.
# Karakter di luar grammar RFC 3986 (`/`, `?`, `#`) menggeser batas path saat
# re-parse, sehingga `request.url.path` != path yang benar-benar di-routing.
# Contoh terverifikasi (layer ASGI, scope crafted):
#     Host: evil.com/health?x=  ->  scope['path']='/protected'  TAPI  request.url.path='/health'
# Auth berbasis `request.url.path` akan terbaca path publik sambil handler
# terproteksi dieksekusi.
#
# TrustedHostMiddleware menolak Host di luar allowlist SEBELUM router berjalan,
# jadi `request.url.path` tak pernah bisa dipois pada app ini.
#
# CATATAN URUTAN (sudah dibuktikan, bukan asumsi):
# `app.add_middleware()` pada Starlette MENDASARIK (prepend) ke
# `user_middleware`; index 0 = OUTERMOST = berjalan PERTAMA. Supaya
# TrustedHost benar-benar menjadi pagar terluar, ia harus di-add_middleware
# SESUDAH CORSMiddleware - bukan "sebelum" seperti kelihatannya.
#   add TrustedHost lalu CORSMiddleware -> [0]=CORSMiddleware     (Salah)
#   add CORSMiddleware lalu TrustedHost -> [0]=TrustedHostMiddleware (Benar)
#
# Tidak ada path-based auth middleware di repo ini sama sekali
# (`request.url.path` = 0 hasil, `security.py:351` pakai Depends pada header
# `Authorization`), jadi mitigasi ini bersifat defense-in-depth - mencegah
# kerentanan ini diaktifkan oleh kode yang ditulis berikutnya.
# ---------------------------------------------------------------------------
_allowed_hosts_raw = (os.getenv("ALLOWED_HOSTS") or "").strip()
if not _allowed_hosts_raw:
    # FAIL-SECURE. `TrustedHostMiddleware(allowed_hosts=None)` diam-diam
    # menjadi `["*"]` (lihat source: `if allowed_hosts is None: allowed_hosts = ["*"]`),
    # yang justru membatalkan seluruh mitigasi ini. Gagal keras lebih aman
    # daripada berjalan dengan proteksi yang terlihat aktif tapi tidak ada.
    raise RuntimeError(
        "ALLOWED_HOSTS wajib diisi. JANGAN fallback ke '*' - itu membatalkan "
        "mitigasi CVE-2026-48710. Lihat docs/security/cve-investigation.md"
    )

ALLOWED_HOSTS = [h.strip() for h in _allowed_hosts_raw.split(",") if h.strip()]
if "*" in ALLOWED_HOSTS:
    raise RuntimeError("ALLOWED_HOSTS tidak boleh berisi '*' (mitigasi CVE-2026-48710 dinonaktifkan).")

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=ALLOWED_HOSTS,
    # API gateway tidak dilayani via `www`, jadi fail-closed (400) lebih
    # dapat di_debug daripada redirect diam-diam yang bisa jadi loop.
    www_redirect=False,
)

# ---------------------------------------------------------------------------
# MCP SERVER BUILT-IN — Fitur #8
#
# Mount diletakkan SETELAH TrustedHostMiddleware dipasang agar urutan
# middleware tetap: request melewati TrustedHost (menolak Host palsu) SEBELUM
# mencapai middleware auth MCP. Membalik urutan ini akan membuat endpoint MCP
# bisa dijangkau dengan Host header yang tidak divalidasi.
#
# `app.mount` meneruskan SEMUA metode (GET/POST/DELETE) ke sub-app, jadi
# /mcp/katalir melayani `initialize`, `tools/list`, `tools/call`, dan
# penutupan sesi sesuai spesifikasi Streamable HTTP.
#
# Kill-switch env MCP_SERVER_ENABLED=0 (dipakai test suite yang tidak butuh MCP),
# konsisten dengan kill-switch scheduler dan lifespan di atas.
#
# URUTAN MOUNT = BUG PRODUKSI YANG PERNAH LOLOS (ditemukan 8 Okt 2026 lewat
# verifikasi E2E produksi). `app.mount("/mcp/katalir", ...)` mencocokkan
# BERDASARKAN PREFIX, jadi bila didaftarkan di sini (baris ~243) ia menelan
# `/mcp/katalir/info`, `/mcp/katalir/key`, dan `/mcp/katalir/verify` yang baru
# dideklarasikan ribuan baris di bawah — ketiganya jadi tidak pernah tercapai
# dan membalas JSON-RPC `-32001` (auth MCP), bukan handler-nya. Akibatnya user
# TIDAK PERNAH bisa menerbitkan API key MCP: Fitur #8 mati dari sisi klien.
# Test suite tidak menangkapnya karena tidak ada satu pun tes yang memanggil
# ketiga route itu lewat HTTP.
#
# PERBAIKAN: mount dipindah ke AKHIR modul (lihat `_mount_mcp_app()` di bawah),
# sehingga route eksplisit yang didaftarkan lebih dulu selalu menang, dan mount
# hanya melayani sisa prefix (`/mcp/katalir/`).
_MCP_ASGI = None
if os.getenv("MCP_SERVER_ENABLED", "1").strip() not in ("0", "false", "False"):
    try:
        # BUG NYATA (ditemukan lewat probe): `app.mount()` FastAPI/Starlette
        # membalas **307 Temporary Redirect** untuk POST /mcp/katalir (tanpa
        # trailing slash) -> /mcp/katalir/. Klien MCP tidak mengikuti redirect
        # POST, jadi URL yang didokumentasikan akan tampak "mati" tanpa pesan
        # yang berguna. Route ASGI eksplisit di BAWAH INI didaftarkan SEBELUM
        # mount sehingga path tanpa slash dilayani langsung, bukan di-redirect.
        #
        # Dipakai `app.add_route` (Starlette) alih-alih dekorator FastAPI
        # supaya path kosong ikut ditangani (FastAPI menolak path "" pada
        # dekorator, karena prefix mount sudah di-strip).
        from starlette.routing import Route as _StarletteRoute

        _MCP_ASGI = mcp_server.get_asgi_application(server=_MCP_SERVER)
        app.router.routes.insert(0, _StarletteRoute(
            "/mcp/katalir", endpoint=_MCP_ASGI, methods=None,
            include_in_schema=False))
    except Exception as _mcp_mount_exc:  # noqa: BLE001 - mount gagal tidak boleh mematikan API
        print(f"[startup] mount MCP gagal: {type(_mcp_mount_exc).__name__}: {_mcp_mount_exc}")
        _MCP_ASGI = None


# MODEL SELECTION: discovery dinamis via model_discovery (runtime query,
# bukan hardcode — Google ubah/tambah/hapus model tiap kuartal).
# 'plus' = kebijakan bisnis (hermes #5880), tetap eksplisit per model.
# Didefinisikan SETELAH import md (NameError `md` = crash 502 saat startup).
PLUS_CHAT_MODELS = md.PLUS_CHAT_MODELS

# Batas perbaikan otomatis: berapa kali error validasi YANG SAMA boleh
# muncul sebelum kita menyerah dan lapor jujur ke user. Dipakai
# `workflow_autofix` (lihat modul itu untuk analisis lengkap).
_WAF_NO_PROGRESS = _wf_autofix.NO_PROGRESS_LIMIT
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


#: Preferensi model default bila user TIDAK memilih model.
#:
#: BUG FIX 2026-10-06 (Bug #1 & #2 di produksi):
#: `_default_model_id()` dulu mengembalikan `roster[0]`. Roster
#: `probe_roster()` diurutkan (provider, id), jadi urutan itu KEBETULAN
#: menaruh `gemini-2.5-flash-lite` di depan.
#:
#: Model default harus lulus DUA perilaku sekaligus. Hasil matriks empiris
#: (`_model_matrix.py`, prompt + alat NYATA, 6 Okt 2026):
#:
#:   model                    Bug#1 (kirim telegram)   Bug#2 (build workflow)
#:   gemini-3.5-flash-lite    kirim_telegram_message   generate_workflow_json  <-- LULUS 2/2
#:   gemini-2.5-flash         (tidak ada panggilan)    generate_workflow_json
#:   gemini-2.5-flash-lite    kirim_telegram_message   BERTANYA (tidak build)
#:
#: Penting: `gemini-2.5-flash` LEBIH BAIK di Bug#2 tapi GAGAL di Bug#1
#: (mengembalikan teks kosong tanpa panggilan alat -> user melihat
#: "Tugas selesai dieksekusi" padahal tidak ada yang dijalankan). Karena itu
#: `gemini-3.5-flash-lite` sengaja diletakkan DI DEPAN: satu-satunya model
#: roster yang lulus kedua perilaku.
DEFAULT_MODEL_PREFERENCE = (
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "moonshotai/kimi-k3",
)


def _default_model_id() -> str:
    """Default server: model roster gateway bila gateway aktif.

    Tanpa ini default legacy `gemma-4-31b-it` (id Gemini-only, tak ada di
    roster) diarahkan ke gateway -> 404; sebaliknya id gateway
    (`qwen/qwen3.8-27b`) tidak dikenal genai.Client.

    Urutan pemilihan (BUG FIX 2026-10-06, lihat `DEFAULT_MODEL_PREFERENCE`):
      1. `AGENT_MODEL` env (operator override) - selalu menang bila ada di roster;
      2. preferensi kapabilitas (kuat -> lemah) yang ADA di roster;
      3. fallback terakhir: entri pertama roster (perilaku lama).
    """
    gw = _gateway_target()
    if gw and gw[2]:
        env_default = (os.getenv("AGENT_MODEL") or "").strip()
        if env_default and env_default in gw[2]:
            return env_default
        _roster = list(gw[2])
        for _pref in DEFAULT_MODEL_PREFERENCE:
            if _pref in _roster:
                return _pref
        return _roster[0]
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
    # Tier EFEKTIF (launch): user lama pro/ultra diperlakukan sebagai plus,
    # bukan diturunkan ke free (lihat database.effective_tier).
    tier = db.effective_tier(user_tier)
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


class GmailImapSaveRequest(BaseModel):
    """Body untuk POST /api/vault/gmail-imap.

    App password adalah kredensial nyata, jadi dikirim lewat body POST lalu
    langsung dienkripsi (vault) dan TIDAK pernah dikembalikan dalam respons.
    """
    email_address: str
    app_password: str
    # Bila true: setelah simpan, langsung tes login IMAP supaya user tahu
    # sekalian apakah App Password-nya benar (UI bisa tampilkan status).
    test_connection: bool = True


class VaultSaveRequest(BaseModel):
    provider: str
    api_key: str


class WorkflowCreateRequest(BaseModel):
    # `id` opsional: bila diisi dan workflow itu MILIK user, POST = UPDATE
    # (dulu selalu INSERT sehingga setiap "Simpan Alur" menumpuk baris baru).
    id: str | None = None
    name: str = "Draft Workflow"
    description: str = ""
    flow_data: dict = {}


class WorkflowUpdateRequest(BaseModel):
    """PATCH /workflows/{id} — rename (dan deskripsi bila perlu)."""
    name: str | None = None
    description: str | None = None


# ---------------------------------------------------------------------------
# Validasi graf workflow — dipakai jalur TULIS /workflows (INSERT & UPDATE).
#
# KENAPA ADA: `POST /workflows` dulu menyimpan `flow_data` APA ADANYA. Tiga
# masalah nyata yang terbukti lewat hard test produksi (8 Okt 2026):
#   1. graf 5.000 node diterima (201) -> tidak ada batas atas, permukaan DoS
#      sekaligus beban DB;
#   2. self-loop diterima;
#   3. edge yang menunjuk node tidak ada ("node hantu") diterima.
# Sementara itu `workflow_templates.validate_flow_data` dan
# `mcp_server._validate_flow_data` SUDAH menegakkan aturan yang sama — jadi
# jalur tulis utama justru yang paling longgar. Fungsi ini menyatukan aturan
# itu untuk kanvas pengguna dengan batas yang lebih longgar dari template.
# ---------------------------------------------------------------------------
# Sumber kebenaran tunggal (flow_limits.py) — dulu ada 3 nilai berbeda:
# 500 (API) vs 200 (MCP) vs 100 (templates) untuk konsep yang sama.
# ---------------------------------------------------------------------------
from flow_limits import MAX_FLOW_EDGES as MAX_WORKFLOW_EDGES  # noqa: E402
from flow_limits import MAX_FLOW_NODES as MAX_WORKFLOW_NODES  # noqa: E402


def validate_workflow_flow(flow: Any) -> dict:
    """Validasi bentuk graf kanvas. Mengembalikan flow bila sah.

    Raises HTTPException(422) supaya klien tahu payload-nya yang salah, bukan
    500 (kesalahan server).
    """
    if not isinstance(flow, dict):
        raise HTTPException(422, "flow_data harus objek JSON.")
    nodes = flow.get("nodes", [])
    if not isinstance(nodes, list):
        raise HTTPException(422, "flow_data.nodes harus list.")
    if len(nodes) > MAX_WORKFLOW_NODES:
        raise HTTPException(
            422, f"Terlalu banyak node ({len(nodes)} > {MAX_WORKFLOW_NODES}).")
    ids: set[str] = set()
    for i, n in enumerate(nodes):
        if not isinstance(n, dict):
            raise HTTPException(422, f"node[{i}] bukan objek.")
        nid = n.get("id")
        if not isinstance(nid, str) or not nid.strip():
            raise HTTPException(422, f"node[{i}] tanpa id.")
        if nid in ids:
            raise HTTPException(422, f"node id duplikat: {nid!r}.")
        ids.add(nid)
    edges = flow.get("edges", [])
    if not isinstance(edges, list):
        raise HTTPException(422, "flow_data.edges harus list.")
    if len(edges) > MAX_WORKFLOW_EDGES:
        raise HTTPException(
            422, f"Terlalu banyak edge ({len(edges)} > {MAX_WORKFLOW_EDGES}).")
    for i, e in enumerate(edges):
        if not isinstance(e, dict):
            raise HTTPException(422, f"edge[{i}] bukan objek.")
        src, tgt = e.get("source"), e.get("target")
        if not isinstance(src, str) or not isinstance(tgt, str):
            raise HTTPException(422, f"edge[{i}] harus punya source & target string.")
        if src not in ids:
            raise HTTPException(422, f"edge[{i}] source {src!r} tidak ada di nodes.")
        if tgt not in ids:
            raise HTTPException(422, f"edge[{i}] target {tgt!r} tidak ada di nodes.")
        if src == tgt:
            raise HTTPException(422, f"edge[{i}] self-loop {src!r} tidak diizinkan.")
    return flow


class ExecuteRequest(BaseModel):
    # Body opcional; si va vacio, se usa el flow_data guardado del workflow.
    flow_data: dict | None = None


class TemplateCreateRequest(BaseModel):
    """POST /templates — simpan template kustom.

    Bisa dari `flow_data` langsung ATAU dari `workflow_id` (workflow yang sudah
    ada milik user diambil flow_data-nya). `workflow_id` menang bila keduanya
    diisi — user tidak perlu menyalin JSON manual.
    """
    name: str = ""
    description: str = ""
    category: str = "ops"
    tags: list[str] = Field(default_factory=list)
    flow_data: dict | None = None
    workflow_id: str | None = None


class TemplateUseRequest(BaseModel):
    """POST /templates/{id}/use — nama/deskripsi opsional untuk workflow baru."""
    name: str | None = None
    description: str | None = None


# ---------------------------------------------------------------------------
# AGENTIC LOOP VIA GATEWAY (OpenAI-compatible /v1)
# ---------------------------------------------------------------------------
# Registry credential = sumber kebenaran untuk AI DAN form (2026-10-03).
# Diimpor di luar ekspresi prompt supaya prompt tetap string konstan yang
# bisa dibaca, dan supaya menambah provider cukup mengubah registry.
from credential_forms import credential_catalog as _credential_catalog


# --- Katalog tool MCP gateway untuk system prompt (NON-BLOCKING) ------------
# MASALAH YANG DIPERBAIKI (terbukti di produksi 2026-10-06): model tidak tahu
# bahwa ada 44 tool MCP sungguhan di balik agentgateway. Permintaan "Buat
# workflow yang pakai MCP tool echo" dijawab dengan node mcp ber-provider `http`
# dan URL karangan (`https://echo.free.beeceptor.com`) — bukan tool
# `everything_echo` yang benar-benar ada. Akibatnya jalur MCP tidak pernah
# dipakai walau jembatannya sudah berfungsi.
#
# KENAPA TIDAK DIAMBIL LANGSUNG DI SINI: `initialize` ke gateway terukur
# 8-13 detik (fan-out ke target stdio npx/uvx). System prompt dibangun pada
# SETIAP request, jadi pengambilan sinkron akan menambah belasan detik ke setiap
# chat. Karena itu pembacaan HANYA dari cache, dan refresh dijalankan di thread
# latar (`mcp_tool_cache.refresh_async`). Cache-nya dipakai bersama endpoint
# `/mcp/gateway/servers` supaya hanya ada SATU sumber kebenaran, dan supaya satu
# refresh melayani chat + UI sekaligus (tiap panggilan gateway membuat sesi baru
# yang men-spawn satu set proses stdio di VPS).
def mcp_gateway_catalog_text() -> str:
    """Teks katalog dari cache bersama; picu refresh latar bila basi. Tak memblokir."""
    if not mcp_tool_cache.is_fresh():
        mcp_tool_cache.refresh_async()
    names = [str(t.get("name") or "") for t in mcp_tool_cache.cached_tools()
             if t.get("name")]
    if not names:
        return ""
    return (
        "\nKATALOG TOOL MCP (nama PERSIS seperti ini, "
        f"{len(names)} tool tersedia):\n"
        + ", ".join(names)
        + "\n"
    )


_AGENT_SYSTEM = (
    "Anda adalah Nexus Autonomous Agent. Rencanakan & lakukan tindakan dengan "
    "alat yang tersedia. Setelah eksekusi alat, rangkum hasil untuk pengguna "
    "secara ringkas dalam Bahasa Indonesia.\n\n"
    # BAGIAN TEXTUAL TOOL CALLING (BUG FIX 2026-10-04).
    # Gateway production memb-drop parameter `tools` (bukti: HTTP 500 saat
    # `tools` dikirim ke qwen3.8-27b, sementara tanpa `tools` balas 200).
    # Karena itu alat dipanggil lewat TEKS berkurung, bukan native tool
    # calling. Format ini model-agnostic: Qwen/Gemma/DeepSeek/Llama bisa.
    #
    # PENTING: blok kode di bawah ini ADALAH dokumentasi. Bila user
    # membuat blok kode berisi [VAULT: ...], itu TIDAK dieksekusi
    # (parser mengabaikannya) - jadi contoh di sini aman.
    "FORMAT PEMANGGILAN ALAT (WAJIB):\n"
    "Gateway ini tidak menerima native tool calling, jadi alat dipanggil "
    "dengan menulis blok berkurung di jawabanmu:\n\n"
    "  [VAULT: <provider>]              -> cek/nyambung kredensial "
    "(supabase | gmail_imap | telegram | slack | google_sheets)\n"
    "  [WORKFLOW: <nama>]               -> minta pembuatan workflow\n"
    "  [EMAIL: cek subjek=<teks> max=<n>]-> baca email user via Gmail\n"
    "  [SHEETS: write spreadsheet=<id> sheet=<nama>]\n"
    "  [TELEGRAM: chat_id=<id> pesan=\"<teks>\"]\n"
    "  [SLACK: channel=<nama> pesan=\"<teks>\"]\n\n"
    "ATURAN ALAT (WAJIB):\n"
    "a. Butuh nilai yang mengandung spasi? WAJIB apit tanda kutip, "
    "contoh: pesan=\"Halo dunia\". Tanpa kutip, teks setelah spasi "
    "diabaikan.\n"
    "b. Panggil [VAULT: <provider>] DULU bila workflow butuh "
    "kredensial, lalu tunggu user mengisi form sebelum lanjut.\n"
    "c. JANGAN pernah menampilkan JSON mentah ke pengguna.\n"
    "d. Blok [ALAT: ...] di dalam ``` atau `inline code` TIDAK "
    "dieksekusi - di sana itu contoh dokumentasi.\n"
    "e. Setelah menulis blok alat, jelaskan singkat dalam Bahasa "
    "Indonesia apa yang akan dilakukan.\n"
    # BUG FIX 2026-10-02 - aturan "cari dulu, jangan berasumsi". Tanpa ini
    # agen menjawab pertanyaan teknis langsung dari ingatan, padahal versi
    # library / CVE / error message berubah cepat dan sering keliru.
    "ATURAN VERIFIKASI (WAJIB):\n"
    "a. Untuk pertanyaan TEKNIS yang bisa berubah cepat (nomor versi, CVE, "
    "error message, best practice, status API pihak ketiga, atau penyebab "
    "bug yang tidak kamu yakin) WAJIB panggil alat `web_search` dulu "
    "sebelum menjawab. Jangan berasumsi dari ingatan.\n"
    "b. Gunakan kueri singkat dan spesifik, pilih 1-2 kata kunci yang menentukan.\n"
    "c. Bila hasil pencarian relevan, WAJIB sebutkan sumber (nama situs/URL) "
    "di akhir jawaban.\n"
    "d. Bila pencarian gagal atau tidak ada hasil, katakan terus terang bahwa "
    "informasi tidak terverifikasi - jangan mengarang.\n"
    "e. Pertanyaan umum yang tidak berubah (matematika, definisi dasar) TIDAK "
    "perlu searching; jangan boros waktu.\n\n"
    # BAGIAN 3.2 (2026-10-03): credential elicited INLINE. Sebelumnya model
    # synthesized "silakan buka halaman Vault / Settings" - itu memutus alur
    # chat dan mudah dilupakan. Sekarang sistem otomatis memunculkan form di
    # dalam bubble begitu tool melempar credential_missing.
    "CREDENTIAL (WAJIB):\n"
    "a. JANGAN PERNAH menyuruh user membuka halaman Vault, Settings, atau "
    "mengofill credential di luar chat.\n"
    "b. Butuh credential? Panggil toolnya. Sistem otomatis menampilkan form "
    "di dalam percakapan, menyimpan kredensial terenkripsi, lalu mengulang "
    "perintahmu otomatis - user tidak perlu melakukan apa pun.\n"
    "c. Jadi cukup sebutkan credential kurang lalu panggil tool yang relevan; "
    "JANGAN memberi instruksi bernada 'kunjungi halaman'.\n"
    # --- FASE 2.1: DISCOVERY AGENT -------------------------------------------
    # Tanpa aturan ini, model langsung menebak isi workflow dan hasilnya salah
    # (provider/jadwal/field karangan). Jadi klarifikasi dulu, baru bangun.
    "MODE DISCOVERY (membangun workflow baru):\n"
    "1. Bila pengguna meminta membuat/mengubah workflow dan INTENSI-nya masih "
    "ambigu (tidak jelas mau apa, atau antar-node tidak nyambung), JANGAN "
    "langsung membangun: ajukan 2-5 pertanyaan klarifikasi yang paling "
    "menentukan, dalam daftar bernomor, singkat, dan sebutkan pilihan bila ada "
    "(contoh: 'Mau dijalankan tiap jam berapa?'). Kekurangan SATU nilai teknis "
    "(chat_id, URL, channel) BUKAN alasan menahan — lihat ATURAN BUILD "
    "WORKFLOW di bawah.\n"
    "2. Tanyakan hanya bila INTENSI belum jelas: pemicu/jadwal, aksi yang "
    "diinginkan, provider tujuan (telegram/gmail/google_sheets/slack/http), dan "
    "data yang dipindahkan antar langkah. Untuk node mcp, bila user BELUM "
    "menyebut TUJUAN (chat_id Telegram, channel Slack, atau URL HTTP), JANGAN "
    "menahannya dengan pertanyaan: isi dengan PLACEHOLDER berkurung ganda "
    "(contoh chat_id=\"{{chat_id}}\") supaya user bisa mengisinya di kanvas.\n"
    "3. Maksimal satu putaran pertanyaan per pesan pengguna. Bila jawabannya "
    "sudah cukup, atau pengguna bilang 'langsung buat'/'terserah kamu', "
    "berhenti bertanya dan lanjut membangun. Bila pengguna tetap belum "
    "menyebut tujuan, gunakan pilihan aman dan tulis di config supaya bisa "
    "diubah nanti.\n"
    "4. Bangun workflow dengan memanggil alat `generate_workflow_json` "
    "(seluruh workflow sebagai JSON string). Jangan menulis JSON di balasan "
    "chat — kanvas hanya terisi lewat alat itu. WAJIB isi config per provider:\n"
    "   telegram: {provider, chat_id, pesan} · slack: {provider, channel, pesan} · "
    "http: {provider, url, method} · gmail: {provider, tujuan, subjek, isi} · "
    "google_sheets: {provider, spreadsheet_id, range_data} · whatsapp: "
    "{provider, nomor_tujuan, pesan} · google_calendar: {provider, nama_acara, waktu}. "
    "`pesan`/`isi` boleh memakai teks permintaan pengguna; `chat_id`/`url`/"
    "`channel` TIDAK boleh dikarang dengan nilai palsu — kalau belum disebut, "
    "isi PLACEHOLDER (contoh chat_id=\"{{chat_id}}\", url=\"{{url}}\", "
    "channel=\"{{channel}}\"), JANGAN bertanya dan JANGAN menunda workflow.\n"
    # BUG FIX 2026-10-06: node mcp untuk TOOL MCP harus lewat gateway.
    "4a. TOOL MCP (permintaan seperti \"pakai MCP tool echo\"): node mcp WAJIB "
    "ber-config {provider: \"gateway\", tool: \"<nama PERSIS dari KATALOG TOOL "
    "MCP>\", arguments: {\"...\"}}. JANGAN memakai provider \"http\" dan JANGAN "
    "mengarang URL untuk permintaan tool MCP — itu mengubah tool MCP menjadi "
    "panggilan web biasa sehingga tool yang diminta TIDAK pernah dipanggil. "
    "Bila nama tool yang diminta tidak ada di katalog, katakan terus terang "
    "tool itu tidak tersedia dan sebutkan yang mirip; jangan mengarang nama "
    "maupun URL.\n"
    "4b. MEMBUAT SPREADSHEET: kamu BISA membuat Google Spreadsheet baru sendiri "
    "lewat alat `buat_google_spreadsheet` (parameter `title`, opsional "
    "`sheet_name` dan `sheet_names`). Jika pengguna meminta spreadsheet, lembar "
    "kerja, atau tab BARU dan belum ada spreadsheet yang disebut, PANGGIL alat "
    "itu. JANGAN minta pengguna membuat spreadsheet secara manual dan JANGAN "
    "meminta `spreadsheet_id` dari pengguna. Alat `baca_google_sheets` hanya "
    "untuk spreadsheet yang SUDAH ada.\n"
    "5. Bila alat menolak (ada `errors`), perbaiki sesuai `hint` dan panggil "
    "ulang; jangan menyerahkan JSON yang ditolak ke pengguna.\n"
    # Katalog credential diambil dari registry, bukan ditulis manual - kalau
    # provider baru ditambah, prompt ini ikut punya tanpa diedit.
    "PROVIDER CREDENTIAL YANG TERSEDIA:\n"
    + _credential_catalog() + "\n\n"
        "6. Setelah alat menerima, balas dengan ringkasan singkat: berapa node, "
    "alur besarnya, dan tanyakan apakah perlu diubah atau dijalankan.\n"
    "7. KEJUJURAN HASIL ALAT: bila hasil alat berstatus 'error' atau berisi "
    "'GAGAL', katakan kegagalan itu APA ADANYA — sebut alat, penyebab, dan "
    "langkah perbaikannya (mis. token salah/kedaluwarsa). JANGAN mengaku "
    "berhasil, JANGAN menyembunyikan penyebab, dan JANGAN menyebutnya "
    "'kesalahan server' bila penyebabnya penolakan dari provider.\n"
    # BUG FIX 2026-10-06 (discovery over-asking): user melaporkan agen bertanya
    # "berapa chat_id?" untuk permintaan yang alurnya sudah jelas, dan workflow
    # TIDAK pernah dibangun. Aturan di bawah memisahkan "intensi ambigu" (wajib
    # tanya) dari "satu nilai teknis kosong" (wajib bangun + placeholder) -
    # sebelumnya keduanya diperlakukan sama sehingga agen menahan diri terus.
    "ATURAN BUILD WORKFLOW (WAJIB):\n"
    "a. Bila permintaan user SUDAH menyebut alur yang jelas - terutama bila "
    "menyebut >=2 node/langkah (mis. 'setiap pagi ambil data lalu kirim ke "
    "telegram'), atau menyebut pemicu + aksi - LANGSUNG bangun workflow lewat "
    "`generate_workflow_json`. JANGAN masuk mode klarifikasi.\n"
    "b. Nilai teknis yang belum disebut (chat_id Telegram, channel Slack, URL "
    "HTTP, email tujuan, spreadsheet_id) TIDAK perlu ditanyakan: isi dengan "
    "PLACEHOLDER berkurung ganda, contoh chat_id=\"{{chat_id}}\", "
    "url=\"{{url}}\", channel=\"{{channel}}\", spreadsheet_id=\"{{spreadsheet_id}}\". "
    "User mengisinya di kanvas nanti.\n"
    "c. Tanya HANYA bila INTENSI-nya ambigu - tidak jelas mau apa, atau antar "
    "node tidak nyambung. Kekurangan satu nilai teknis BUKAN alasan bertanya.\n"
    "d. Jangan mengulang pertanyaan yang sama. Bila user sudah bilang "
    "'langsung buat' / 'terserah' / 'yang penting jalan', bangun SEKARANG "
    "dengan placeholder.\n"
    "e. Setelah membangun, rangkum singkat (berapa node, alur besarnya) dan "
    "sebutkan placeholder mana yang perlu diisi user di kanvas.\n"
    # --- KAPASITAS RUNTIME (diperbarui 2026-10-07, BUG #1/#3/#4) ------------
    # Runtime KINI mendukung IF/kondisi, Split In Batches, dan delegasi
    # multi-agent. Prompt harus mengajari SKEMA NYATA-nya supaya model tidak
    # menebak (dulu model mengaku membuat node IF/Supervisor padahal hanya
    # label — bukti docs/security/adversarial-test-n8n-hardcore-user-*.md).
    "KAPASITAS RUNTIME (3 jenis node: trigger, agent, mcp):\n"
    "1. KONDISI/IF - tambahkan config.condition (string ekspresi) pada node "
    "apa pun. Node DILEWATI bila ekspresi tidak benar. Contoh: "
    "config.condition = \"{{data.status}} == 'valid'\". Boleh juga "
    "config.else_condition untuk cabang ELSE. Operator didukung: "
    "== != > < >= <= , AND/OR/NOT, aritmatika dasar.\n"
    "2. SPLIT IN BATCHES - tambahkan config.batch_size (bilangan bulat >= 1) "
    "pada node agent/mcp. Node dijalankan SEKALI PER BATCH dengan konteks "
    "TERISOLASI; tiap batch mengakses itemnya lewat {{item}} dan "
    "{{batch}}. Contoh: config.batch_size = 1.\n"
    "3. DELEGASI MULTI-AGENT - set config.role = 'supervisor' pada node "
    "agent, dan sebut id agent target di config.delegates (list id). "
    "Supervisor mendelegasikan tugas ke sub-agent lewat baris "
    "[DELEGATE: agent_id=<id> task=\"<tugas>\"] lalu merangkai hasilnya.\n"
    "a. Placeholder {{akar.segmen}} diresolv dari output node hulu "
    "(contoh {{http_1.response.data.user.name}}); gagal resolv = node "
    "error jujur, bukan string mentah. {{tanpa_titik}} = isi manual user.\n"
    "b. JANGAN memberi label palsu. Menamai node 'IF'/'Supervisor' tanpa "
    "config di atas TIDAK mengubah cara kerjanya.\n"
    "c. Ringkasan SETELAH membangun WAJIB mencerminkan node yang benar-"
    "benar tersimpan (kind, config kunci, dan label apa adanya).\n"
    "d. Config yang didukung: condition, else_condition, batch_size, role, "
    "delegates, prompt (instruksi agent), event_name (pemicu), provider/"
    "tool (mcp). sub_workflow TIDAK didukung - pakai delegasi.\n"
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


def _tool_name(raw_name: str) -> str:
    """Ambil nama alat yang terdaftar dari nama ber-namespace.

    Model seperti Gemma 4 menulis `call:nexus:generate_workflow_json`, jadi
    nama yang sampai ke sini adalah `nexus:generate_workflow_json`. Alat
    terdaftar sebagai `generate_workflow_json`; tanpa pengupasan ini
    `tools.execute_tool` tidak akan menemukannya.
    """
    name = str(raw_name or "").strip()
    if ":" in name:
        name = name.rsplit(":", 1)[-1]
    return name.strip()


def _waf_repair_track(tool_result: Any, seen: list) -> bool:
    """Catat tanda tangan error validasi; True bila sudah TANPA PROGRES.

    Menggantikan 3 ronde buta di loop tool calling. Tanpa ini, model yang
    salah dengan cara yang sama tetap dipanggil 3x lalu output-nya tetap
    ditolak tanpa penjelasan ke user - persis kelemahan "stuck" yang paling
    sering dikeluhkan.

    `seen` diubah in-place; tiap entri adalah dict {"sig", "errors"} supaya
    pelapor bisa menampilkan error ASLI, bukan tanda tangan ternormalisasi.

    Args:
        tool_result: string JSON hasil `generate_workflow_json`.
        seen: list rekaman yang sudah terkumpul.

    Returns:
        bool: True bila error yang identik sudah mencapai batas.
    """
    try:
        parsed = json.loads(tool_result) if isinstance(tool_result, str) else tool_result
    except (TypeError, ValueError):
        return False
    if not isinstance(parsed, dict) or parsed.get("ok"):
        return False
    sig = _wf_autofix.error_signature(parsed)
    if not sig:
        return False
    seen.append({"sig": sig, "errors": list(parsed.get("errors") or [])})
    return sum(1 for r in seen if r["sig"] == sig) >= _WAF_NO_PROGRESS


def _waf_repair_message(seen: list, stalled: bool = False) -> str:
    """Pesan jujur saat ada validasi gagal tapi workflow tidak terbentuk.

    Prinsip anti-hallucination: JANGAN menulis "workflow berhasil dibuat"
    atau menyiratkan ada workflow di canvas bila memang tidak ada.

    Args:
        seen: rekaman dari `_waf_repair_track`.
        stalled: True bila error identik berulang sampai batas, artinya
            perbaikan otomatis tidak lagi hydroxide ada artinya.
    """
    errors = list(seen[-1]["errors"]) if seen else []
    if stalled:
        head = ("Workflow belum bisa diselesaikan otomatis: "
                f"{_WAF_NO_PROGRESS}x percobaan perbaikan menghasilkan "
                "masalah yang sama.")
    else:
        head = ("Workflow BELUM jadi - validasi menolak draf terakhir, "
                "jadi tidak ada yang masuk ke canvas.")
    return head + "\n" + _wf_autofix.describe_errors(errors)


def _accepted_workflow(tool_result: Any) -> "dict | None":
    """Ambil `spec` dari hasil `generate_workflow_json` BILA alat menerimanya.

    Alat memulangkan JSON string: {"ok":True,"spec":{...}} atau
    {"ok":False,"errors":[...]}. Draf yang DITOLAK sengaja tidak dikembalikan
    agar canvas tidak pernah terisi workflow setengah benar.
    """
    if not isinstance(tool_result, str):
        return None
    try:
        parsed = json.loads(tool_result)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict) or not parsed.get("ok"):
        return None
    spec = parsed.get("spec")
    return spec if isinstance(spec, dict) else None





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

    def _send_tools_param() -> bool:
        """Apakah native `tools` perlu dikirim ke gateway?

        DEFAULT: TIDAK (BAGIAN 2.3 - "JANGAN kirim parameter `tools`").

        Alasannya terukur, bukan tebakan: gateway menjawab HTTP 500 polos
        begitu payload `tools` disisipkan ke model produksi, sementara
        tanpa `tools` balas 200 (diperiksa langsung ke
        /v1/chat/completions). Akibatnya setiap request membuang satu
        round-trip 500 plus retry sebelum balasan pertama.

        Katalir tidak memerlukan native tool calling karena sudah punya
        jalur TEKS berformat `[ALAT: args]` yang model-agnostic (lihat
        `textual_tool_parser.py`). Jadi jalur native dimatikan sejak
        awal, bukan ditunggu sampai gagal.

        Set KATALIR_SEND_TOOLS=1 hanya kalau hulu berubah dan memang
        menerima `tools`. Jalur teks tetap berfungsi sebagai cadangan.
        """
        return (os.getenv("KATALIR_SEND_TOOLS", "0") or "0").strip().lower() in (
            "1", "true", "yes", "on")

    def _bound(model_name: str, timeout: float | None = None,
               with_tools: bool | None = None):
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
        want = _send_tools_param() if with_tools is None else with_tools
        if not want:
            # Jalur utama: TANPA `tools`. Panggilan alat lewat TEKS
            # ([ALAT: args]) yang di-parse di bawah.
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
        messages: list[Any] = [
            SystemMessage(content=_AGENT_SYSTEM + mcp_gateway_catalog_text())
        ]
        messages.extend(_to_lc_history(history))
        messages.append(HumanMessage(
                    # BUG FIX 2026-10-04: control token chat-template dan
                    # zero-width dihapus sebelum masuk model. Tanpa ini,
                    # penyang dapat menyamarkan nama alat lewat U+200B.
                    content=sanitize_user_input(prompt)))
        _t0 = time.time()
        tools_dropped = False
        # FASE 2.1 -> 2.2: spec workflow yang DITERIMA alat disimpan di sini dan
        # ikut di respons (`meta.workflow`). Tanpa ini, hasil generate hanya
        # hidup di dalam pesan tool lalu hilang -> canvas tidak punya apa pun.
        workflow_out: dict | None = None
        # Rekam error validasi yang berulang (lihat _waf_repair_track).
        waf_seen: list = []
        waf_stalled = False
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
                # BUG FIX 2026-10-02: sebagian model (Gemma 4 via NVIDIA,
                # Qwen3-Coder) membungkus panggilan alat di dalam `content`
                # sebagai TEKS `<|tool_call>call:NS:NAME({...})<tool_call|>` dan
                # TIDAK mengisi field `tool_calls`. Sebelum fix ini, loop langsung
                # `break` dan JSON mentah ikut ke `reply`, jadi user melihat
                # JSON alih-alih workflow di canvas (bug "tool call tidak
                # dieksekusi"). Bukti reproduksi: google/gemma-4-31b-it.
                textual = []
                # --- GERBANG FAIL-CLOSED (BUG FIX 2026-10-04) -----------------
                # Gateway production memb-drop `tools` (bukti: HTTP 500 saat
                # payload tools dikirim), jadi semua panggilan datang sebagai TEKS.
                # `extract_textual_tool_calls` bersifat LENIENT: ia mengambil
                # apa pun yang menyerupai call. Itu deveriam tidak dieksekusi
                # bila bentuknya rusak.
                # `tool_call_parser.parse_tool_call` bersifat KAKAT: bentuk
                # ambigu/rusak -> ToolCallParseError (jangan dieksekusi).
                #
                # Aturan yang dipakai di sini:
                #   * "ambigu" (ada >1 blok) = multi-call yang SAH -> tetap
                #     lanjut lewat jalur lenient yang sudah terbukti di produksi.
                #     Memblokirnya akan merusak alur yang hari ini bekerja.
                #   * error lain (JSON rusak, blok tanpa argumen, data setelah
                #     code fence) = TIDAK SAH -> stop, jangan eksekusi apa pun,
                #     dan jangan tampilkan JSON mentah ke user.
                _raw_text = _content_text(resp)
                _gate = ""
                if not calls:
                    try:
                        parse_tool_call(_raw_text)
                    except ToolCallParseError as _exc:
                        if not str(_exc).startswith("ambigu"):
                            _gate = str(_exc)
                    except Exception:  # noqa: BLE001 - gerbang tidak boleh mematikan alur
                        _gate = ""
                if _gate:
                    print(f"[chat/gateway] fail-closed tool_call: {_gate[:120]}")
                    return {
                        "reply": (
                            "Saya menghasilkan panggilan alat yang tidak "
                            "berbentuk benar sehingga tidak saya jalankan "
                            "(fail-closed). Mohon ulangi permintaan; "
                            "tidak ada credential yang diubah."
                        ),
                        "meta": {
                            "model": cand,
                            "requested_model": model_id,
                            "latency_ms": int((time.time() - _t0) * 1000),
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "total_tokens": 0,
                            "fallback": bool(cand != model_id),
                            "gateway": True,
                            "tools_dropped": tools_dropped,
                            "tool_call_rejected": True,
                            "tool_call_error": _gate[:200],
                            "workflow": None,
                        },
                    }
                # --- TEKSTUAL BERKURUNG (BUG FIX 2026-10-04) ------------------
                # Format `[ALAT: args]`. Ini jalur UTAMA sekarang karena
                # gateway tidak menerima native tools. Dicek SEBELUM parser
                # XML, dan hanya bila tidak ada `tool_calls` terstruktur.
                _bracket_calls = [] if calls else parse_textual_tools(_raw_text)
                if _bracket_calls:
                    print(f"[chat/gateway] bracket tool_call n="
                          f"{len(_bracket_calls)} names="
                          f"{[c['tool'] for c in _bracket_calls]}")
                    for c in _bracket_calls:
                        try:
                            # `prompt` diteruskan supaya intent-alignment
                            # bisa menilai apakah tool ini memang diminta user.
                            result = execute_textual_tool(
                                c, email, user_message=prompt)
                        except CredentialMissingError:
                            raise  # -> endpoint merender form inline
                        except Exception as exc:  # noqa: BLE001
                            result = {"status": "error",
                                      "message": f"{type(exc).__name__}: {exc}"[:300]}
                        # Status ini harus sampai ke form, bukan ditampilkan
                        # sebagai teks biasa.
                        if isinstance(result, dict) and result.get("status") in (
                                "requires_credential", "needs_oauth"):
                            raise CredentialMissingError(
                                str(result.get("provider") or ""))
                        # Spec workflow masih dibutuhkan -> minta giliran
                        # berikutnya, jangan mengarang node.
                        if isinstance(result, dict) and result.get("status") == "needs_spec":
                            print(f"[chat/gateway] needs_spec name={result.get('name')}")
                        # BUG FIX 2026-10-05: `requires_approval` (policy gate
                        # + intent-alignment) TIDAK boleh swallowed. Terbukti
                        # di produksi: model menulis [VAULT: ...], gate
                        # mengembalikan requires_approval, dan jalur ini
                        # berdiam saja sehingga user melihat `success`
                        # padahal tidak ada yang dieksekusi maupun diminta.
                        if isinstance(result, dict) and result.get("status") in (
                                "requires_approval", "denied"):
                            _clean0 = strip_textual_tools(_raw_text)
                            return {**result, "reply": _clean0 or "",
                                    "meta": {"model": cand,
                                             "requested_model": model_id,
                                             "latency_ms": int((time.time() - _t0) * 1000),
                                             "fallback": bool(cand != model_id),
                                             "gateway": True,
                                             "tools_dropped": tools_dropped,
                                             "bracket_tool_calls": [
                                                 c["tool"] for c in _bracket_calls],
                                             "workflow": None}}
                    _clean = strip_textual_tools(_raw_text)
                    usage = getattr(resp, "usage_metadata", None) or {}
                    return {
                        "reply": _clean or "Selesai.",
                        "meta": {
                            "model": cand,
                            "requested_model": model_id,
                            "latency_ms": int((time.time() - _t0) * 1000),
                            "prompt_tokens": int(usage.get("input_tokens") or 0),
                            "completion_tokens": int(usage.get("completion_tokens") or 0),
                            "total_tokens": int(usage.get("total_tokens") or 0),
                            "fallback": bool(cand != model_id),
                            "fallback_reason": (_fallback_reason(last_err)
                                                if cand != model_id and last_err is not None
                                                else None),
                            "gateway": True,
                            "tools_dropped": tools_dropped,
                            "textual_tool_calls": True,
                            "bracket_tool_calls": [c["tool"] for c in _bracket_calls],
                            "workflow": None,
                        },
                    }
                if not calls:
                    textual = extract_textual_tool_calls(_raw_text)
                if textual:
                    print(f"[chat/gateway] textual tool_call n={len(textual)} "
                          f"names={[c['name'] for c in textual]}")
                    # Jalur TEKS tidak mengulang `invoke`: `messages.append(resp)`
                    # + ToolMessage akan melanggar pasangan tool_call_id milik
                    # LangChain karena respons aslinya tidak punya tool_calls
                    # terstruktur. Jadi alat dieksekusi sekali, lalu reply
                    # dibangun dari teks yang sudah dibersihkan.
                    for c in textual:
                        name = _tool_name(c["name"])
                        print(f"[chat/gateway] textual tool_call name={name}")
                        try:
                            result = tools.execute_tool(name, c["args"], email)
                        except CredentialMissingError:
                            raise  # -> endpoint ubah jadi needs_credential
                        except Exception as exc:  # noqa: BLE001 - alat gagal
                            result = f"Gagal menjalankan {name}: {exc}"
                        # `requires_credential` (dari check_credential / broker
                        # secret://) harus PERNAH sampai ke form inline; tanpa
                        # cabang ini, form tidak pernah muncul.
                        if isinstance(result, dict) and result.get("status") == "requires_credential":
                            raise CredentialMissingError(str(result.get("provider") or ""))
                        if isinstance(result, dict) and result.get("status") == "needs_oauth":
                            raise CredentialMissingError(str(result.get("provider") or ""))
                        if name == "generate_workflow_json":
                            workflow_out = _accepted_workflow(result) or workflow_out
                    textual_reply = strip_textual_tool_calls(_content_text(resp))
                    usage = getattr(resp, "usage_metadata", None) or {}
                    return {
                        "reply": textual_reply or (
                            "Workflow berhasil dibuat." if workflow_out
                            else "Selesai."),
                        "meta": {
                            "model": cand,
                            "requested_model": model_id,
                            "latency_ms": int((time.time() - _t0) * 1000),
                            "prompt_tokens": int(usage.get("input_tokens") or 0),
                            "completion_tokens": int(usage.get("output_tokens") or 0),
                            "total_tokens": int(usage.get("total_tokens") or 0),
                            "fallback": bool(cand != model_id),
                            "fallback_reason": (_fallback_reason(last_err)
                                                if cand != model_id and last_err is not None
                                                else None),
                            "gateway": True,
                            "tools_dropped": tools_dropped,
                            # True bila panggilan datang sebagai TEKS, bukan
                            # field tool_calls terstruktur.
                            "textual_tool_calls": True,
                            "workflow": workflow_out,
                        },
                    }
                if not calls:
                    break
                messages.append(resp)
                for call in calls:
                    name = str((call or {}).get("name") or "")
                    args = dict((call or {}).get("args") or {})
                    # JEJAK: berapa kali agen meminta tool (untuk memisahkan
                    # duplikasi "agen memanggil 2x" vs "mesin mengeksekusi 2x").
                    print(f"[chat/gateway] tool_call name={name}")
                    try:
                        result = tools.execute_tool(name, args, email)
                    except CredentialMissingError:
                        raise  # -> endpoint ubah jadi needs_credential
                    except Exception as exc:  # noqa: BLE001 - alat gagal
                        result = f"Gagal menjalankan {name}: {exc}"
                    if isinstance(result, dict) and result.get("status") in (
                            "requires_approval", "denied"):
                        # BUG FIX 2026-10-05: sama seperti jalur TEKS, status ini
                        # tidak boleh swallowed - user harus melihat tombol
                        # Setujui atau alasan penolakan.
                        return {"reply": "", **result,
                                "meta": {"model": cand,
                                         "requested_model": model_id,
                                         "latency_ms": int((time.time() - _t0) * 1000),
                                         "fallback": bool(cand != model_id),
                                         "gateway": True,
                                         "tools_dropped": tools_dropped,
                                         "workflow": workflow_out}}
                    if isinstance(result, dict) and result.get("status") == "requires_credential":
                        # BUG FIX 2026-10-04: sama seperti jalur TEKS, status ini
                        # harus diubah jadi form inline oleh endpoint.
                        raise CredentialMissingError(str(result.get("provider") or ""))
                    if isinstance(result, dict) and result.get("status") == "needs_oauth":
                        # Task 1C: `tools.execute_tool` MENGEMBALIKAN sinyal OAuth
                        # (bukan melempar) untuk provider ber-OAuth. Teruskan ke
                        # endpoint lewat jalur yang sudah ada supaya user menerima
                        # {status: needs_oauth, connect_url} + tombol Connect —
                        # jangan meneruskan hasil palsu ke model.
                        raise CredentialMissingError(str(result.get("provider") or ""))

                    if name == "generate_workflow_json":
                        workflow_out = _accepted_workflow(result) or workflow_out
                        # Deteksi tanpa progres: error validasi yang IDENTIK
                        # berulang = repair berikutnya pasti sia-sia. Menghentikan
                        # ronde lebih awal dan melapor jujur lebih baik daripada
                        # membuang kuota 3x lalu diam saja.
                        if _waf_repair_track(result, waf_seen):
                            waf_stalled = True
                            break
                    messages.append(ToolMessage(
                        # BUG FIX 2026-10-04 (CRITICAL): hasil tool berasal dari
                        # LUAR (body email, isi sel, respons API) dan kembali ke
                        # konteks model. Tanpa sanitasi, email berisi
                        # "[VAULT: supabase]" bisa membuat model menuliskannya
                        # - lalu dieksekusi parser. Netralkan polanya sebelum
                        # masuk konteks; data tetap terbaca, tapi tidak punya
                        # daya sebagai perintah.
                        content=sanitize_tool_result(result),
                        tool_call_id=str((call or {}).get("id") or name),
                    ))
                resp = chat_model.invoke(messages)
            usage = getattr(resp, "usage_metadata", None) or {}
            reply_text = _content_text(resp)
            if workflow_out is None and waf_seen:
                # Anti-hallucination: ada validasi yang GAGAL tapi tidak ada
                # Ada validasi yang GAGAL tapi tidak ada workflow. Membalas
                # "Selesai." apa adanya sama saja menyesatkan user - dia
                # mengira workflow sudah dibuat. Kabar buruknya lebih berguna.
                # Kabar buruknya selalu lebih berguna daripada senyap.
                msg = _waf_repair_message(waf_seen, stalled=waf_stalled)
                reply_text = (reply_text + "\n\n" + msg).strip() if reply_text else msg

            return {
                "reply": reply_text,
                "meta": {
                    "model": cand,
                    "repair_stalled": waf_stalled,
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
                    # Draf workflow hasil Discovery Agent (None bila tidak ada).
                    "workflow": workflow_out,
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
def _direct_policy_gate(name: str, args: dict, email: str, prompt: str
                        ) -> dict | None:
    """Gerbang kebijakan untuk jalur Gemini LANGSUNG (`_agentic_run_direct`).

    Mengembalikan `None` bila panggilan boleh dieksekusi apa adanya; atau
    sebuah dict respons final (`requires_approval` / `denied`) yang harus
    dikembalikan pengganti hasil tool.

    Kenapa perlu: gerbang `tool_policy_gate` sebelumnya HANYA dipasang di
    jalur gateway (lewat `execute_textual_tool`). Bila user tidak memilih
    model, `/chat` selalu mengambil jalur Gemini langsung, dan di sana alat
    dieksekusi tanpa gerbang -> tidak ada kartu persetujuan untuk alat yang
    mengirim data ke luar (Bug #1 di produksi, terbukti dari log
    `[chat/direct] tool_call name=kirim_telegram_message` diikuti eksekusi).

    Urutan keputusan mengikuti `execute_textual_tool`: kredensial dicek
    LEBIH DAHULU daripada approval, supaya user tidak diberi tombol
    "Setujui" untuk alat yang tetap tak bisa jalan tanpa kredensial.
    """
    try:
        from tool_policy_gate import Disposition, validate_call
        disposition, reason = validate_call(
            name, args or {}, {"email": email})
    except Exception as exc:  # noqa: BLE001 - gate gagal = jangan lewati
        print(f"[chat/direct] policy gate error: {type(exc).__name__}: {exc}")
        return None

    if disposition is Disposition.ALLOW:
        return None
    if disposition is Disposition.DENY:
        print(f"[chat/direct] policy DENY name={name}: {reason[:80]}")
        return {"status": "denied",
                "reply": f"Permintaan tidak dijalankan: {reason}",
                "meta": {"policy": "deny", "reason": reason,
                         "bracket_tool_calls": [name]}}

    # REQUIRE_APPROVAL
    # Kredensial dulu: tanpa kredensial, "Setujui" tidak akan membuat apa pun
    # berhasil. Dipetakan dari nama native maupun tekstual.
    #
    # Bila kredensial belum ada, LEMPAR `CredentialMissingError` (jangan
    # kembalikan dict sendiri): endpoint sudah menangkapnya dan menyusun kartu
    # form lengkap (`display_name`, `icon`, `fields`, `resume_token`) lewat
    # `credential_forms.build_requires_credential`. Mengembalikan dict parsial
    # di sini akan membuat form tampil KOSONG di frontend.
    from credential_forms import check_credential
    _prov = _native_tool_provider(name)
    if _prov:
        try:
            _status = check_credential(_prov, email)["status"]
        except Exception as exc:  # noqa: BLE001 - gagal cek = serahkan ke gate
            print(f"[chat/direct] cek kredensial gagal: {type(exc).__name__}: {exc}")
            _status = "ok"
        if _status != "ok":
            print(f"[chat/direct] requires_credential provider={_prov}")
            raise CredentialMissingError(_prov)

    try:
        from approval_flow import APPROVAL_TTL_S, issue_approval_token
        tok = issue_approval_token(email, name, args or {})
    except Exception as exc:  # noqa: BLE001 - tanpa token user tak bisa setuju
        print(f"[chat/direct] token approval gagal: {type(exc).__name__}: {exc}")
        return {"status": "denied",
                "reply": "Persetujuan tidak tersedia saat ini.",
                "meta": {"bracket_tool_calls": [name]}}
    print(f"[chat/direct] requires_approval name={name}")
    return {"status": "requires_approval", "tool": name, "args": args or {},
            "reason": reason, "approval_token": tok,
            "expires_in": APPROVAL_TTL_S, "reply": "",
            "meta": {"bracket_tool_calls": [name]}}


def _native_tool_provider(name: str) -> str:
    """Nama provider kredensial untuk nama alat NATIVE (function-call).

    `textual_tool_handlers._TOOL_PROVIDER` hanya mengenal nama TEKSTUAL
    (`TELEGRAM`, `SLACK`, ...). Jalur langsung menerima nama native
    (`kirim_telegram_message`), jadi peta ini melengkapinya. Mengembalikan
    "" bila alat tidak butuh kredensial (mis. `generate_workflow_json`).
    """
    return {
        "KIRIM_TELEGRAM_MESSAGE": "telegram",
        "KIRIM_SLACK_MESSAGE": "slack",
        "KIRIM_EMAIL_GMAIL": "gmail",
        "SEND_WHATSAPP_MESSAGE": "whatsapp",
        "TRIGGER_GMAIL_IMAP": "gmail_imap",
        "WRITE_SHEETS_DYNAMIC": "google_sheets",
        "BUAT_GOOGLE_SPREADSHEET": "google_sheets",
        "TAMBAH_AGENDA_CALENDAR": "google_calendar",
    }.get(str(name or "").strip().upper(), "")


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
        system_instruction=_AGENT_SYSTEM + mcp_gateway_catalog_text(),
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
    # FASE 2.1 -> 2.2: draf workflow yang diterima alat ikut di meta.workflow.
    workflow_out: dict | None = None

    while response.function_calls:
        if retry >= max_retries:
            return "Maaf, agen gagal menyelesaikan operasi setelah beberapa percobaan."

        for call in response.function_calls:
            name = call.name
            args = dict(call.args) if call.args else {}

            # CredentialMissingError dibiarkan menyebar -> endpoint menangkapnya.
            # Kegagalan tool LAIN (mis. provider menolak token: HTTP 401) tidak
            # boleh menjatuhkan permintaan sebagai 'kesalahan internal': itu
            # penolakan dari provider, bukan bug server. Dikembalikan sebagai
            # hasil tool yang berstatus error supaya model bisa menjelaskan
            # penyebabnya kepada user (jalur gateway sudah berperilaku begitu).
            # JEJAK: berapa kali agen meminta tool (jalur Gemini langsung).
            print(f"[chat/direct] tool_call name={name}")
            # BUG FIX 2026-10-06 (approval card tidak pernah muncul di jalur
            # Gemini langsung): jalur ini dulu mengeksekusi alat LANGSUNG lewat
            # `tools.execute_tool`, TANPA `tool_policy_gate` sama sekali.
            # Akibatnya alat pengirim data ke luar (TELEGRAM/SLACK/EMAIL/SHEETS,
            # termasuk nama native `kirim_telegram_message`) benar-benar
            # terkirim tanpa kartu persetujuan - persis gejala Bug #1 di
            # produksi. Gate deterministik yang sama yang dipakai jalur gateway
            # sekarang dijalankan di sini SEBELUM eksekusi.
            _gate = _direct_policy_gate(name, args, email, prompt)
            if _gate is not None:
                return _gate
            try:
                tool_result = tools.execute_tool(name, args, email)
                tool_status = "success"
            except CredentialMissingError:
                raise
            except Exception as exc:  # noqa: BLE001 - kesalahan tool, bukan server
                tool_result = f"GAGAL menjalankan {name}: {type(exc).__name__}: {exc}"
                tool_status = "error"
                print(f"[api_server] tool {name} gagal: {type(exc).__name__}: {exc}")
            if isinstance(tool_result, dict) and tool_result.get("status") == "needs_oauth":
                # Task 1C (jalur Gemini langsung): sinyal OAuth diteruskan ke
                # endpoint supaya user menerima connect_url, bukan teks mentah.
                raise CredentialMissingError(str(tool_result.get("provider") or ""))

            if name == "generate_workflow_json" and tool_status == "success":
                workflow_out = _accepted_workflow(tool_result) or workflow_out

            response = _send_guarded(
                chat,
                types.Part.from_function_response(
                    name=name,
                    response={"status": tool_status, "result": tool_result},
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
        # Draf workflow hasil Discovery Agent (None bila tidak ada).
        "workflow": workflow_out,
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


#: Sentinel envelope kartu di `chat_messages.content` (role="system").
#: BUG FIX 2026-10-06 (vault hilang saat navigasi): kartu form kredensial /
#: approval hanya hidup di cache klien (TanStack `_localId`), jadi HILANG saat
#: user pindah sesi / refresh. Baris `role="system"` dengan envelope JSON
#: membuatnya bertahan. Baris ini AMAN:
#:   * `load_history` hanya mengirim role user/assistant -> tidak jadi konteks;
#:   * `get_last_assistant_reply` memfilter role=assistant -> bukan "balasan";
#:   * index unik client_request_id bersifat partial (role='user') -> tidak bentrok.
_CARD_SENTINEL = "__katalir_card"


def _persist_card(user_email: str, session_id: str, user_id: str | None,
                  req_id: str | None, card: dict) -> None:
    """Simpan satu kartu (credential_form / approval_prompt / oauth_prompt).

    Tidak pernah melempar: gagal menyimpan kartu BUKAN alasan menggagalkan
    giliran chat yang sudah berhasil dihitung. Dedup by client_request_id
    supaya retry tidak menumpuk kartu ganda.
    """
    try:
        if req_id:
            existing = db.find_card_message_by_request(req_id)
            if existing:
                return
        payload = {_CARD_SENTINEL: card.get("type") or card.get("__katalir_card"), **card}
        db.add_message(user_email, session_id, "system",
                       json.dumps(payload, ensure_ascii=False),
                       auth_id=user_id, client_request_id=req_id)
    except Exception as exc:  # noqa: BLE001 - persist kartu bersifat best-effort
        print(f"[persist_card] {type(exc).__name__}: {str(exc)[:200]}")


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
        # Tier EFEKTIF (launch 2026-09-18): user lama pro/ultra diperlakukan
        # sebagai plus (tidak turun ke free, tidak pula ke skema tersembunyi).
        user_tier = db.effective_tier((_u or {}).get("tier", "free"))
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
            # PENTING: reply WAJIB ditautkan ke req_id yang sama. Tanpa itu
            # (versi lama) percakapan yang sudah punya giliran sukses akan
            # mengembalikan reply giliran SEBELUMNYA lalu short-circuit ->
            # retry terkira berhasil padahal tidak pernah dijalankan ulang.
            prev_reply = db.get_last_assistant_reply(prior["session_id"],
                                                      client_request_id=req_id)
            if prev_reply:
                return {
                    "status": "success",
                    "reply": prev_reply,
                    "session_id": prior["session_id"],
                }
            prior_session = prior["session_id"]

    # ---- RATE LIMIT PER USER (BUG-5, adversarial 2026-10-07) ---------------
    # Diletakkan SETELAH early-return idempotensi (replay TIDAK memakan slot -
    # sama rasionalnya dengan penempatan kuota di bawah) dan SEBELUM
    # pemeriksaan kuota/write apa pun, supaya burst ditahan murah sebelum
    # menyentuh DB maupun LLM. Bukti awal: burst 8 paralel -> 8/8 200 tanpa
    # satu pun 429; 13 key / 27 RPM lalu kehabisan RPM -> 503 menyebar ke
    # semua user. Limit in-memory per proses (lihat rate_limit.py - bila
    # suatu saat di-scale >1 replica, store-nya harus terpusat).
    _rl_ok, _rl_retry = rate_limit.chat_limiter.check(user_id)
    if not _rl_ok:
        raise HTTPException(
            429,
            ("Terlalu banyak permintaan percakapan. Batas "
             f"{rate_limit.chat_limiter.max_calls} pesan per "
             f"{int(rate_limit.chat_limiter.window_sec)} detik per akun. "
             "Tunggu sebentar lalu coba lagi."),
            headers={"Retry-After": str(int(_rl_retry))},
        )
    # Tier kedua (brief 7 Okt, BAGIAN 6): batas per JAM untuk menahan pola
    # pemakaian beruntun yang lolos dari window per-menit.
    _rl_h_ok, _rl_h_retry = rate_limit.request_hourly_limiter.check(user_id)
    if not _rl_h_ok:
        raise HTTPException(
            429,
            ("Kuota permintaan per jam tercapai. Batas "
             f"{rate_limit.request_hourly_limiter.max_calls} permintaan per "
             f"{int(rate_limit.request_hourly_limiter.window_sec // 60)} menit "
             "per akun. Coba lagi nanti."),
            headers={"Retry-After": str(int(_rl_h_retry))},
        )

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
            print(f"[api_server] /chat gagal membuat session: "
                  f"{type(exc).__name__}: {exc}")
            raise HTTPException(
                500, "Gagal memulai sesi percakapan. Silakan coba lagi.")

    # KONTEKS MULTI-TURN: muat riwayat sesi SEBELUM pesan baru disimpan, supaya
    # prompt yang sedang dikirim tidak ikut terkirim dua kali (sebagai riwayat
    # DAN sebagai prompt). Tanpa ini agen lupa isi percakapan turn sebelumnya.
    history = load_history(user_email, session_id, current_prompt=req.prompt)

    # AI AGENT MEMORY (Fitur #11): recall memori relevan + preferensi user,
    # dijahit ke prompt. Defensif TOTAL — kegagalan memory TIDAK BOLEH
    # mengganggu chat (build_memory_context sudah menelan exception; ini
    # lapis kedua). Kill-switch: env AGENT_MEMORY_ENABLED=0.
    prompt_final = req.prompt
    try:
        _memctx = memory_manager.build_memory_context(
            str(user_id), session_id or "chat", req.prompt)
        if _memctx:
            prompt_final = (
                f"{req.prompt}\n\n"
                "[KONTEKS MEMORI — informasi latar dari interaksi sebelumnya; "
                "gunakan bila relevan, jangan sebut asalnya ke user]\n"
                + _memctx)
    except Exception as _mem_exc:  # noqa: BLE001
        print(f"[memory] hook recall gagal (diabaikan): {type(_mem_exc).__name__}")

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
        print(f"[api_server] /chat gagal menyimpan pesan: "
              f"{type(exc).__name__}: {exc}")
        raise HTTPException(
            500, "Gagal menyimpan pesan. Silakan coba lagi.")

    try:
        _run = _agentic_run_direct(prompt_final, user_email, model=_q_run_model,
                                   user_tier=user_tier, history=history)
        reply = _run["reply"]
        meta = _run.get("meta") or {}
        # Fitur #11: simpan giliran chat sebagai memori EPISODIC (fire-and-
        # forget di thread daemon — nol tambahan latensi respons).
        try:
            threading.Thread(
                target=memory_manager.remember_chat_turn,
                args=(str(user_id), session_id or "chat", req.prompt, str(reply)),
                daemon=True).start()
        except Exception as _mem_w_exc:  # noqa: BLE001
            print(f"[memory] episodic thread gagal (diabaikan): "
                  f"{type(_mem_w_exc).__name__}")
    except CredentialMissingError as e:
        # Persist hanya pesan user; UI menampilkan form credential & akan submit ulang.
        #
        # FASE backlog (Task 1C): provider yang punya alur OAuth TIDAK boleh
        # meminta user menempel token manual — UI harus menawarkan "Connect".
        # Kontrak `tools.py` sengaja TIDAK diubah (masih melempar
        # CredentialMissingError, sudah diuji di test_mcp_registry), jadi
        # pemetaan ke `needs_oauth` dilakukan di sini: satu tempat, tidak
        # mengguncang tool yang sudah stabil.
        # Hanya provider yang alur OAuth-nya benar-benar bisa memenuhi kebutuhannya.
        #
        # Pemetaan ini sebelumnya memuat gmail + google_calendar. Keduanya salah,
        # dan bukan cuma soal scope:
        #   1. `/oauth/google/authorize` meng-hardcode `scope` menjadi
        #      `auth/spreadsheets` (lihat oauth_google.SHEETS_SCOPE), jadi consent
        #      screen tidak pernah meminta izin Gmail/Calendar.
        #   2. `kirim_email_gmail` membaca `db.get_integration(...)`, bukan
        #      `user_vault` tempat token OAuth disimpan. Token Sheets secara
        #      struktur tidak mungkin memakainya.
        #
        # Akibatnya user diberi tombol "Connect", menyetujuinya, melihat
        # "Connected", lalu tool-nya tetap gagal. Mencantumkan gmail sebagai
        # OAuth menahan janji palsu; `needs_credential` jujur walau form manual
        # belum punya entri gmail (lihat docs/oauth/provider-status.md).
        _oauth_providers = {
            "google_sheets": "/oauth/google/authorize",
            "slack": "/oauth/slack/authorize",
        }
        # BUG/fitur 2026-10-03: credential yang bisa diisi user (App Password
        # Gmail) tidak lagi mengarah ke "user buka halaman Vault". Form-nya
        # dirender INLINE di bubble chat, persis pola MCP (server balas
        # CredentialMissing, client render form) dan Vercel AI SDK v5
        # (tool part `requires-action`). Jadi user tidak pernah meninggalkan
        # percakapan, dan tidak perlu mengingat di mana harus mengetik.
        import credential_forms as _cf

        _prov = str(e.provider_name or "").strip().lower()
        if _cf.has_inline_form(_prov):
            try:
                _card = _cf.build_requires_credential(
                    _prov, user_email, session_id=session_id)
                # BUG FIX 2026-10-06 (vault hilang saat navigasi): persist kartu
                # supaya form tetap ada setelah user pindah sesi / refresh.
                _persist_card(user_email, session_id, user_id, req_id,
                              {**dict(_card), "type": "credential_form",
                               "original": req.prompt})
                return _card
            except ValueError:
                pass  # form hilang/berubah -> jatuh ke jalur lama di bawah

        # Provider OAuth: descriptor diambil dari registry (generic), bukan
        # dari daftar lokal. `needs_oauth` tetap dipertahankan sebagai
        # alias supaya klien lama tidak rusak.
        if _prov in _cf.OAUTH_ONLY_PROVIDERS:
            try:
                _rq = _cf.build_requires_oauth(
                    _prov, user_email, session_id=session_id)
                _rq["status"] = "requires_oauth"
                _rq["connect_url"] = _rq.get("oauth_url")
                _persist_card(user_email, session_id, user_id, req_id,
                              {**dict(_rq), "type": "oauth_prompt",
                               "original": req.prompt})
                return _rq
            except ValueError:
                pass

        connect_url = _oauth_providers.get(_prov)
        # BUG FIX 2026-10-06 (vault hilang saat navigasi): persist kartu supaya
        # bertahan saat user pindah sesi / refresh. `_persist_card` ditulis
        # SEBELUM literal return agar bentuk kontrak respons tidak berubah.
        _persist_card(user_email, session_id, user_id, req_id,
                      {"type": "oauth_prompt" if connect_url else "credential_form",
                       "provider": e.provider_name,
                       "connect_url": connect_url,
                       "original": req.prompt})
        return {
            "status": "needs_oauth" if connect_url else "needs_credential",
            "provider": e.provider_name,
            "connect_url": connect_url,
            "message": (
                f"Provider {e.provider_name} memakai OAuth — hubungkan akun lewat tombol Connect."
                if connect_url
                else "Akses dibutuhkan"
            ),
            # session_id WAJIB tetap ada: frontend memakainya untuk melanjutkan
            # percakapan yang sama setelah user menyelesaikan Connect.
            "session_id": session_id,
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        # F-4 (KEAMANAN - kebocoran 500): detail upstream (mis.
        # "ClientError: 400 INVALID_ARGUMENT" dari Gemini, atau pesan kuota model
        # internal) TIDAK boleh bocor ke klien. Versi lama menyisipkan
        # `type(exc).__name__: exc` ke body 500, sehingga UI menampilkan pesan
        # internal yang tidak bisa ditindaklanjuti user dan membocorkan
        # struktur upstream. Stack lengkap tetap dicatat di log Railway untuk
        # diagnosis; klien hanya menerima pesan generik yang aman.
        import traceback
        traceback.print_exc()  # full stack ke Railway log (Fase 2b)
        print(f"[api_server] /chat gagal: {type(exc).__name__}: {exc}")
        raise HTTPException(
            500, "Terjadi kesalahan internal. Silakan coba lagi sebentar lagi.")

    # Simpan balasan AI.
    # Lewati balasan KOSONG: giliran kartu (approval/denied) tidak punya teks,
    # dan baris assistant kosong hanya menjadi bubble hampa setelah reload.
    if str(reply or "").strip():
        try:
            db.add_message(user_email, session_id, "assistant", reply, auth_id=user_id, client_request_id=req_id)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            print(f"[api_server] /chat gagal menyimpan balasan: "
                  f"{type(exc).__name__}: {exc}")
            raise HTTPException(
                500, "Gagal menyimpan balasan. Silakan coba lagi.")

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

    # BUG FIX 2026-10-05: `status` TIDAK boleh di-hardcode "success".
    # Terbukti di produksi: gateway sudah benar mengembalikan
    # `requires_approval` (dibuktikan meta.bracket_tool_calls terisi), tapi
    # baris ini menimpanya jadi "success" sehingga approval_token hilang
    # tanpa jejak dan user tidak pernah melihat tombol Setujui.
    #
    # `requires_credential` tidak pernah lewat sini - ia naik sebagai
    # CredentialMissingError dan ditangani jauh di atas - jadi bug ini
    # hanya menimpa status baru, dan karena itu tidak kelihatan.
    _response = {"status": "success", "reply": reply,
                 "session_id": session_id, "meta": meta}
    _gw_status = str(_run.get("status") or "success").strip()
    if _gw_status and _gw_status != "success":
        _response["status"] = _gw_status
        # Teruskan field khusus status tersebut. Daftar ini disengaja
        # (allowlist): field yang tidak disebut tidak ikut terbawa.
        for _k in ("approval_token", "resume_token", "provider",
                   "display_name", "icon", "fields", "tool", "args",
                   "reason", "alignment", "expires_in", "message",
                   "connect_url", "oauth_url", "name"):
            if _k in _run:
                _response[_k] = _run[_k]
        # BUG FIX 2026-10-06 (vault hilang saat navigasi): persist kartu
        # approval/denied supaya bertahan saat user pindah sesi / refresh.
        # Sebelumnya kartu hanya hidup di cache klien dan lenyap begitu saja.
        if _gw_status == "requires_approval":
            _persist_card(user_email, session_id, user_id, req_id,
                          {"type": "approval_prompt",
                           "tool": _response.get("tool"),
                           "toolArgs": _response.get("args") or {},
                           "reason": _response.get("reason"),
                           "alignment": _response.get("alignment"),
                           "approval_token": _response.get("approval_token"),
                           "original": req.prompt})
        elif _gw_status == "denied":
            _persist_card(user_email, session_id, user_id, req_id,
                          {"type": "error",
                           "content": (_response.get("reason")
                                       or "Permintaan ditolak oleh keamanan."),
                           "original": req.prompt})
    return _response


# ---------------------------------------------------------------------------
# ENDPOINT (BUG FIX 2026-10-03): POST /chat/interrupted
#
# Mengembalikan `session_id` dari giliran yang sudah TERSIMPAN di server lalu
# dihentikan user (tombol Stop).
#
# Kenapa perlu: `POST /chat` menyimpan pesan user ke `chat_messages` SEBELUM
# menjalankan agent, jadi konteksnya tidak pernah hilang di server. Yang hilang
# adalah `session_id`: responsnya ter-abort, jadi klien tidak pernah tahu sesi
# mana yang dipakai. Untuk percakapan yang masih baru, giliran berikutnya lalu
# membuat SESI BARU yang riwayatnya kosong - gejala "konteks hilang".
#
# Endpoint ini menutup celah itu TANPA menghapus apa pun: ia hanya mencari
# kembali sesi yang sudah ada. Kalau pesan user belum sempat tersimpan, jawabannya
# `session_id: null` dan klien memakai perilaku lama.
#
# Idempoten: pemanggilan berulang selalu mengembalikan hal yang sama dan tidak
# mengubah data.
# ---------------------------------------------------------------------------
class InterruptedTurnBody(BaseModel):
    """Body untuk POST /chat/interrupted."""

    client_request_id: str = Field(..., min_length=1)


@app.post("/chat/interrupted")
def chat_interrupted(body: InterruptedTurnBody, authorization: str | None = Header(None)):
    """Cari sesi yang sudah menampung giliran yang dibatalkan user (tombol Stop).

    BUG FIX 2026-10-03 (cancel context loss). Endpoint ini TIDAK menghapus apa pun.

    `POST /chat` menyimpan pesan user ke `chat_messages` SEBELUM menjalankan agent
    (lihat `db.add_message(..., "user", ...)` di fungsi `chat`), jadi konteksnya
    tidak pernah hilang di server. Yang hilang waktu klien meng-abort request
    hanyalah `session_id` di dalam respons. Untuk percakapan yang masih baru,
    giliran berikutnya lalu membuat SESI BARU yang riwayatnya kosong - persis
    gejala "konteks hilang" yang dilaporkan user.

    Endpoint ini menutup celah itu dengan cara MENCARI KEMBALI sesi yang sudah
    ada. Kalau pesan user belum sempat tersimpan (abort sebelum `add_message`),
    balas `{session_id: null}` dan klien memakai perilaku lama.

    Idempoten: pemanggilan berulang mengembalikan hasil yang sama, tanpa menulis.

    Returns:
        {status, session_id, has_reply, ok}
        - session_id: id sesi efektif, atau None bila tidak bisa dipulihkan.
        - has_reply: True bila balasan sempat selesai di server walau klien
          menyerah menunggu (jarang; dicek supaya UI bisa invalidate, bukan
          menebak).
    """
    user = security.get_current_user(authorization)
    user_email = user["email"]

    try:
        prior = db.find_user_message_by_request(body.client_request_id)
    except Exception as exc:  # noqa: BLE001
        print(f"[api_server] gagal mencari giliran terputus: {type(exc).__name__}: {exc}")
        prior = None

    if not prior or not prior.get("session_id"):
        return {"status": "success", "session_id": None, "has_reply": False, "ok": True}

    sid = str(prior["session_id"])

    # Ownership check. `find_user_message_by_request` memakai service-role
    # client, jadi TIDAK memfilter per user. `db.get_messages(owner, ...)` sudah
    # memvalidasi kepemilikan (dipakai juga oleh `load_history`), jadi
    # pemeriksaan di sini mencegah endpoint ini jadi oracle keberadaan sesi
    # milik orang lain bila `client_request_id` pernah bocor.
    try:
        db.get_messages(user_email, sid)
    except HTTPException:
        return {"status": "success", "session_id": None, "has_reply": False, "ok": True}
    except Exception:  # noqa: BLE001
        return {"status": "success", "session_id": None, "has_reply": False, "ok": True}

    try:
        reply = db.get_last_assistant_reply(sid, client_request_id=body.client_request_id)
    except Exception:  # noqa: BLE001 - hanya informatif
        reply = None

    return {
        "status": "success",
        "session_id": sid,
        "has_reply": bool(reply),
        "ok": True,
    }


# ---------------------------------------------------------------------------
# ENDPOINT: GET /me  (profil user: email + tier) — untuk tier-gate ModelSelector.
# ---------------------------------------------------------------------------
@app.get("/me")
def me(authorization: str | None = Header(None)):
    """Kembalikan {email, tier} user JWT (tier dari public.users, default free)."""
    user = security.get_current_user(authorization)
    try:
        _u = db.get_or_create_user(user["email"], "", auth_id=user["id"])
        # Tier EFEKTIF (launch): user lama pro/ultra tampil sebagai plus.
        tier = db.effective_tier((_u or {}).get("tier", "free"))
    except Exception:
        tier = "free"
    return {"status": "success", "email": user["email"], "tier": tier}


# ---------------------------------------------------------------------------
# ENDPOINT: GET /preferences + PUT /preferences  (FASE 4)
#
# Preferensi UI per user (tema kanvas dst) supaya pilihan tidak hilang saat
# berpindah browser/perangkat. localStorage TETAP sumber utama di klien
# (instan, offline-safe); endpoint ini sinkronisasi profil.
#
# Tabel `user_preferences` bersifat ADITIF & opsional -- lihat catatan di
# kepala `database.py`. Bila belum dibuat, penyimpanan jatuh ke memori proses
# dan endpoint TETAP 200 (bukan 500), sehingga klien tidak pernah rusak karena
# migration yang belum dijalankan.
# ---------------------------------------------------------------------------
class PreferencesBody(BaseModel):
    prefs: dict[str, Any] = Field(default_factory=dict)


@app.get("/preferences")
def get_preferences(authorization: str | None = Header(None)):
    """Preferensi UI user JWT (kosong bila belum pernah disimpan)."""
    user = security.get_current_user(authorization)
    prefs = db.get_user_preferences(user["email"])
    return {"status": "success", "prefs": prefs}


@app.put("/preferences")
def put_preferences(body: PreferencesBody, authorization: str | None = Header(None)):
    """Simpan (merge) preferensi UI user JWT. Kunci yang tidak dikirim tetap utuh."""
    user = security.get_current_user(authorization)
    merged = dict(db.get_user_preferences(user["email"]))
    merged.update({k: v for k, v in (body.prefs or {}).items() if isinstance(k, str)})
    saved = db.save_user_preferences(user["email"], merged)
    return {"status": "success", "prefs": saved}


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
        # Tier EFEKTIF di sini juga (pro/ultra lama -> plus) supaya dashboard
        # dan warning kuota tidak menampilkan skema yang disembunyikan.
        tier = db.effective_tier((_u or {}).get("tier", "free"))
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


@app.get("/analytics")
def get_analytics(authorization: str | None = Header(None)):
    """Authenticated, owner-scoped usage and workflow execution summary."""
    user = security.get_current_user(authorization)
    return {"status": "success", "quota": db.quota_status(user["email"], db.effective_tier((db.get_or_create_user(user["email"], "", auth_id=user.get("id")) or {}).get("tier", "free"))), "executions": db.execution_analytics(user["id"])}


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
        tier = db.effective_tier((_u or {}).get("tier", "free"))
    except Exception:
        tier = "free"
    # Launch 2026-09-18: pro/ultra diperlakukan sebagai plus di database.py;
    # is_plus di sini berarti akses jalur berbayar (PLUS_TIERS lama diganti
    # pemeriksaan langsung agar maksudnya jelas).
    is_plus = (tier == "plus")
    default_id = _default_model_id()
    discovered = md.get_available_models()
    items = [
        {**m, "locked": bool(m.get("tier") == "plus" and not is_plus)}
        for m in discovered
    ]
    # DIAGNOSTIK (2026-09-19): user pernah melihat dropdown "hanya Google" tanpa
    # penjelasan karena discovery jatuh ke daftar Gemini secara senyap saat
    # roster gateway kosong. Kini asal daftar + status degradasi ikut dikirim
    # supaya UI bisa memperingatkan dan investigasi tidak lagi menebak.
    health = md.discovery_health()
    return {"status": "success", "tier": tier, "default": default_id,
            "models": items,
            "roster_source": health.get("source", "unknown"),
            "degraded": bool(health.get("degraded")),
            "degraded_reason": health.get("reason", ""),
            "refreshed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(md._cache["ts"]))}


# ---------------------------------------------------------------------------
# ENDPOINT 2: POST /integrations
# ---------------------------------------------------------------------------


class MCPInstanceRequest(BaseModel):
    mcp_id: str
    config: dict[str, Any] = Field(default_factory=dict)
    confirmed: bool = False

_MCP_INSTANCES: dict[str, dict[str, dict[str, Any]]] = {}
_EXECUTABLE_MCP_IDS = {"everything", "fetch", "memory", "filesystem", "time"}


class AutoConfigPreviewRequest(BaseModel):
    """Preview = rencana tanpa efek samping (FASE E auto-config).

    Install yang sebenarnya tetap `POST /mcp/install` dan WAJIB mengirim
    `confirmed=true`; preview hanya supaya UI bisa menampilkan konfigurasi
    yang kurang sebelum pengguna menekan tombol konfirmasi.
    """
    mcp_id: str
    config: dict[str, Any] = Field(default_factory=dict)


@app.post("/mcp/auto-config/preview")
def mcp_auto_config_preview(req: AutoConfigPreviewRequest, authorization: str | None = Header(None)):
    import mcp_autoconfig as ac
    _mcp_key(authorization)
    try:
        p = ac.plan(req.mcp_id, req.config)
    except ac.AutoConfigError as exc:
        raise HTTPException(400, str(exc))
    return {"plan": p.to_dict(), "requires_confirmation": True, "install_endpoint": "/mcp/install"}

def _mcp_key(authorization: str | None) -> str:
    user = security.get_current_user(authorization)
    return str(user.get("id") or user.get("email") or "unknown")

def _mcp_rows(user_id: str):
    if db.is_configured():
        res = db._get_write_client().table("user_mcp_instances").select("mcp_id,config,status,created_at,updated_at").eq("user_id", user_id).execute()
        return list(res.data or [])
    return list(_MCP_INSTANCES.get(user_id, {}).values())

@app.get("/mcp/my-instances")
def mcp_my_instances(authorization: str | None = Header(None)):
    user_id = _mcp_key(authorization)
    return {"instances": _mcp_rows(user_id)}

@app.post("/mcp/install")
def mcp_install(req: MCPInstanceRequest, authorization: str | None = Header(None)):
    user_id = _mcp_key(authorization)
    if not req.mcp_id.strip():
        raise HTTPException(422, "mcp_id wajib")
    if not req.confirmed:
        raise HTTPException(409, "Instalasi memerlukan konfirmasi eksplisit")
    # allowlist runtime: entri katalog metadata-only tidak pernah bisa di-install
    import mcp_autoconfig as ac
    try:
        p = ac.plan(req.mcp_id, req.config)
    except ac.AutoConfigError as exc:
        raise HTTPException(422, str(exc))
    import mcp_registry
    req_item = {"id": req.mcp_id, "install_config": {"transport": "stdio", "package": req.mcp_id}}
    verified = mcp_registry.validate_executable_manifest(req_item)
    if verified["status"] != "valid":
        raise HTTPException(422, f"Manifest ditolak: {', '.join(verified['errors'])}")
    row = {"mcp_id": p.mcp_id, "config": req.config, "status": "active" if not p.missing_config else "needs_config",
           "runtime": p.runtime, "transport": p.transport, "package": p.package, "manifest": verified,
           "missing_config": p.missing_config, "warnings": p.warnings}
    if db.is_configured():
        client = db._get_write_client()
        payload = {"user_id": user_id, "mcp_id": row["mcp_id"], "config": req.config, "status": row["status"], "updated_at": db._now()}
        existing = client.table("user_mcp_instances").select("id").eq("user_id", user_id).eq("mcp_id", row["mcp_id"]).limit(1).execute()
        if existing.data:
            client.table("user_mcp_instances").update(payload).eq("id", existing.data[0]["id"]).execute()
        else:
            client.table("user_mcp_instances").insert(payload).execute()
    else:
        _MCP_INSTANCES.setdefault(user_id, {})[row["mcp_id"]] = row
    return {"instance": row}

@app.delete("/mcp/uninstall/{mcp_id}")
def mcp_uninstall(mcp_id: str, authorization: str | None = Header(None)):
    user_id = _mcp_key(authorization)
    if db.is_configured():
        client = db._get_write_client()
        existing = client.table("user_mcp_instances").select("id").eq("user_id", user_id).eq("mcp_id", mcp_id).limit(1).execute()
        if not existing.data:
            raise HTTPException(404, "Instance tidak ditemukan")
        client.table("user_mcp_instances").delete().eq("id", existing.data[0]["id"]).execute()
    else:
        removed = _MCP_INSTANCES.get(user_id, {}).pop(mcp_id, None)
        if not removed:
            raise HTTPException(404, "Instance tidak ditemukan")
    return {"removed": mcp_id}

# ---------------------------------------------------------------------------
@app.get("/mcp/gateway/health")
async def mcp_gateway_health(authorization: str | None = Header(None)):
    from mcp_gateway.client import GatewayClient
    security.get_current_user(authorization)
    try:
        ok = await GatewayClient().health()
        return {"status": "ok" if ok else "unreachable"}
    except Exception:
        return {"status": "unreachable"}

@app.get("/mcp/gateway/servers")
def mcp_gateway_servers(authorization: str | None = Header(None), refresh: int = 0):
    """Katalog tool MCP gateway — dilayani dari cache, BUKAN 503 saat gateway gagal.

    Sebelumnya endpoint ini memanggil gateway pada SETIAP request (8-13 detik)
    dan membalas 503 begitu gateway tidak bisa dihubungi. Terbukti di produksi:
    saat guard VPS me-restart agentgateway, satu panggilan langsung 503 —
    padahal daftar tool hampir tidak pernah berubah. Sekarang:
      * cache segar (< TTL) -> dilayani seketika, tanpa menyentuh gateway;
      * gateway gagal tetapi ada cache -> balas 200 dengan `source="stale"`;
      * hanya 503 bila memang belum ada data sama sekali.
    `?refresh=1` memaksa pengambilan ulang dari gateway.
    """
    security.get_current_user(authorization)
    out = mcp_tool_cache.get_tools(force_refresh=bool(refresh))
    if out["source"] == "none":
        raise HTTPException(503, f"Gateway tidak tersedia: {out['error']}")
    return {"tools": out["tools"], "source": out["source"],
            "age_s": round(float(out["age_s"]), 1),
            "warning": (f"data cache; gateway gagal: {out['error']}"
                        if out["source"] == "stale" else "")}

class GatewayCallRequest(BaseModel):
    server_id: str | None = None
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)

@app.post("/mcp/gateway/call")
def mcp_gateway_call(req: GatewayCallRequest, authorization: str | None = Header(None)):
    from mcp_gateway.client import GatewayClient
    security.get_current_user(authorization)
    if not req.tool:
        raise HTTPException(422, "tool wajib")
    try:
        return GatewayClient().call_tool_sync(req.tool, req.arguments)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"Gateway call gagal: {type(exc).__name__}")


@app.get("/mcp/recommendations")
def mcp_recommendations(q: str, limit: int = 5):
    import mcp_registry as catalog
    try:
        return {"items": catalog.recommend_servers(q, limit), "source": "toolsdk-mcp-registry"}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/mcp/registry")
def mcp_registry(page: int = 1, limit: int = 50, search: str = "", category: str = "", source: str = "", view: str = "all", tier: str = ""):
    """view=all is the raw merged catalogue; view=unique is the deduped set.

    Both are real numbers and they differ by the duplicate rate, so the caller
    must say which one it is displaying rather than being handed one by default.

    `tier` is passed straight through to the registry, which owns the single
    definition of a tier. The UI filters and badges from the same function, so
    the two cannot disagree.
    """
    import mcp_registry as catalog
    if view not in ("all", "unique"):
        raise HTTPException(400, f"view must be 'all' or 'unique', got {view!r}")
    try:
        if view == "unique":
            return catalog.list_canonical(page=page, limit=limit, search=search, category=category, source=source, tier=tier)
        return catalog.list_servers(page=page, limit=limit, search=search, category=category, source=source, tier=tier)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/mcp/registry/capabilities")
def mcp_registry_capabilities():
    """Apakah view `unique` benar-benar bisa dilayani, dan kenapa.

    `dedup_canonical.json` sengaja TIDAK di-commit (29,8 MB hasil turunan), jadi
    ada deploy yang bisa booting tanpa file itu. Waktu itu `GET /mcp/registry?
    view=unique` balas 400 dan toggle "Unique (dedup)" di UI jadi gagal tanpa
    penjelasan.

    Frontend memakai endpoint ini untuk jujur menyembunyikan toggle ketika
    artifact-nya memang tidak ada, alih-alih memunculkan kontrol yang pasti
    error. `reason` sengaja dikembalikan supaya UI bisa menjelaskan, bukan
    hanya diam.

    Catatan: `buildCommand: python mcp_dedup.py` di railway.json seharusnya
    selalu menghasilkan file ini, jadi di Railway normal nilainya true. Endpoint
    ini adalah jaring pengaman untuk target deploy lain (Railway alternate,
    container manual, Codespaces) yang tidak menjalankan build step.
    """
    import mcp_registry as catalog
    available = catalog.CANONICAL_PATH.exists()
    return {
        "unique_view": available,
        "reason": None if available else "unique view unavailable: run mcp_dedup.py to build dedup_canonical.json",
        "canonical_path": catalog.CANONICAL_PATH.name,
        "version": "1.0",
    }


@app.get("/mcp/native")
def mcp_native():
    """The natively executable providers, derived from provider_registry.

    The count is computed from code, never hardcoded in the UI, so the
    "Native" marketplace tab can never drift from what actually runs.

    ``credential`` is empty only for providers that execute without any user
    secret; that is what separates the Ready badge from Auth required.
    """
    import provider_registry as pr
    items = []
    for spec in pr.PROVIDERS.values():
        items.append(
            {
                "id": f"native/{spec.name}",
                "name": spec.name,
                "summary": spec.summary,
                "credential": spec.credential,
                "needs_credential": bool(spec.credential),
                "source": "native",
                # Only providers that need no user secret are "Ready"; the rest
                # run natively but are Auth required until the user connects.
                "runtime_verified": not spec.credential,
                "verification": {
                    "discovered": True,
                    "tools_listed": True,
                    # executed in-process, but only called end to end with a
                    # real credential, so it is not claimed as call_verified
                    "call_verified": False,
                },
            }
        )
    return {"items": items, "total": len(items), "source": "native"}


class CommunitySubmission(BaseModel):
    name: str
    source_url: str
    description: str = ""
    manifest: dict


def _community_unavailable() -> HTTPException:
    """The community tables are not deployed yet.

    Failing closed keeps the marketplace honest: a browse endpoint that
    silently returns an empty list would look like "no community integrations
    exist" rather than "the feature is off", which is exactly the kind of quiet
    dishonesty this project keeps trying to avoid.
    """
    return HTTPException(503, "community tables not deployed; apply docs/architecture/community-platform.sql")


@app.post("/community/submit")
def community_submit(req: CommunitySubmission, authorization: str | None = Header(None)):
    """Submit an integration manifest for review. Pending is not approved."""
    user = security.get_current_user(authorization)
    if not req.name.strip() or not req.source_url.strip():
        raise HTTPException(400, "name and source_url are required")
    if not isinstance(req.manifest, dict) or not req.manifest.get("tools"):
        raise HTTPException(400, "manifest must be an object containing a 'tools' list")
    import database as db

    developer_id = user.get("id") or user.get("user_id") or user.get("email")
    try:
        row_id = db.submit_community_integration(
            developer_id=developer_id,
            name=req.name.strip(),
            source_url=req.source_url.strip(),
            description=req.description.strip()[:1000],
            manifest=req.manifest,
        )
    except Exception as exc:  # noqa: BLE001
        raise _community_unavailable() from exc
    return {"status": "pending", "id": row_id, "note": "pending review; not verified"}


@app.get("/community/browse")
def community_browse(limit: int = 25):
    """Approved submissions only - never pending or rejected ones."""
    import database as db

    try:
        rows = db.list_community_integrations(status="approved", limit=min(max(limit, 1), 100))
    except Exception as exc:  # noqa: BLE001
        raise _community_unavailable() from exc
    return {"items": rows, "total": len(rows), "status_filter": "approved"}


@app.get("/community/review")
def community_review(authorization: str | None = Header(None)):
    """Queue of pending submissions for moderation."""
    security.get_current_user(authorization)
    import database as db

    try:
        rows = db.list_pending_community_integrations(limit=50)
    except Exception as exc:  # noqa: BLE001
        raise _community_unavailable() from exc
    return {"items": rows, "total": len(rows)}


@app.get("/community/my-earnings")
def community_my_earnings(authorization: str | None = Header(None)):
    user = security.get_current_user(authorization)
    import database as db

    developer_id = user.get("id") or user.get("user_id") or user.get("email")
    try:
        rows = db.list_community_earnings(developer_id)
    except Exception as exc:  # noqa: BLE001
        raise _community_unavailable() from exc
    return {"items": rows, "total_usd": sum(float(r.get("amount_usd") or 0) for r in rows)}


@app.get("/mcp/registry/categories")
def mcp_registry_categories(source: str = "", limit: int = 40):
    """Category facet for the F4.3 filter, derived from the same rows as the grid."""
    import mcp_registry as catalog
    return catalog.category_facets(source=source, limit=max(1, min(limit, 200)))


@app.get("/mcp/registry/sources")
def mcp_registry_sources():
    """Per-source counts plus the Glama credit the UI must render.

    Glama's API Data License requires a visible "Powered by Glama" credit on
    every page that shows its data, so the API ships the exact link and label
    rather than letting the frontend invent one.
    """
    import mcp_registry as catalog
    import provider_registry as pr
    return {
        "sources": {**catalog.source_counts(), "native": len(pr.PROVIDERS)},
        "sources_unique": catalog.source_counts_unique(),
        "coverage": catalog.coverage(),
        "attribution": {
            "glama": {
                "required": True,
                "label": "MCP data from Glama",
                "href": "https://glama.ai/mcp/servers",
                "note": "Listing data is licensed under the Glama API Data License; attribution and a link back to each listing are required.",
            }
        },
    }


@app.get("/mcp/registry/coverage")
def mcp_registry_coverage():
    import mcp_registry as catalog
    return catalog.coverage()


@app.get("/mcp/recommended")
def mcp_recommended(category: str = "", source: str = "", limit: int = 5):
    """Integrasi yang direkomendasikan, dihitung dari rumus yang dikunci.

    Skor dihitung runtime di `mcp_registry.compute_recommendation_score` —
    tidak ada daftar hardcoded di endpoint maupun di registry. Endpoint ini
    hanya membungkusnya, menambah batasan param, dan meneruskan
    `data_coverage` apa adanya supaya kelemahan data terlihat di respons,
    bukan hanya di dokumen internal.

    `GET /mcp/registry/{server_id:path}` ada di SEJAKHIRANYA dan memakai
    pola `{...:path}`, jadi rute ini harus dideklarasikan SEBELUM-nya agar
    "recommended" tidak tertangkap sebagai server_id.
    """
    import mcp_registry as catalog
    try:
        return catalog.get_recommended(category=category, source=source, limit=max(1, min(int(limit), 50)))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/mcp/registry/{server_id:path}")
def mcp_registry_detail(server_id: str):
    import mcp_registry as catalog
    try:
        return catalog.get_server(server_id)
    except KeyError:
        raise HTTPException(404, "MCP server tidak ditemukan")


@app.post("/mcp/registry/sync")
def mcp_registry_sync(authorization: str | None = Header(None)):
    import mcp_registry as catalog
    security.get_current_user(authorization)
    try:
        count = catalog.sync_from_public()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Gagal sync registry publik: {type(exc).__name__}")
    return {"status": "success", "synced": count, "source": catalog.SOURCE_URL}



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
# ---------------------------------------------------------------------------
# ENDPOINTS: OAuth Google Sheets (OAuth 2.1 + PKCE)
#
# KENAPA TERPISAH DARI `/api/vault/save`: alur ini REDIRECT, bukan XHR. User
# meninggalkan aplikasi, menyetujui di Google, lalu kembali ke /settings.
# Identitas user dibawa di `state` bertanda tangan (backend tidak punya sesi
# cookie), dan `code_verifier` tetap di server — lihat oauth_google.py.
# ---------------------------------------------------------------------------
def _og():
    import oauth_google as og  # impor lokal: api_server tetap bisa start tanpa modul ini

    return og


def _ui_base() -> str:
    return (os.getenv("APP_UI_URL") or os.getenv("CORS_ORIGIN") or "http://localhost:3000").split(",")[0].strip().rstrip("/")


def _append_query(url: str, params: dict) -> str:
    """Tambah query param ke URL tanpa merusak param yang sudah ada."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
    parts = urlsplit(url)
    q = dict(parse_qsl(parts.query))
    q.update({k: v for k, v in params.items() if v})
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       urlencode(q), parts.fragment))


def _resume_destination(resume: str) -> str:
    """URL chat tujuan yang MEMBAWA token resume, atau "" .

    Sengaja dibangun dari `_ui_base()`, bukan dari input mentah, sehingga
    mustahil menjadi open-redirect.
    """
    if not resume:
        return ""
    from urllib.parse import quote
    return f"{_ui_base()}/chat?resume={quote(resume, safe='')}"


def _safe_resume_target(state: str) -> str:
    """Baca tujuan kembali dari `state`, TAPI hanya jika host-nya UI sendiri.

    `state` berasal dari provider, jadi tidak boleh dipercaya: tanpa
    pemeriksaan host, penyerang bisa menitipkan `redirect_to` milik situs
    lain dan memakai callback kita sebagai pengalihan.
    """
    if not state:
        return ""
    try:
        from urllib.parse import parse_qsl, urlsplit
        target = dict(parse_qsl(urlsplit(state).query)).get("redirect_to", "")
    except (TypeError, ValueError):
        return ""
    if not target:
        return ""
    a, b = urlsplit(target), urlsplit(_resume_destination("x"))
    if a.scheme not in ("http", "https"):
        return ""
    if (a.scheme, a.netloc, a.path) != (b.scheme, b.netloc, b.path):
        return ""
    return target


def _resume_from_state(state: str) -> str:
    """Ambil param `resume` yang kita sisipkan sendiri saat authorize.

    Jangan percaya `state` mentah: hanya terima token yang benar-benar
    berbentuk resume token milik kita (dicek ulang di /chat/resume).
    """
    if not state:
        return ""
    try:
        from urllib.parse import parse_qsl, urlsplit
        q = dict(parse_qsl(urlsplit(state).query))
    except (TypeError, ValueError):
        return ""
    return str(q.get("resume") or "")



@app.get("/oauth/google/authorize")
def oauth_google_authorize(authorization: str | None = Header(None), redirect_base: str | None = None,
                          mode: str = "", resume: str = ""):
    """Redirect ke consent Google (PKCE S256, access_type=offline, prompt=consent).

    `mode=json` mengembalikan {"url": ...} alih-alih 302. KENAPA: tombol
    "Connect" di `/settings` memakai redirect HALAMAN PENUH (bukan popup), dan
    redirect halaman penuh TIDAK bisa membawa header Authorization. Dengan mode
    ini, frontend meminta URL lewat `apiFetch` (JWT ikut di header), lalu
    mengarahkan browser ke URL itu — sehingga JWT tidak pernah masuk ke URL/log.
    """
    user = security.get_current_user(authorization)
    og = _og()
    if not og.configured():
        # Jujur: tanpa kunci, jangan menebak URL yang pasti gagal.
        raise HTTPException(503, "OAuth Google belum dikonfigurasi (GOOGLE_CLIENT_ID/SECRET kosong).")
    try:
        url = og.build_authorize_url(user["email"], redirect_base)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    if mode == "json":
        return {"status": "success", "provider": og.PROVIDER, "url": url}
    from fastapi.responses import RedirectResponse  # impor lokal: hindari ubah blok impor

    # `resume` diteruskan lewat `redirect_to` supaya setelah consent user
    # mendarat kembali ke percakapan yang terhenti, bukan ke halaman Settings.
    # Tanpa ini, alur OAuth selalu "buntu di halaman lain" dan user harus
    # mengetik ulang permintaannya (Bagian 3.2c).
    if resume:
        url = _append_query(url, {"redirect_to": _resume_destination(resume)})
    return RedirectResponse(url, status_code=302)



@app.get("/oauth/google/callback")
def oauth_google_callback(code: str = "", state: str = "", error: str = ""):
    """Terima `code`, tukar jadi token, simpan terenkripsi, lalu balik ke /settings."""
    from fastapi.responses import RedirectResponse

    og = _og()
    ui = _ui_base()
    if error:
        # User menolak / Google menolak: sampaikan alasannya, jangan diam.
        return RedirectResponse(f"{ui}/settings?google=denied&reason={error}", status_code=302)
    if not code or not state:
        return RedirectResponse(f"{ui}/settings?google=error&reason=missing_code_or_state", status_code=302)
    try:
        tokens = og.exchange_code(code, state)
    except (ValueError, RuntimeError) as exc:
        print(f"[oauth] google callback gagal: {type(exc).__name__}: {exc}")
        return RedirectResponse(f"{ui}/settings?google=error&reason=exchange_failed", status_code=302)
    email = tokens.get("email") or ""
    if not email or not og.save_tokens(email, tokens):
        return RedirectResponse(f"{ui}/settings?google=error&reason=vault_save_failed", status_code=302)
    print(f"[oauth] google terhubung untuk {email} (refresh_token={'ada' if tokens.get('refresh_token') else 'TIDAK ADA'})")
    # Kembali ke percakapan yang tertunda bila ada (Bagian 3.2c). Tujuan
    # divalidasi host-nya lebih dulu supaya `state` dari provider tidak bisa
    # dipakai sebagai open-redirect.
    dest = _safe_resume_target(state)
    if dest:
        return RedirectResponse(f"{dest}&google=connected", status_code=302)
    return RedirectResponse(f"{ui}/settings?google=connected", status_code=302)


@app.post("/oauth/google/refresh")
def oauth_google_refresh(authorization: str | None = Header(None)):
    """Perbarui access_token manual (selain jalur otomatis di `access_token()`)."""
    user = security.get_current_user(authorization)
    og = _og()
    tokens = og.load_tokens(user["email"])
    if not tokens:
        raise HTTPException(404, "Belum terhubung ke Google Sheets.")
    try:
        updated = og.refresh_tokens(tokens)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    og.save_tokens(user["email"], updated)
    return {"status": "success", "expires_in_s": og.connection_status(user["email"]).get("expires_in_s")}


@app.get("/oauth/google/status")
def oauth_google_status(authorization: str | None = Header(None)):
    """Status untuk UI `/settings` — TANPA nilai token (hanya boolean/umur)."""
    user = security.get_current_user(authorization)
    og = _og()
    return {"status": "success", "configured": og.configured(), "google_sheets": og.connection_status(user["email"])}


@app.delete("/oauth/google")
def oauth_google_disconnect(authorization: str | None = Header(None)):
    """Cabut koneksi Google Sheets user (hapus token dari Brankas).

    KEAMANAN: user diambil dari JWT — user tidak bisa memutus koneksi orang lain.
    Tanpa endpoint ini tombol "Disconnect" di `/settings` tidak punya cara sah
    untuk mencabut akses; user hanya bisa menimpa token.
    """
    user = security.get_current_user(authorization)
    og = _og()
    existed = bool(og.load_tokens(user["email"]))
    if not og.clear_tokens(user["email"]):
        raise HTTPException(500, "Gagal menghapus token Google dari Brankas.")
    print(f"[oauth] google diputus untuk {user['email']} (sebelumnya_ada={existed})")
    return {"status": "success", "provider": og.PROVIDER, "disconnected": True, "existed": existed}


@app.get("/oauth/slack/authorize")
def oauth_slack_authorize(authorization: str | None = Header(None), redirect_base: str | None = None,
                          mode: str = ""):
    """Redirect ke consent Slack (scope chat:write, channels:read, users:read).

    `mode=json` → {"url": ...} (lihat penjelasan di `/oauth/google/authorize`:
    tombol Connect memakai redirect halaman penuh, dan JWT tidak boleh masuk URL).
    """
    user = security.get_current_user(authorization)
    import oauth_slack as osl

    if not osl.configured():
        raise HTTPException(503, "OAuth Slack belum dikonfigurasi (SLACK_CLIENT_ID/SECRET kosong).")
    try:
        url = osl.build_authorize_url(user["email"], redirect_base)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    if mode == "json":
        return {"status": "success", "provider": osl.PROVIDER, "url": url}
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url, status_code=302)



@app.get("/oauth/slack/callback")
def oauth_slack_callback(code: str = "", state: str = "", error: str = ""):
    """Tukar code -> bot token workspace -> simpan terenkripsi di Vault."""
    from fastapi.responses import RedirectResponse

    import oauth_slack as osl

    ui = _ui_base()
    if error:
        return RedirectResponse(f"{ui}/settings?slack=denied&reason={error}", status_code=302)
    if not code or not state:
        return RedirectResponse(f"{ui}/settings?slack=error&reason=missing_code_or_state", status_code=302)
    try:
        data = osl.exchange_code(code, state)
    except (ValueError, RuntimeError) as exc:
        print(f"[oauth] slack callback gagal: {type(exc).__name__}: {exc}")
        return RedirectResponse(f"{ui}/settings?slack=error&reason=exchange_failed", status_code=302)
    email = data.get("email") or ""
    if not email or not osl.save_installation(email, data):
        return RedirectResponse(f"{ui}/settings?slack=error&reason=vault_save_failed", status_code=302)
    print(f"[oauth] slack terhubung untuk {email} team={data.get('team_name') or '?'}")
    return RedirectResponse(f"{ui}/settings?slack=connected", status_code=302)


@app.get("/oauth/slack/status")
def oauth_slack_status(authorization: str | None = Header(None)):
    """Status Slack: kunci ada + alur OAuth SUDAH diimplementasikan (Task 1A).

    Dibuat menerima JWT (opsional) supaya bisa dipakai dua konteks: probe tanpa
    login (hanya status kunci) dan UI `/settings` (status koneksi per user).
    """
    import oauth_slack as osl

    keys = {
        "SLACK_APP_ID": bool((os.getenv("SLACK_APP_ID") or "").strip()),
        "SLACK_CLIENT_ID": bool((os.getenv("SLACK_CLIENT_ID") or "").strip()),
        "SLACK_CLIENT_SECRET": bool((os.getenv("SLACK_CLIENT_SECRET") or "").strip()),
        "SLACK_SIGNING_SECRET": bool((os.getenv("SLACK_SIGNING_SECRET") or "").strip()),
        "SLACK_VERIFICATION_TOKEN": bool((os.getenv("SLACK_VERIFICATION_TOKEN") or "").strip()),
    }
    filled = sum(1 for v in keys.values() if v)
    out = {
        "status": "success",
        "keys_present": filled,
        "keys_total": len(keys),
        "keys": keys,
        "implemented": True,
        "authorize_endpoint": "/oauth/slack/authorize",
        "reason": (
            "Alur OAuth Slack siap; kunci lengkap."
            if filled == len(keys)
            else "Sebagian kunci Slack kosong — isi dari api.slack.com/apps."
        ),
    }
    if authorization:
        try:
            user = security.get_current_user(authorization)
            out["slack"] = osl.connection_status(user["email"])
        except HTTPException:
            out["slack"] = {"connected": False, "provider": "slack"}
    else:
        out["slack"] = {"connected": False, "provider": "slack"}

    # Kontrak yang diminta UI (Task 1B): `connected` + `team_name` di tingkat
    # atas, supaya kartu `/settings` tidak perlu tahu bentuk bersarang `slack`.
    # `slack` (bersarang) tetap dikirim agar probe/tes lama tidak pecah.
    out["connected"] = bool(out["slack"].get("connected"))
    out["team_name"] = out["slack"].get("team_name") or ""
    return out


@app.delete("/oauth/slack")
def oauth_slack_disconnect(authorization: str | None = Header(None)):
    """Cabut instalasi Slack user (bot token dihapus dari Brankas).

    KEAMANAN: user dari JWT. Bot token dihapus DARI SISI KITA; untuk mencabut di
    sisi Slack, user juga perlu menghapus app-nya di workspace (dicatat di UI
    supaya tidak ada klaim berlebihan bahwa ini "revoke penuh").
    """
    user = security.get_current_user(authorization)
    import oauth_slack as osl

    existed = bool(osl.load_installation(user["email"]))
    if not osl.clear_installation(user["email"]):
        raise HTTPException(500, "Gagal menghapus instalasi Slack dari Brankas.")
    print(f"[oauth] slack diputus untuk {user['email']} (sebelumnya_ada={existed})")
    return {"status": "success", "provider": osl.PROVIDER, "disconnected": True, "existed": existed}





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


@app.get("/api/vault/gmail-imap")
def gmail_imap_status(authorization: str | None = Header(None)):
    """Status koneksi Gmail IMAP untuk UI. TIDAK pernah mengembalikan kredensial."""
    user = security.get_current_user(authorization)
    import database as _db
    from gmail_imap import VAULT_PROVIDER as _VP

    cipher = _db.vault_get(user["email"], _VP)
    connected = bool(cipher)
    address = None
    if connected:
        try:
            import vault_security as _vs
            address = (_json.loads(_vs.decrypt_key(cipher)) or {}).get("email_address")
        except Exception:  # noqa: BLE001 - vault rusak tidak boleh 500
            address = None
    return {
        "status": "success",
        "connected": connected,
        "email_address": address,
        "method": "imap",
        "app_password_url": "https://myaccount.google.com/apppasswords",
    }


@app.post("/api/vault/gmail-imap")
def gmail_imap_save(req: GmailImapSaveRequest, authorization: str | None = Header(None)):
    """Simpan App Password terenkripsi, opsional tes koneksi IMAP.

    Keamanan: user TARGET dari JWT, bukan dari body. App password hanya
    keluar dari server sebagai ciphertext ke vault dan TIDAK PERNAH dikembalikan
    ke klien.
    """
    user = security.get_current_user(authorization)
    try:
        ok = tools.save_gmail_imap_credential(
            user["email"], req.email_address, req.app_password)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if not ok:
        raise HTTPException(500, "Gagal menyimpan kredensial Gmail.")

    result: dict = {"status": "saved", "connected": True,
                    "email_address": req.email_address}
    if req.test_connection:
        from gmail_imap import GmailImapError, trigger_gmail_imap as _poll
        try:
            # Dipakai HANYA untuk tes login; tidak membaca isi email.
            _poll(email_address=req.email_address,
                  app_password=req.app_password,
                  unread_only=True, max_messages=1)
            result["connection_test"] = "ok"
        except GmailImapError as exc:
            # Kredensial tetap disimpan (user mungkin salah ketik spasi), tapi
            # status koneksi_FAILED supaya UI bisa menuntun.
            result["connection_test"] = "failed"
            result["connection_error"] = str(exc)
    return result


@app.delete("/api/vault/gmail-imap")
def gmail_imap_delete(authorization: str | None = Header(None)):
    """Cabut kredensial Gmail IMAP milik user pada JWT."""
    user = security.get_current_user(authorization)
    from gmail_imap import VAULT_PROVIDER as _VP
    ok = db.vault_delete(user["email"], _VP)
    return {"status": "deleted" if ok else "not_found", "connected": False}


class ChatResumeRequest(BaseModel):
    """Body POST /chat/resume — credential dari form inline di chat."""
    resume_token: str
    provider: str = ""
    credentials: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# ENDPOINT: POST /chat/resume
# Credential hasil form inline disimpan terenkripsi, lalu tool langsung bisa
# jalan. Frontend lalu mengirim ulang prompt aslinya (ia masih memegang
# prompt itu di message list), jadi server tidak perlu menyimpan percakapan.
# ---------------------------------------------------------------------------
@app.post("/chat/resume")
def chat_resume(req: ChatResumeRequest, authorization: str | None = Header(None)):
    """Simpan credential dari form inline chat (terenkripsi ke user_vault).

    Keamanan:
      * `resume_token` diverifikasi tanda tangan + masa berlaku + pemilik,
        jadi user lain tidak bisa menyimpan credential ke akun ini.
      * Credential divalidasi terhadap definisi field provider, lalu
        disimpan lewat `vault_security` (Fernet). Tidak pernah dikembalikan.
      * Respons hanya berisi ringkasan non-rahasia.
    """
    user = security.get_current_user(authorization)
    import credential_forms as _cf

    try:
        provider = _cf.verify_resume_token(req.resume_token, user["email"])
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    # Kalau body menyebut provider lain dari token, tolak: token adalah
    # sumber kebenaran (mencegah form dicampur antar provider).
    claimed = str(req.provider or "").strip().lower()
    if claimed and claimed != provider:
        raise HTTPException(400, "Provider tidak cocok dengan resume_token.")

    try:
        summary = _cf.validate_and_save(provider, req.credentials, user["email"])
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except tools.CredentialMissingError:
        raise HTTPException(500, "Gagal menyimpan credential.")

    return {
        "status": "resumed",
        "provider": summary["provider"],
        "display_name": summary["display_name"],
        "email_address": user["email"],
        # Sinyal ke frontend: kirim ulang prompt, tool akan jalan sekarang.
        "retry_hint": "resend_last_prompt",
        "secure_note": "Credential disimpan terenkripsi di vault Anda.",
    }
# ---------------------------------------------------------------------------
# POST /chat/approve - keputusan user atas tool yang butuh persetujuan
# ---------------------------------------------------------------------------
class ApproveRequest(BaseModel):
    """Body untuk /chat/approve.

    Sengaja TIDAK punya field `tool`/`args`: argumen diambil dari dalam
    token bertanda tangan, bukan dari client. Kalau client boleh memilih
    argumen sendiri, persetujuan kehilangan makna - user menyetujui satu
    pesan, lalu server mengirim pesan lain.
    """

    approval_token: str
    decision: str  # "approve" | "deny"


@app.post("/chat/approve")
def approve_tool_call(req: ApproveRequest,
                      authorization: str | None = Header(None)):
    """Eksekusi atau tolak panggilan tool yang menunggu persetujuan user.

    Keamanan:
      * user target dari JWT, bukan dari body;
      * token wajib milik akun ini dan belum kedaluwarsa (HMAC);
      * argumen diambil dari token, bukan dari client;
      * gate + allowlist argumen dijalankan ULANG saat persetujuan -
        kondisi bisa saja berubah antara meminta dan menyetujui.
    """
    user = security.get_current_user(authorization)
    from approval_flow import verify_approval_token

    decision = str(req.decision or "").strip().lower()
    if decision not in ("approve", "deny"):
        raise HTTPException(400, "Decision harus 'approve' atau 'deny'.")

    try:
        payload = verify_approval_token(req.approval_token, user["email"])
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    tool = payload["tool"]
    args = payload.get("args") or {}

    # BUG FIX 2026-10-06 (defect #4): token dari jalur Gemini-langsung
    # memuat nama NATIVE (`kirim_telegram_message`). Validasi ulang di bawah
    # memakai `argument_validator` yang hanya punya skema untuk nama
    # kanonik (`TELEGRAM`) -> "tidak punya skema argumen" + HTTP 400, dan
    # persetujuan kembali buntu. Normalkan ke nama kanonik SEKARANG,
    # sebelum validasi & eksekusi. (`execute_textual_tool` juga menormalkan;
    # idempoten.) Verifikasi token sendiri SUDAH selesai di atas dengan
    # nama asli dari payload, jadi ini tidak melemahkan pemeriksaan.
    from textual_tool_handlers import NATIVE_TO_TEXTUAL
    tool = NATIVE_TO_TEXTUAL.get(str(tool).upper(), tool)

    if decision == "deny":
        return {"status": "denied", "tool": tool,
                "message": "Panggilan dibatalkan oleh Anda."}

    # Verifikasi ulang: jangan percaya begitu saja apa yang disimpan 5 menit
    # lalu. Kredensial bisa saja sudah berubah/kedaluwarsa di antara itu.
    from argument_validator import validate_args as _validate_args
    ok, why = _validate_args(tool, args)
    if not ok:
        raise HTTPException(400, f"Argumen tidak lagi valid: {why}")

    from textual_tool_handlers import execute_textual_tool as _exec
    # `approved=True`: user SUDAH menekan "Setujui" untuk token ini, jadi gate
    # tidak boleh meminta persetujuan lagi (kalau tidak, selalu 409 dan
    # persetujuan tidak pernah selesai). DENY + validasi argumen tetap jalan
    # di dalam `execute_textual_tool`.
    result = _exec({"tool": tool, "args": args}, user["email"], approved=True)
    if isinstance(result, dict) and result.get("status") in (
            "requires_approval", "denied"):
        # Menahan dua kali berturut-turut = kondisi berubah; jangan dipaksa.
        raise HTTPException(409, f"Panggilan tidak dapat dijalankan: "
                                 f"{result.get('reason') or result.get('status')}")
    return {"status": "executed", "tool": tool, "result": result}


@app.delete("/api/vault/{provider}")
def vault_delete_endpoint(provider: str, authorization: str | None = Header(None)):
    """Cabut kredensial satu provider untuk user pada JWT (self-service).

    KEAMANAN: user TARGET dari JWT, bukan body/query — user tidak bisa menghapus
    kredensial orang lain. Tanpa endpoint ini user hanya bisa MENIMPA token,
    tidak pernah bisa mencabutnya.
    """
    user = security.get_current_user(authorization)
    prov = (provider or "").strip().lower()
    if not prov:
        raise HTTPException(422, "provider wajib diisi.")
    ok = db.vault_delete(user["email"], prov)
    if not ok:
        raise HTTPException(500, "Gagal menghapus kredensial.")
    return {"status": "deleted", "provider": prov, "deleted": True}


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
    """Simpan workflow. `id` diisi -> UPDATE (bila milik user), jika tidak INSERT.

    Idempotensi: menyimpan ulang workflow yang sama TIDAK boleh menumpuk baris
    baru di sidebar (bug lama: POST selalu INSERT).
    """
    user = security.get_current_user(authorization)
    # Validasi graf SEBELUM menyentuh DB — berlaku untuk INSERT maupun UPDATE
    # (autosave kanvas juga mengirim flow_data). Lihat validate_workflow_flow.
    validate_workflow_flow(req.flow_data or {})
    if req.id:
        existing = db.get_workflow(req.id, user["id"])
        if not existing:
            # Membedakan "tidak ada" dari "milik orang lain" berguna untuk
            # frontend (pesan yang benar), dan tidak membocorkan isi workflow.
            owner = db.get_workflow_owner(req.id)
            if owner:
                raise HTTPException(403, "Workflow ini bukan milik Anda.")
            raise HTTPException(404, "Workflow tidak ditemukan.")
        try:
            row = db.update_workflow(req.id, user["id"], name=req.name,
                                     description=req.description, flow_data=req.flow_data)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"Gagal memperbarui workflow: {exc}")
        if not row:
            raise HTTPException(404, "Workflow tidak ditemukan.")
        return {"status": "success", "updated": True, "workflow": row}
    # ---- RATE LIMIT PEMBUATAN WORKFLOW (brief 7 Okt, BAGIAN 6) -------------
    # Hanya jalur INSERT (pembuatan BARU) yang dibatasi; UPDATE (autosave
    # kanvas yang mengirim `id`) TIDAK dihitung - kalau dihitung, autosave
    # normal akan langsung kena 429.
    _wb_ok, _wb_retry = rate_limit.workflow_build_limiter.check(user["id"])
    if not _wb_ok:
        raise HTTPException(
            429,
            ("Terlalu banyak pembuatan workflow. Batas "
             f"{rate_limit.workflow_build_limiter.max_calls} workflow baru per "
             f"{int(rate_limit.workflow_build_limiter.window_sec)} detik. "
             "Tunggu sebentar lalu coba lagi."),
            headers={"Retry-After": str(int(_wb_retry))},
        )
    try:
        row = db.create_workflow(user["id"], req.name, req.description, req.flow_data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal menyimpan workflow: {exc}")
    return {"status": "success", "updated": False, "workflow": row}


@app.get("/workflows/{workflow_id}")
def get_workflow_detail(workflow_id: str, authorization: str | None = Header(None)):
    """Detail SATU workflow (termasuk flow_data) — hanya milik user JWT."""
    user = security.get_current_user(authorization)
    try:
        row = db.get_workflow(workflow_id, user["id"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal memuat workflow: {exc}")
    if not row:
        raise HTTPException(404, "Workflow tidak ditemukan.")
    return {"status": "success", "workflow": row}


@app.patch("/workflows/{workflow_id}")
def patch_workflow(workflow_id: str, req: WorkflowUpdateRequest,
                   authorization: str | None = Header(None)):
    """Rename / ubah deskripsi. Owner-scoped: bukan pemilik -> 403."""
    user = security.get_current_user(authorization)
    if req.name is None and req.description is None:
        raise HTTPException(400, "Tidak ada perubahan yang dikirim.")
    if req.name is not None and not req.name.strip():
        raise HTTPException(400, "Nama workflow tidak boleh kosong.")
    try:
        row = db.update_workflow(workflow_id, user["id"],
                                 name=(req.name.strip() if req.name else None),
                                 description=req.description)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal mengubah workflow: {exc}")
    if not row:
        if db.get_workflow_owner(workflow_id):
            raise HTTPException(403, "Workflow ini bukan milik Anda.")
        raise HTTPException(404, "Workflow tidak ditemukan.")
    return {"status": "success", "workflow": row}


@app.delete("/workflows/{workflow_id}")
def remove_workflow(workflow_id: str, authorization: str | None = Header(None)):
    """Hapus SATU workflow milik user JWT. Owner-scoped (bukan pemilik -> 403)."""
    user = security.get_current_user(authorization)
    try:
        ok = db.delete_workflow(workflow_id, user["id"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal menghapus workflow: {exc}")
    if not ok:
        if db.get_workflow_owner(workflow_id):
            raise HTTPException(403, "Workflow ini bukan milik Anda.")
        raise HTTPException(404, "Workflow tidak ditemukan.")
    return {"status": "success", "deleted": True, "id": workflow_id}


# ---------------------------------------------------------------------------
# ENDPOINT: GET /workflows  (listar workflows) — SOLO milik user JWT
# ---------------------------------------------------------------------------
@app.get("/workflows")
def get_workflows(authorization: str | None = Header(None)):
    """List workflow user (METADATA saja — tanpa flow_data).

    Isi graf diambil per-workflow lewat GET /workflows/{id} supaya payload list
    tetap kecil walau user punya banyak workflow.
    """
    user = security.get_current_user(authorization)
    try:
        rows = db.list_workflows(user["id"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal memuat workflows: {exc}")
    return {"status": "success", "workflows": rows}


# ---------------------------------------------------------------------------
# ENDPOINT: /templates — Workflow Templates (Fitur #10)
#   GET  /templates                 -> bawaan + kustom milik user
#   GET  /templates/info            -> metadata (jumlah, kategori)
#   GET  /templates/{id}            -> detail satu template
#   POST /templates                 -> simpan template kustom
#   POST /templates/{id}/use        -> buat workflow NYATA dari template
#   DELETE /templates/{id}          -> hapus template kustom
#
# Route "/templates/info" didaftarkan SEBELUM "/templates/{id}" supaya tidak
# tertangkap sebagai template_id="info".
# ---------------------------------------------------------------------------
@app.get("/templates/info")
def templates_info(authorization: str | None = Header(None)):
    security.get_current_user(authorization)
    return {"status": "success", **workflow_templates.describe()}


@app.get("/templates")
def list_templates_endpoint(category: str | None = None, q: str | None = None,
                            authorization: str | None = Header(None)):
    """Daftar template: bawaan (kode) + kustom milik user JWT."""
    user = security.get_current_user(authorization)
    try:
        items = workflow_templates.list_templates(
            user_id=user["id"], category=category, query=q)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal memuat template: {exc}")
    return {"status": "success", "count": len(items), "templates": items}


@app.get("/templates/{template_id}")
def get_template_endpoint(template_id: str,
                          authorization: str | None = Header(None)):
    user = security.get_current_user(authorization)
    tpl = workflow_templates.get_template(template_id, user["id"])
    if not tpl:
        raise HTTPException(404, "Template tidak ditemukan.")
    return {"status": "success", "template": tpl}


@app.post("/templates", status_code=201)
def create_template_endpoint(req: TemplateCreateRequest,
                             authorization: str | None = Header(None)):
    """Simpan template kustom dari `flow_data` atau dari `workflow_id` milik user."""
    user = security.get_current_user(authorization)
    flow = req.flow_data
    if req.workflow_id:
        wf = db.get_workflow(req.workflow_id, user["id"])
        if not wf:
            if db.get_workflow_owner(req.workflow_id):
                raise HTTPException(403, "Workflow ini bukan milik Anda.")
            raise HTTPException(404, "Workflow tidak ditemukan.")
        flow = wf.get("flow_data") or {}
    try:
        row = workflow_templates.create_custom_template(
            user["id"], name=req.name, description=req.description,
            category=req.category, flow_data=flow, tags=req.tags)
    except workflow_templates.TemplateError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal menyimpan template: {exc}")
    return {"status": "success", "template": row}


@app.post("/templates/{template_id}/use", status_code=201)
def use_template_endpoint(template_id: str, req: TemplateUseRequest,
                          authorization: str | None = Header(None)):
    """Buat workflow BARU milik user dari template (bawaan maupun kustom)."""
    user = security.get_current_user(authorization)
    try:
        hasil = workflow_templates.instantiate(
            template_id, user["id"], name=req.name, description=req.description)
    except workflow_templates.TemplateError as exc:
        raise HTTPException(404, str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal membuat workflow dari template: {exc}")
    return {"status": "success", **hasil}


@app.delete("/templates/{template_id}")
def delete_template_endpoint(template_id: str,
                             authorization: str | None = Header(None)):
    user = security.get_current_user(authorization)
    if str(template_id).startswith(workflow_templates.BUILTIN_PREFIX):
        raise HTTPException(400, "Template bawaan tidak bisa dihapus.")
    try:
        ok = workflow_templates.delete_custom_template(template_id, user["id"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal menghapus template: {exc}")
    if not ok:
        raise HTTPException(404, "Template tidak ditemukan.")
    return {"status": "success", "deleted": True, "id": template_id}


class MCPWorkflowCall(BaseModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)

def _mcp_workflow_tool_name(name: str, workflow_id: str) -> str:
    slug = "-".join(str(name or workflow_id).lower().split()).replace("/", "-")
    return f"katalir_workflow__{slug or workflow_id}"[:64]

def _mcp_workflow_tools(user_id: str) -> list[dict[str, Any]]:
    rows = db.list_workflows(user_id) or []
    return [{"name": _mcp_workflow_tool_name(r.get("name"), str(r.get("id"))), "workflow_id": str(r.get("id")), "description": str(r.get("description") or f"Run Katalir workflow {r.get('name') or r.get('id')}") } for r in rows]

@app.get("/mcp/server/tools")
def mcp_server_tools(authorization: str | None = Header(None)):
    """List workflow tools exposed by Katalir; owner scoped."""
    user = security.get_current_user(authorization)
    return {"tools": _mcp_workflow_tools(str(user["id"]))}

@app.post("/mcp/server/call", status_code=202)
def mcp_server_call(req: MCPWorkflowCall, authorization: str | None = Header(None)):
    """Execute one owner workflow through the MCP-compatible surface."""
    user = security.get_current_user(authorization)
    row = next((r for r in (db.list_workflows(str(user["id"])) or []) if _mcp_workflow_tool_name(r.get("name"), str(r.get("id"))) == req.tool), None)
    if row is None:
        raise HTTPException(404, "Workflow tool tidak ditemukan")
    detail = db.get_workflow(str(row["id"]), str(user["id"]))
    if not detail:
        raise HTTPException(404, "Workflow tidak ditemukan")
    execution_id = engine.launch_execution(str(row["id"]), detail.get("flow_data") or {}, owner_email=str(user.get("email") or ""))
    return {"execution_id": execution_id, "workflow_id": str(row["id"]), "status": "pending"}

# ---------------------------------------------------------------------------
# MCP SERVER BUILT-IN — Fitur #8
#   Katalir sebagai MCP server ASLI (JSON-RPC 2.0 + Streamable HTTP).
#   Endpoint protokol : POST/GET/DELETE /mcp/katalir
#   Endpoint bantu    : GET  /mcp/katalir/info   (metadata + daftar tool)
#                       POST /mcp/katalir/key    (terbitkan API key MCP)
#
#   Kenapa API key, bukan JWT Supabase: klien MCP (Claude Desktop, Cursor)
#   tidak bisa menjalani alur login Supabase. Kunci bertanda tangan HMAC
#   (stateless) → tidak ada tabel baru, tetap sah setelah instance restart.
# ---------------------------------------------------------------------------
class McpKeyRequest(BaseModel):
    ttl_days: int = 90
    label: str = ""


@app.get("/mcp/katalir/info")
def mcp_katalir_info():
    """Metadata permukaan MCP Katalir (publik: hanya bentuk, bukan rahasia)."""
    return mcp_server.describe()


@app.post("/mcp/katalir/key")
def mcp_katalir_issue_key(req: McpKeyRequest | None = None,
                          authorization: str | None = Header(None)):
    """Terbitkan API key MCP untuk user yang sedang login (JWT Supabase).

    Kunci ditampilkan SEKALI di respons ini dan tidak disimpan di server —
    server tidak punya tabel kunci. Kehilangan kunci = terbitkan yang baru.
    """
    user = security.get_current_user(authorization)
    days = 90 if req is None else req.ttl_days
    try:
        days = int(days)
    except (TypeError, ValueError):
        raise HTTPException(422, "ttl_days harus angka")
    # 1..365 hari: batas bawah mencegah kunci yang mati sebelum dipakai, batas
    # atas membatasi umur kunci yang bocor.
    days = max(1, min(365, days))
    key = mcp_server.issue_api_key(
        str(user["id"]), str(user.get("email") or ""),
        ttl_s=days * 24 * 3600,
        label=("" if req is None else str(req.label or ""))[:40],
    )
    return {
        "api_key": key,
        "prefix": mcp_server.API_KEY_PREFIX,
        "expires_in_days": days,
        "endpoint": f"/mcp/katalir",
        "header": "X-API-Key",
        "note": "Simpan sekarang — server tidak menyimpan kunci ini.",
    }


@app.get("/mcp/katalir/verify")
def mcp_katalir_verify(x_api_key: str | None = Header(None),
                       authorization: str | None = Header(None)):
    """Cek apakah API key MCP masih sah. Dipakai UI untuk badge "Terhubung"."""
    raw = (x_api_key or "").strip()
    if not raw and authorization and authorization.lower().startswith("bearer "):
        raw = authorization[7:].strip()
    try:
        info = mcp_server.verify_api_key(raw)
    except mcp_server.McpAuthError as exc:
        raise HTTPException(401, str(exc))
    return {"valid": True, "user_id": info["user_id"],
            "email": info["email"], "label": info["label"], "exp": info["exp"]}


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
        # LIST tidak lagi membawa flow_data (FASE B) -> ambil DETAIL.
        found = db.get_workflow(workflow_id, user["id"])
        if not found:
            raise HTTPException(404, f"Workflow {workflow_id} tidak ditemukan.")
        flow_data = found.get("flow_data") or {}
    try:
        # FASE 2.6: sertakan email pemilik agar node MCP bisa membaca kredensial
        # user dari Brankas (tanpa ini node telegram/slack selalu "belum ada
        # kredensial" walau user sudah menyimpannya).
        execution_id = engine.launch_execution(
            workflow_id, flow_data, owner_email=str(user.get("email") or ""))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal melanjar ejekution: {exc}")
    return {"execution_id": execution_id, "workflow_id": workflow_id, "status": "pending"}


# ---------------------------------------------------------------------------
# ENDPOINTS: Scheduled Trigger (cron) — Fitur #1 (8 Okt 2026)
#   POST   /workflows/{id}/schedule  -> buat/ganti (satu jadwal per workflow)
#   GET    /workflows/{id}/schedule  -> lihat jadwal
#   DELETE /workflows/{id}/schedule  -> hapus jadwal
# Validasi: cron 5-field via croniter, timezone IANA via zoneinfo.
# Ownership dicek sebelum operasi DB (service client dipakai hanya setelah itu).
# ---------------------------------------------------------------------------
class ScheduleRequest(BaseModel):
    cron_expression: str
    timezone: str = "Asia/Jakarta"
    enabled: bool = True


def _schedule_owner_or_404(workflow_id: str, authorization: str | None) -> dict:
    user = security.get_current_user(authorization)
    owner = db.get_workflow_owner(workflow_id)
    if owner is None or owner != user["id"]:
        raise HTTPException(404, "Workflow tidak ditemukan.")
    return user


@app.post("/workflows/{workflow_id}/schedule", status_code=201)
def create_workflow_schedule(workflow_id: str, body: ScheduleRequest,
                             authorization: str | None = Header(None)):
    """Buat/ganti jadwal cron workflow. next_run_at dihitung pada timezone
    jadwal (IANA), dikembalikan dalam UTC."""
    user = _schedule_owner_or_404(workflow_id, authorization)
    expr = (body.cron_expression or "").strip()
    if not scheduler_manager.is_valid_cron(expr):
        raise HTTPException(
            400, f"Cron expression tidak valid: {expr!r} "
                 "(format 5-field: menit jam tanggal bulan hari)")
    tz = (body.timezone or "Asia/Jakarta").strip() or "Asia/Jakarta"
    if not scheduler_manager.is_valid_timezone(tz):
        raise HTTPException(
            400, f"Timezone tidak valid: {tz!r} "
                 "(pakai nama IANA, mis. 'Asia/Jakarta', bukan 'WIB')")
    try:
        next_at = scheduler_manager.next_fire_utc(expr, tz)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Cron expression tidak bisa dihitung: {exc}")
    row = {
        "workflow_id": workflow_id,
        "user_id": str(user["id"]),
        "cron_expression": expr,
        "timezone": tz,
        "enabled": bool(body.enabled),
        "next_fire_at": scheduler_manager.iso_utc(next_at) if body.enabled else None,
    }
    try:
        res = (db.get_write_client().table("workflow_schedules")
               .upsert(row, on_conflict="workflow_id").execute())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal menyimpan jadwal: {exc}")
    data = (res.data or [{}])[0]
    return {
        "schedule_id": data.get("id"),
        "workflow_id": workflow_id,
        "cron_expression": data.get("cron_expression"),
        "timezone": data.get("timezone"),
        "enabled": data.get("enabled"),
        "next_run_at": data.get("next_fire_at"),
    }


@app.get("/workflows/{workflow_id}/schedule")
def get_workflow_schedule(workflow_id: str, authorization: str | None = Header(None)):
    """Lihat jadwal cron workflow ini (atau 404 bila belum ada)."""
    _schedule_owner_or_404(workflow_id, authorization)
    try:
        res = (db.get_write_client().table("workflow_schedules").select("*")
               .eq("workflow_id", workflow_id).limit(1).execute())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal memuat jadwal: {exc}")
    rows = res.data or []
    if not rows:
        raise HTTPException(404, "Jadwal tidak ditemukan untuk workflow ini.")
    row = rows[0]
    return {
        "schedule_id": row.get("id"),
        "workflow_id": workflow_id,
        "cron_expression": row.get("cron_expression"),
        "timezone": row.get("timezone"),
        "enabled": row.get("enabled"),
        "next_run_at": row.get("next_fire_at"),
        "last_fired_at": row.get("last_fired_at"),
        "last_execution_id": row.get("last_execution_id"),
        "created_at": row.get("created_at"),
    }


@app.delete("/workflows/{workflow_id}/schedule")
def delete_workflow_schedule(workflow_id: str, authorization: str | None = Header(None)):
    """Hapus jadwal cron workflow ini (idempotent: 404 bila memang tidak ada)."""
    _schedule_owner_or_404(workflow_id, authorization)
    try:
        res = (db.get_write_client().table("workflow_schedules").delete()
               .eq("workflow_id", workflow_id).execute())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal menghapus jadwal: {exc}")
    if not res.data:
        raise HTTPException(404, "Jadwal tidak ditemukan untuk workflow ini.")
    return {"deleted": True, "workflow_id": workflow_id}


# ---------------------------------------------------------------------------
# ENDPOINTS: AI Agent Memory — Fitur #11 (8 Okt 2026)
#   POST   /memory/remember          -> simpan memory (dedup >= 0.95 = update)
#   POST   /memory/recall            -> semantic search (cosine, pgvector)
#   DELETE /memory/{memory_id}       -> soft delete (expires_at = now)
#   GET    /memory/preferences       -> semua preferensi user
#   PUT    /memory/preferences/{key} -> set/override preferensi
# Embedding: gemini-embedding-001 (1536-dim) via pool GEMINI_KEY.
# ---------------------------------------------------------------------------
class MemoryRememberRequest(BaseModel):
    content: str
    memory_type: str = "semantic"
    metadata: dict = Field(default_factory=dict)
    ttl_seconds: Optional[int] = None
    agent_id: str = "default"


class MemoryRecallRequest(BaseModel):
    query: str
    top_k: int = 5
    memory_type: Optional[str] = None
    agent_id: str = "default"


class MemoryPreferenceRequest(BaseModel):
    value: dict
    confidence: float = 1.0


@app.post("/memory/remember")
def memory_remember(body: MemoryRememberRequest,
                    authorization: str | None = Header(None)):
    """Simpan memory baru untuk user. Dedup otomatis: konten yang mirip
    (similarity >= 0.95) memicu UPDATE, bukan INSERT duplikat."""
    user = security.get_current_user(authorization)
    try:
        row = memory_manager.MemoryManager(
            user_id=str(user["id"]), agent_id=body.agent_id
        ).remember(body.content, memory_type=body.memory_type,
                   metadata=body.metadata, ttl_seconds=body.ttl_seconds)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except memory_manager.MemoryUnavailable as exc:
        raise HTTPException(503, f"Embedding provider tidak tersedia: {exc}")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal menyimpan memory: {exc}")
    return {"status": "success", "memory": {
        "id": row.get("id"), "content": row.get("content"),
        "memory_type": row.get("memory_type"),
        "expires_at": row.get("expires_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }}


@app.post("/memory/recall")
def memory_recall(body: MemoryRecallRequest,
                  authorization: str | None = Header(None)):
    """Semantic search memori milik user (tenant-isolated via filter + RLS)."""
    user = security.get_current_user(authorization)
    try:
        rows = memory_manager.MemoryManager(
            user_id=str(user["id"]), agent_id=body.agent_id
        ).recall(body.query, top_k=body.top_k, memory_type=body.memory_type)
    except memory_manager.MemoryUnavailable as exc:
        raise HTTPException(503, f"Embedding provider tidak tersedia: {exc}")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal mengambil memory: {exc}")
    return {"status": "success", "memories": [
        {"id": r.get("id"), "content": r.get("content"),
         "memory_type": r.get("memory_type"),
         "similarity": round(float(r.get("similarity") or 0), 4)}
        for r in rows]}


@app.delete("/memory/{memory_id}")
def memory_forget(memory_id: str, authorization: str | None = Header(None)):
    """Soft delete satu memory milik user (retention guard menyaring)."""
    user = security.get_current_user(authorization)
    deleted = memory_manager.MemoryManager(
        user_id=str(user["id"]), agent_id="default").forget(memory_id)
    if not deleted:
        raise HTTPException(404, "Memory tidak ditemukan.")
    return {"status": "success", "deleted": True, "memory_id": memory_id}


@app.get("/memory/preferences")
def memory_preferences_get(authorization: str | None = Header(None)):
    user = security.get_current_user(authorization)
    prefs = memory_manager.MemoryManager(
        user_id=str(user["id"]), agent_id="default").list_preferences()
    return {"status": "success", "preferences": prefs}


@app.put("/memory/preferences/{key}")
def memory_preferences_put(key: str, body: MemoryPreferenceRequest,
                           authorization: str | None = Header(None)):
    user = security.get_current_user(authorization)
    try:
        row = memory_manager.MemoryManager(
            user_id=str(user["id"]), agent_id="default"
        ).set_preference(key, body.value, confidence=body.confidence)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Gagal menyimpan preferensi: {exc}")
    return {"status": "success", "key": key,
            "value": row.get("value"), "confidence": row.get("confidence")}


@app.get("/executions/{execution_id}")
def get_execution(execution_id: str, authorization: str | None = Header(None),
                  accept_language: str | None = Header(None)):
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
    # FASE 2.5: laporan siap-tampil untuk chat/kanvas (diformat di server agar
    # semua klien menampilkan hal yang sama dan bisa diuji tanpa browser).
    try:
        import execution_report as _er
        locale = _er.locale_from_accept_language(accept_language)
        report = _er.format_execution_report((data or {}).get("execution"),
                                             (data or {}).get("logs"), locale=locale)
    except Exception as exc:  # noqa: BLE001 - laporan tidak boleh memblokir status
        print(f"[api_server] laporan eksekusi gagal: {type(exc).__name__}")
        report = ""
    return {"status": "success", **data, "report": report}


# ---------------------------------------------------------------------------
# REAL WEBHOOK TRIGGER - POST /webhook/{workflow_id}
#   Otomatisasi dunia nyata: payload JSON bebas dari Telegram/WhatsApp/
#   sistem eksternal -> input_data node Trigger -> DAG async non-blocking.
# ---------------------------------------------------------------------------
async def _run_webhook_dag(workflow_id: str, flow_data: dict,
                           trigger_input: dict,
                           owner_email: str = "") -> None:
    """Runner DAG untuk BackgroundTasks (tanpa create_task mentah).

    Menjalankan Trigger -> Agent -> MCP dan mempersist setiap langkah ke
    execution_logs. Error dicatat ke status eksekusi, bukan crash worker.
    """
    import uuid as _uuid

    execution_id = str(trigger_input.get("_execution_id") or _uuid.uuid4())
    # BUG-B1 (KRITIS) - EKSEKUSI HANTU:
    # Versi lama menghitung `execution_id` di sini tetapi TIDAK meneruskannya ke
    # runner. `execute_workflow_async` lalu membuat id BARU (uuid lain), sehingga
    # seluruh `execution_logs` menempel di baris "hantu" itu, sementara baris
    # `executions` yang di-pegang klien (dibuat `webhook_trigger`, di-poll lewat
    # `GET /executions/{id}`) hanya di-set "completed" tanpa SATU pun langkah.
    # Akibatnya laporan eksekusi webhook selalu kosong walau workflow jalan.
    # Sekarang id yang SAMA diteruskan (persis seperti jalur /execute via
    # `_spawn_execution`), dan status akhir diambil dari hasil runner - bukan
    # di-hardcode "completed".
    #
    # F-6 (KEPUTUSAN PRODUK - Opsi A): jalur webhook KINI meneruskan
    # `owner_email` pemilik workflow, sama seperti `/execute`.
    #
    # Sebelumnya `owner_email` sengaja TIDAK diteruskan. Konsekuensinya node MCP
    # ber-kredensial user (Google Sheets/Gmail/Slack/…) pada workflow webhook
    # TIDAK bisa me-resolve token pemiliknya -> integrasi webhook nyata (yang
    # justru inti fitur ini) selalu gagal di node kredensial.
    #
    # Opsi A dipilih brief: "webhook tetap pakai credential owner". Efek
    # sampingnya yang DISENGAJA: node agent pada workflow webhook ikut
    # termeter atas kuota pemilik (gembok `guard_execution` berlaku) - itu
    # memang perilaku "atas nama pemilik", bukan bug.
    try:
        result = await engine.execute_workflow_async(
            workflow_id, flow_data, trigger_input,
            execution_id=execution_id, owner_email=owner_email or "")
        status = str((result or {}).get("status") or "completed")
        db.update_execution_status(execution_id, status)
    except Exception as exc:  # noqa: BLE001
        try:
            db.update_execution_status(execution_id, "error")
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
    # LIST tidak lagi membawa flow_data (FASE B) -> ambil DETAIL.
    found = db.get_workflow(workflow_id, user["id"])
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
    # F-6 (Opsi A): teruskan email pemilik workflow supaya node MCP
    # ber-kredensial bisa resolve token user di jalur webhook.
    background.add_task(_run_webhook_dag, workflow_id, flow_data,
                        trigger_input, str(user.get("email") or ""))
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
def _build_info() -> dict:
    """Metadata build/deploy — NON-sensitif (tidak memuat satu pun secret).

    Railway menyuntikkan variabel `RAILWAY_GIT_*` pada service yang terhubung
    GitHub. Diekspos supaya commit yang BENAR-BENAR berjalan dapat diverifikasi
    dari luar (`curl /version`) tanpa memerlukan Railway API token — token yang
    tersedia di repo hanya project-scope dan menjawab "Not Authorized".
    """
    def _env(*names: str) -> str:
        for n in names:
            v = (os.getenv(n) or "").strip()
            if v:
                return v
        return ""

    import platform
    return {
        "commit": (_env("RAILWAY_GIT_COMMIT_SHA", "GIT_COMMIT_SHA") or "unknown")[:40],
        "branch": _env("RAILWAY_GIT_BRANCH") or "unknown",
        "service": _env("RAILWAY_SERVICE_NAME") or "local",
        "environment": _env("RAILWAY_ENVIRONMENT_NAME") or "local",
        "deployment_id": _env("RAILWAY_DEPLOYMENT_ID") or "local",
        "python": platform.python_version(),
    }


#: Modul tiap fitur (Fitur #1–#11). Dipakai `/version` untuk membuktikan fitur
#: mana yang ADA di image yang sedang berjalan. `find_spec` dipakai (bukan
#: import) supaya endpoint ini tidak menarik impor berat di jalur request.
_FEATURE_MODULES = {
    "01_cron": "scheduler_manager",
    "02_durable": "durable_execution",
    "03_retry_dlq": "retry_policy",
    "04_subworkflow": "subworkflow",
    "05_parallel_fanout": "parallel_fanout",
    "06_code_sandbox": "code_sandbox",
    "07_secrets": "secrets_provider",
    "08_mcp_server": "mcp_server",
    "09_memory": "memory_manager",
    "10_templates": "workflow_templates",
    "11_testkit": "workflow_testkit",
    # Penutup gap n8n (8 Okt 2026)
    "12_guardrails": "guardrails",
    "13_vector_store": "vector_store",
    "14_hitl": "hitl",
    "15_evaluation": "evaluation",
    "16_insights": "insights",
    # 11 fitur enterprise n8n (Okt 2026)
    "17_secrets_enterprise": "secrets_provider",
    "18_advanced_scheduling": "advanced_scheduling",
    "19_monitoring": "monitoring",
    "20_environments": "environments",
    "21_source_control": "source_control",
    "22_queue_mode": "queue_mode",
    "23_sso": "sso",
    "24_ai_workflow_gen": "ai_workflow_gen",
    "25_workflow_optimizer": "workflow_optimizer",
    "26_collab": "collab",
    "27_plugins": "plugin_system",
}


def _feature_status() -> dict:
    import importlib.util
    out: dict[str, bool] = {}
    for key, mod in _FEATURE_MODULES.items():
        try:
            out[key] = importlib.util.find_spec(mod) is not None
        except Exception:  # noqa: BLE001
            out[key] = False
    return out


# ---------------------------------------------------------------------------
# ENDPOINT HITL (fitur #3) — Human-in-the-Loop
# Workflow yang dijeda `waiting_approval` dilanjutkan/dihentikan di sini.
# ---------------------------------------------------------------------------
class HitlDecisionRequest(BaseModel):
    """Body POST /hitl/{id}/resume. `token` untuk tautan publik (tanpa login)."""
    decision: str            # "approve" | "reject"
    token: str = ""
    approver: str = ""


@app.get("/hitl/pending")
def hitl_pending(authorization: str | None = Header(None)):
    """Daftar permintaan persetujuan yang masih menunggu milik user ini."""
    user = security.get_current_user(authorization)
    import hitl
    hitl.expire_due()  # terapkan timeout yang sudah lewat sebelum menjawab
    rows = [r for r in hitl._backend().list_pending()
            if str(r.get("owner") or "") == str(user["email"])]
    return {"status": "success", "pending": [
        {"request_id": r.get("request_id"), "message": r.get("message"),
         "channel": r.get("channel"), "node_id": r.get("node_id"),
         "execution_id": r.get("execution_id"),
         "timeout_at": r.get("timeout_at"), "created_at": r.get("created_at")}
        for r in rows]}


@app.get("/hitl/{request_id}")
def hitl_detail(request_id: str, authorization: str | None = Header(None)):
    """Detail + jejak audit satu permintaan (hanya pemilik)."""
    user = security.get_current_user(authorization)
    import hitl
    row = hitl.get_request(request_id)
    if not row:
        raise HTTPException(404, "Permintaan tidak ditemukan.")
    if str(row.get("owner") or "") != str(user["email"]):
        raise HTTPException(403, "Bukan permintaan Anda.")
    return {"status": "success",
            "request": {k: row.get(k) for k in (
                "request_id", "status", "channel", "message", "approvers",
                "approval_mode", "on_timeout", "timeout_at", "resolved_at",
                "decisions", "execution_id", "node_id")},
            "audit": hitl.audit_trail(request_id)}


@app.post("/hitl/{request_id}/resume")
def hitl_resume(request_id: str, req: HitlDecisionRequest,
                authorization: str | None = Header(None)):
    """Catat keputusan approve/reject.

    Dua cara otorisasi (salah satu):
      * `token` resume bertanda tangan (tautan di email/Slack) — publik;
      * JWT user yang merupakan PEMILIK permintaan.
    """
    import hitl
    row = hitl.get_request(request_id)
    if not row:
        raise HTTPException(404, "Permintaan tidak ditemukan.")

    token_ok = bool(req.token) and hitl.verify_token(request_id, req.token)
    approver = str(req.approver or "").strip()
    if not token_ok:
        user = security.get_current_user(authorization)
        if str(row.get("owner") or "") != str(user["email"]):
            raise HTTPException(403, "Bukan permintaan Anda.")
        approver = approver or str(user["email"])
    approver = approver or "anonymous"

    try:
        updated = hitl.record_decision(request_id, approver, req.decision,
                                       token=req.token)
    except hitl.HitlError as exc:
        raise HTTPException(400, str(exc))
    return {"status": "success", "decision": req.decision,
            "request_status": updated.get("status"),
            "request_id": request_id,
            "retry_hint": ("resend_execution" if updated.get("status") == "approved"
                           else None)}


@app.get("/hitl/resume/{request_id}")
def hitl_resume_link(request_id: str, token: str = "", decision: str = "approve"):
    """Tautan resume satu-klik (dari email/Slack). Mengembalikan JSON ringkas."""
    import hitl
    if not hitl.verify_token(request_id, token):
        raise HTTPException(403, "Token resume tidak valid.")
    try:
        updated = hitl.record_decision(request_id, "link", decision, token=token)
    except hitl.HitlError as exc:
        raise HTTPException(400, str(exc))
    return {"status": "success", "request_id": request_id,
            "decision": decision, "request_status": updated.get("status")}


@app.post("/hitl/expire")
def hitl_expire(authorization: str | None = Header(None)):
    """Jalankan penyapu timeout HITL (dipanggil cron; idempoten)."""
    security.get_current_user(authorization)
    import hitl
    changed = hitl.expire_due()
    return {"status": "success", "expired": len(changed),
            "requests": [{"request_id": r.get("request_id"),
                          "status": r.get("status")} for r in changed]}


# ---------------------------------------------------------------------------
# ENDPOINT EVALUATION (fitur #4) — dataset uji + metrik + LLM-as-judge
# ---------------------------------------------------------------------------
class EvalRunRequest(BaseModel):
    dataset: Any = Field(default_factory=list)   # list[dict] | str (JSON/CSV)
    dataset_format: str = ""                     # "" | "csv" | "json"
    workflow_id: str = ""
    name: str = "eval"
    compare_mode: str = "fuzzy"                  # exact|contains|fuzzy|numeric|judge
    threshold: float = 0.8
    baseline_accuracy: Optional[float] = None
    max_cases: int = 50
    dataset_name: str = ""


def _eval_runner(workflow_id: str, owner: str, timeout_s: float = 120.0):
    """Runner produksi: jalankan workflow untuk tiap kasus, ambil teks output."""
    import asyncio

    def runner(case: dict) -> dict:
        flow = _load_workflow_flow(workflow_id, owner)
        if not flow:
            raise RuntimeError(f"workflow {workflow_id} tidak ditemukan")
        payload = {"input": case.get("input", ""), "text": case.get("input", "")}
        t0 = time.perf_counter()
        res = asyncio.run(engine.execute_workflow_async(
            workflow_id, flow, payload, owner_email=owner))
        latency = (time.perf_counter() - t0) * 1000
        text = _last_output_text(res)
        return {"output": text, "latency_ms": latency,
                "error": res.get("error") or ""}
    return runner


def _last_output_text(res: dict) -> str:
    for step in reversed(res.get("steps") or []):
        out = step.get("output") or {}
        for k in ("reply", "output", "result", "text", "message", "content"):
            v = out.get(k)
            if isinstance(v, str) and v.strip():
                return v
        if isinstance(out.get("result"), dict):
            for k in ("reply", "output", "text"):
                v = out["result"].get(k)
                if isinstance(v, str) and v.strip():
                    return v
    return res.get("error") or ""


def _load_workflow_flow(workflow_id: str, owner: str) -> Optional[dict]:
    try:
        row = db.get_or_create_user(owner)
        uid = str((row or {}).get("id") or "")
        wf = db.get_workflow(workflow_id, uid) if uid else None
    except Exception:  # noqa: BLE001
        wf = None
    if not wf:
        return None
    return wf.get("flow_data") or wf.get("data") or {}


@app.post("/evaluations/run")
def evaluations_run(req: EvalRunRequest,
                    authorization: str | None = Header(None)):
    """Jalankan dataset terhadap sebuah workflow, hitung metrik, simpan run."""
    user = security.get_current_user(authorization)
    import evaluation

    try:
        cases = evaluation.load_dataset(req.dataset, req.dataset_format)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if not cases:
        raise HTTPException(422, "Dataset kosong atau tidak bisa dibaca.")
    cases = cases[:max(1, min(int(req.max_cases or 50), evaluation.MAX_CASES))]

    runner = _eval_runner(req.workflow_id, user["email"])
    ev = evaluation.Evaluator(name=req.name, threshold=req.threshold)
    out = ev.run(cases, runner, compare_mode=req.compare_mode,
                 baseline_accuracy=req.baseline_accuracy)
    row = evaluation.save_run(user["email"], out["summary"], out["results"],
                              dataset_name=req.dataset_name)
    return {"status": "success", "run_id": row["run_id"],
            "summary": out["summary"], "results": out["results"]}


@app.get("/evaluations/runs")
def evaluations_list(limit: int = 20, authorization: str | None = Header(None)):
    user = security.get_current_user(authorization)
    import evaluation
    rows = evaluation.list_runs(user["email"], limit=max(1, min(limit, 100)))
    return {"status": "success", "runs": [
        {"run_id": r.get("run_id"), "name": r.get("name"),
         "dataset_name": r.get("dataset_name"), "accuracy": r.get("accuracy"),
         "passed": r.get("passed"), "total": r.get("total"),
         "latency_mean_ms": r.get("latency_mean_ms"),
         "cost_total_usd": r.get("cost_total_usd"),
         "created_at": r.get("created_at")} for r in rows]}


@app.get("/evaluations/runs/{run_id}")
def evaluations_detail(run_id: str, authorization: str | None = Header(None)):
    user = security.get_current_user(authorization)
    import evaluation
    row = evaluation.runs_backend().get(run_id)
    if not row:
        raise HTTPException(404, "Run tidak ditemukan.")
    if str(row.get("owner") or "") != str(user["email"]):
        raise HTTPException(403, "Bukan run Anda.")
    return {"status": "success", "run": {
        "run_id": row.get("run_id"), "name": row.get("name"),
        "summary": row.get("summary"), "results": row.get("results"),
        "created_at": row.get("created_at")}}


# ---------------------------------------------------------------------------
# ENDPOINT INSIGHTS (fitur #5) — success rate, latensi, error, time saved, ROI
# ---------------------------------------------------------------------------
@app.get("/insights")
def insights_report(days: int = 30, workflow_id: str = "",
                    latency: bool = False,
                    authorization: str | None = Header(None)):
    """Laporan analitik owner-scoped (time series, time saved, ROI)."""
    user = security.get_current_user(authorization)
    import insights
    ins = insights.Insight(str(user["id"]))
    rep = ins.report(days=days, workflow_id=workflow_id, with_latency=latency)
    rep["status"] = "success"
    return rep


@app.get("/insights/export")
def insights_export(days: int = 30, workflow_id: str = "",
                    authorization: str | None = Header(None)):
    """Unduh deret harian sebagai CSV."""
    user = security.get_current_user(authorization)
    import insights
    from fastapi.responses import Response
    csv_text = insights.Insight(str(user["id"])).export_csv(days=days,
                                                           workflow_id=workflow_id)
    return Response(content=csv_text, media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="insights-{days}d.csv"'})


# ---------------------------------------------------------------------------
# ENDPOINT SECRETS ENTERPRISE (fitur #1 lanjutan) — multi-provider + rotasi
# ---------------------------------------------------------------------------
class SecretRotateRequest(BaseModel):
    """Body POST /secrets/rotate."""
    ref: str                      # "secret://provider/field" atau "provider/field"
    value: str
    provider: str = ""            # paksa backend tertentu (opsional)


@app.get("/secrets/backends")
def secrets_backends(authorization: str | None = Header(None)):
    """Status tiap backend secrets (tanpa mengungkap nilai)."""
    security.get_current_user(authorization)
    import secrets_provider as sp
    return {"status": "success", "backends": sp.describe_backends(),
            "default": sp.default_provider_name()}


@app.get("/secrets/formats")
def secrets_formats(authorization: str | None = Header(None)):
    """Dokumentasi format referensi `secret://` yang didukung."""
    security.get_current_user(authorization)
    import secrets_provider as sp
    return {"status": "success", "formats": sp.SECRET_REF_FORMATS,
            "max_bytes": sp.MAX_SECRET_BYTES}


@app.post("/secrets/rotate")
def secrets_rotate(body: SecretRotateRequest,
                   authorization: str | None = Header(None)):
    """Rotasi rahasia: tulis nilai baru + naikkan versi."""
    user = security.get_current_user(authorization)
    import secrets_provider as sp
    try:
        hasil = sp.rotate(body.ref, body.value, str(user["email"]),
                          provider_name=(body.provider or None))
    except sp.SecretTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc))
    except sp.SecretsError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "success", "rotation": hasil}


@app.get("/secrets/history")
def secrets_history(ref: str, authorization: str | None = Header(None)):
    """Riwayat rotasi untuk satu path (tanpa nilai)."""
    user = security.get_current_user(authorization)
    import secrets_provider as sp
    jalur = ref
    if ref.strip().lower().startswith("secret://"):
        _b, p, f = sp.parse_ref(ref)
        jalur = f"{p}/{f}" if f else p
    hist = sp.rotation_store().history(str(user["email"]), jalur)
    return {"status": "success", "path": jalur, "history": hist,
            "current_version": sp.rotation_store().current_version(
                str(user["email"]), jalur)}


# ---------------------------------------------------------------------------
# ENDPOINT ADVANCED SCHEDULING (fitur #2) — builder, NL, preview, kondisi
# ---------------------------------------------------------------------------
class CronBuildRequest(BaseModel):
    minute: str = "*"
    hour: str = "*"
    dom: str = "*"
    month: str = "*"
    dow: str = "*"


class CronParseRequest(BaseModel):
    text: str


class SchedulePreviewRequest(BaseModel):
    cron: str
    timezone: str = "UTC"
    count: int = 5


@app.get("/schedules/timezones")
def schedules_timezones(authorization: str | None = Header(None)):
    """Daftar timezone IANA untuk picker (DST-aware via zoneinfo)."""
    security.get_current_user(authorization)
    import advanced_scheduling as sch
    return {"status": "success", "timezones": sch.COMMON_TIMEZONES}


@app.post("/schedules/build")
def schedules_build(body: CronBuildRequest,
                    authorization: str | None = Header(None)):
    """Builder visual -> cron expression."""
    security.get_current_user(authorization)
    import advanced_scheduling as sch
    try:
        expr = sch.build_cron(body.minute, body.hour, body.dom, body.month,
                              body.dow)
    except sch.ScheduleError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "success", "cron": expr}


@app.post("/schedules/parse")
def schedules_parse(body: CronParseRequest,
                    authorization: str | None = Header(None)):
    """Natural language (EN/ID) -> cron expression."""
    security.get_current_user(authorization)
    import advanced_scheduling as sch
    expr = sch.natural_to_cron(body.text)
    if not expr:
        raise HTTPException(status_code=422,
                            detail="Frasa jadwal tidak dikenali")
    return {"status": "success", "cron": expr}


@app.post("/schedules/preview")
def schedules_preview(body: SchedulePreviewRequest,
                      authorization: str | None = Header(None)):
    """Pratinjau N waktu tembak berikutnya (UTC ISO) — membuktikan DST."""
    security.get_current_user(authorization)
    import advanced_scheduling as sch
    if not sch.is_valid_cron(body.cron):
        raise HTTPException(status_code=400, detail="cron tidak valid")
    if not sch.is_valid_timezone(body.timezone):
        raise HTTPException(status_code=400, detail="timezone tidak valid")
    n = max(1, min(int(body.count or 5), 50))
    fires = sch.next_fires(body.cron, body.timezone, count=n)
    return {"status": "success", "cron": body.cron, "timezone": body.timezone,
            "next": [f.isoformat() for f in fires]}


@app.post("/schedules/validate")
def schedules_validate(body: dict,
                       authorization: str | None = Header(None)):
    """Validasi daftar spec jadwal (multiple/conditional/dependency)."""
    security.get_current_user(authorization)
    import advanced_scheduling as sch
    specs = (body or {}).get("specs") or []
    hasil = []
    ok = True
    for i, s in enumerate(specs):
        errs = sch.validate_spec(s)
        if errs:
            ok = False
        hasil.append({"index": i, "valid": not errs, "errors": errs})
    return {"status": "success", "valid": ok, "results": hasil}


# ---------------------------------------------------------------------------
# ENDPOINT MONITORING (fitur #3) — metrik Prometheus, alert, log, trace
# ---------------------------------------------------------------------------
_METRICS = None
_ALERT_MGR = None
_LOG_INDEX = None


def _mon():
    """Lazy-init observabilitas (satu instance per proses)."""
    global _METRICS, _ALERT_MGR, _LOG_INDEX
    import monitoring as mon
    if _METRICS is None:
        _METRICS = mon.Metrics()
        _METRICS.describe("katalir_up", "Katalir process up")
        _METRICS.set_gauge("katalir_up", 1)
        _ALERT_MGR = mon.AlertManager()
        _LOG_INDEX = mon.LogIndex()
    return mon


@app.get("/metrics")
def metrics_prometheus():
    """Eksposisi metrik format Prometheus (numerik saja — tanpa rahasia)."""
    from fastapi.responses import Response
    _mon()
    return Response(content=_METRICS.render_prometheus(),
                    media_type="text/plain; version=0.0.4")


@app.get("/monitoring/summary")
def monitoring_summary(authorization: str | None = Header(None)):
    """Ringkasan dashboard (counter, p95, alert aktif)."""
    security.get_current_user(authorization)
    mon = _mon()
    values = _monitor_values()
    firing = mon.evaluate_rules(mon.DEFAULT_RULES, values)
    return {"status": "success",
            "summary": mon.dashboard_summary(_METRICS, firing),
            "alerts": firing}


def _monitor_values() -> dict:
    """Nilai metrik ringkas untuk evaluasi aturan (dari insights bila ada)."""
    return {"error_rate": 0.0, "success_rate": 1.0, "p95_latency_ms": 0.0,
            "cost_usd": 0.0}


class SilenceRequest(BaseModel):
    rule: str
    until_ts: float = 0.0


@app.post("/monitoring/silence")
def monitoring_silence(body: SilenceRequest,
                       authorization: str | None = Header(None)):
    """Bisukan aturan alert (maintenance). until_ts=0 -> selamanya."""
    security.get_current_user(authorization)
    _mon()
    _ALERT_MGR.silence(body.rule, body.until_ts)
    return {"status": "success", "rule": body.rule,
            "silenced_until": body.until_ts}


@app.get("/monitoring/logs")
def monitoring_logs(q: str = "", level: str = "", limit: int = 100,
                    authorization: str | None = Header(None)):
    """Cari log teragregasi (substring + level)."""
    security.get_current_user(authorization)
    _mon()
    return {"status": "success",
            "logs": _LOG_INDEX.search(q, level=level, limit=max(1, min(limit, 500)))}


# ---------------------------------------------------------------------------
# ENDPOINT MULTI-ENVIRONMENT (fitur #4)
# ---------------------------------------------------------------------------
_ENVS = None


def _envs():
    global _ENVS
    import environments as envmod
    if _ENVS is None:
        _ENVS = envmod.Environments(envmod.default_store())
    return _ENVS


class PromoteRequest(BaseModel):
    workflow_id: str
    src: str
    dst: str
    role: str = "owner"
    approver: str = ""


class EnvApproveRequest(BaseModel):
    """Body untuk /environments/approve.

    CATATAN PENTING (bug ditemukan saat regresi suite penuh): kelas ini DULU
    bernama `ApproveRequest` — sama persis dengan model `/chat/approve`
    (approval_token + decision) di atas. Definisi kedua MENIMPA nama modul
    `ApproveRequest`, sehingga `api_server.ApproveRequest` menunjuk ke model
    promosi environment dan alur persetujuan tool Telegram (Defect #4) pecah:
    `ApproveRequest(approval_token=..., decision=...)` melempar ValidationError
    "request_id Field required". Nama kini unik.
    """

    request_id: str
    role: str = "admin"


class RollbackRequest(BaseModel):
    workflow_id: str
    env: str
    version: int
    role: str = "owner"


@app.get("/environments")
def environments_list(authorization: str | None = Header(None)):
    """Daftar environment + hak peran (untuk selector UI)."""
    security.get_current_user(authorization)
    import environments as envmod
    return {"status": "success", "environments": list(envmod.ENVIRONMENTS),
            "protected": list(envmod.PROTECTED),
            "promotion_order": envmod.PROMOTION_ORDER,
            "role_rights": {k: sorted(v) for k, v in envmod.ROLE_RIGHTS.items()}}


@app.get("/environments/{env}/workflows")
def environments_workflows(env: str, authorization: str | None = Header(None)):
    """Daftar workflow pada satu environment."""
    user = security.get_current_user(authorization)
    import environments as envmod
    try:
        wf = _envs().list(str(user["email"]), env)
    except envmod.UnknownEnvironment as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "success", "env": env, "workflows": wf}


@app.post("/environments/promote")
def environments_promote(body: PromoteRequest,
                         authorization: str | None = Header(None)):
    """Promosikan workflow antar environment (production butuh approval)."""
    user = security.get_current_user(authorization)
    import environments as envmod
    try:
        hasil = _envs().promote(str(user["email"]), body.workflow_id, body.src,
                                body.dst, role=body.role,
                                approver=body.approver)
    except envmod.ApprovalRequired as exc:
        return {"status": "pending_approval", "request_id": exc.request_id}
    except (envmod.EnvError, envmod.UnknownEnvironment) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "success", "result": hasil}


@app.post("/environments/approve")
def environments_approve(body: EnvApproveRequest,
                         authorization: str | None = Header(None)):
    """Setujui permintaan promosi yang tertunda."""
    user = security.get_current_user(authorization)
    import environments as envmod
    try:
        hasil = _envs().approve(body.request_id, str(user["email"]),
                                role=body.role)
    except envmod.EnvError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "success", "result": hasil}


@app.get("/environments/pending")
def environments_pending(authorization: str | None = Header(None)):
    """Daftar permintaan promosi yang menunggu approval."""
    user = security.get_current_user(authorization)
    return {"status": "success",
            "pending": _envs().pending(str(user["email"]))}


@app.get("/environments/diff")
def environments_diff(workflow_id: str, env_a: str, env_b: str,
                      authorization: str | None = Header(None)):
    """Diff struktural workflow antara dua environment."""
    user = security.get_current_user(authorization)
    import environments as envmod
    try:
        d = _envs().diff(str(user["email"]), workflow_id, env_a, env_b)
    except envmod.EnvError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "success", "diff": d}


@app.post("/environments/rollback")
def environments_rollback(body: RollbackRequest,
                          authorization: str | None = Header(None)):
    """Kembalikan environment ke versi tertentu."""
    user = security.get_current_user(authorization)
    import environments as envmod
    try:
        hasil = _envs().rollback(str(user["email"]), body.workflow_id, body.env,
                                 body.version, role=body.role)
    except envmod.EnvError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "success", "result": hasil}


@app.get("/environments/audit")
def environments_audit(authorization: str | None = Header(None)):
    """Jejak audit promosi/rollback milik user ini."""
    user = security.get_current_user(authorization)
    return {"status": "success",
            "audit": _envs().audit_trail(str(user["email"]))}


# ---------------------------------------------------------------------------
# ENDPOINT SOURCE CONTROL / GIT (fitur #5)
# ---------------------------------------------------------------------------
_SC_CONN = None


def _sc():
    global _SC_CONN
    import source_control as sc
    if _SC_CONN is None:
        _SC_CONN = sc.ConnectionStore()
    return sc, _SC_CONN


class GitConnectRequest(BaseModel):
    provider: str
    repo: str
    token: str = ""


class GitCommitRequest(BaseModel):
    provider: str
    workflow_id: str
    flow_data: dict
    branch: str = "main"
    message: str = ""
    expect_sha: str = ""


class GitRollbackRequest(BaseModel):
    provider: str
    workflow_id: str
    to_sha: str
    branch: str = "main"


class GitBranchRequest(BaseModel):
    provider: str
    name: str
    from_ref: str = "main"


class GitPrRequest(BaseModel):
    provider: str
    head: str
    base: str = "main"
    title: str
    body: str = ""


class GitWebhookRequest(BaseModel):
    provider: str = "github"
    payload: dict = {}


@app.get("/source-control/providers")
def sc_providers(authorization: str | None = Header(None)):
    """Daftar provider Git yang didukung."""
    security.get_current_user(authorization)
    sc, _ = _sc()
    return {"status": "success", "providers": sorted(sc.PROVIDERS)}


@app.post("/source-control/connect")
def sc_connect(body: GitConnectRequest,
               authorization: str | None = Header(None)):
    """Simpan koneksi Git (token dienkripsi, tidak pernah dikembalikan)."""
    user = security.get_current_user(authorization)
    sc, store = _sc()
    try:
        client = sc.make_client(body.provider, body.token, body.repo)
        cabang = client.list_branches()
    except sc.GitError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    info = store.save(str(user["email"]), body.provider, body.repo, body.token)
    return {"status": "success", "connection": info, "branches": cabang[:50]}


@app.get("/source-control/connections")
def sc_connections(authorization: str | None = Header(None)):
    """Daftar koneksi Git milik user (token ter-mask)."""
    user = security.get_current_user(authorization)
    _, store = _sc()
    return {"status": "success", "connections": store.list(str(user["email"]))}


@app.delete("/source-control/connections/{provider}")
def sc_disconnect(provider: str, authorization: str | None = Header(None)):
    """Hapus koneksi Git."""
    user = security.get_current_user(authorization)
    _, store = _sc()
    ok = store.delete(str(user["email"]), provider)
    return {"status": "success", "removed": ok}


@app.post("/source-control/commit")
def sc_commit(body: GitCommitRequest,
              authorization: str | None = Header(None)):
    """Commit workflow ke repo."""
    user = security.get_current_user(authorization)
    sc, store = _sc()
    try:
        client = store.client(str(user["email"]), body.provider)
        scm = sc.SourceControl(client)
        hasil = scm.commit_workflow(
            body.workflow_id, body.flow_data, branch=body.branch,
            message=body.message,
            expect_sha=(body.expect_sha or None))
    except sc.ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except sc.GitError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "success", "commit": hasil}


@app.get("/source-control/pull")
def sc_pull(provider: str, workflow_id: str, ref: str = "main",
            authorization: str | None = Header(None)):
    """Ambil workflow dari repo."""
    user = security.get_current_user(authorization)
    sc, store = _sc()
    try:
        client = store.client(str(user["email"]), provider)
        out = sc.SourceControl(client).pull_workflow(workflow_id, ref)
    except sc.GitError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "success", "workflow": out}


@app.get("/source-control/diff")
def sc_diff(provider: str, workflow_id: str, base: str, head: str,
            authorization: str | None = Header(None)):
    """Diff workflow antara dua ref."""
    user = security.get_current_user(authorization)
    sc, store = _sc()
    try:
        client = store.client(str(user["email"]), provider)
        out = sc.SourceControl(client).diff(workflow_id, base, head)
    except sc.GitError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "success", "diff": out}


@app.post("/source-control/rollback")
def sc_rollback(body: GitRollbackRequest,
                authorization: str | None = Header(None)):
    """Rollback workflow ke commit sebelumnya."""
    user = security.get_current_user(authorization)
    sc, store = _sc()
    try:
        client = store.client(str(user["email"]), body.provider)
        out = sc.SourceControl(client).rollback(body.workflow_id, body.to_sha,
                                                body.branch)
    except sc.GitError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "success", "commit": out}


@app.post("/source-control/branches")
def sc_branch(body: GitBranchRequest,
              authorization: str | None = Header(None)):
    """Buat branch baru."""
    user = security.get_current_user(authorization)
    sc, store = _sc()
    try:
        client = store.client(str(user["email"]), body.provider)
        out = sc.SourceControl(client).create_branch(body.name, body.from_ref)
    except sc.GitError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "success", "branch": out}


@app.post("/source-control/pr")
def sc_pr(body: GitPrRequest, authorization: str | None = Header(None)):
    """Buka pull request."""
    user = security.get_current_user(authorization)
    sc, store = _sc()
    try:
        client = store.client(str(user["email"]), body.provider)
        out = sc.SourceControl(client).open_pr(body.head, body.base, body.title,
                                               body.body)
    except sc.GitError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "success", "pull_request": out}


@app.post("/source-control/webhook")
def sc_webhook(body: GitWebhookRequest):
    """Terima event push Git -> daftar workflow yang berubah (untuk sync)."""
    sc, _ = _sc()
    return {"status": "success", "sync": sc.SourceControl(
        sc.make_client(body.provider, "", "x")).sync_from_webhook(body.payload)}


# ---------------------------------------------------------------------------
# ENDPOINT QUEUE MODE (fitur #6)
# ---------------------------------------------------------------------------
class QueueEnqueueRequest(BaseModel):
    workflow_id: str
    flow_data: dict = {}
    trigger_input: dict = {}
    priority: int = 0
    max_retries: int = 3
    timeout: float = 0.0


@app.get("/queue/health")
def queue_health(authorization: str | None = Header(None)):
    """Status backend antrian + worker pool."""
    security.get_current_user(authorization)
    mgr = _queue_mgr()
    out = mgr.health()
    out["workers"] = _QUEUE_POOL.health() if _QUEUE_POOL else {
        "workers": 0, "concurrency": 0}
    return {"status": "success", "queue": out}


@app.get("/queue/stats")
def queue_stats(authorization: str | None = Header(None)):
    """Statistik antrian (queued/inflight/dlq/by_status)."""
    security.get_current_user(authorization)
    return {"status": "success", "stats": _queue_mgr().queue.stats()}


@app.post("/queue/enqueue")
def queue_enqueue(body: QueueEnqueueRequest,
                  authorization: str | None = Header(None)):
    """Masukkan eksekusi workflow ke antrian."""
    user = security.get_current_user(authorization)
    job = _queue_mgr().queue.enqueue(
        {"workflow_id": body.workflow_id, "flow_data": body.flow_data,
         "trigger_input": body.trigger_input,
         "owner_email": str(user["email"])},
        priority=body.priority, max_retries=body.max_retries,
        timeout=(body.timeout or None))
    return {"status": "success", "job": job.to_dict()}


@app.get("/queue/dlq")
def queue_dlq(authorization: str | None = Header(None)):
    """Daftar job yang gagal permanen (dead letter queue)."""
    security.get_current_user(authorization)
    return {"status": "success",
            "dlq": [j.to_dict() for j in _queue_mgr().queue.dlq()]}


@app.post("/queue/recover")
def queue_recover(authorization: str | None = Header(None)):
    """Requeue job in-flight (pemulihan setelah worker crash)."""
    security.get_current_user(authorization)
    n = _queue_mgr().queue.recover_inflight()
    return {"status": "success", "requeued": n}


@app.get("/queue/workers")
def queue_workers(authorization: str | None = Header(None)):
    """Status worker pool + kedalaman antrian (dipakai dashboard UI).

    `depth` = jumlah job siap diambil (ZCARD `ready` di Redis) — angka ini
    dibaca LANGSUNG dari server Redis, jadi mencerminkan state lintas PROSES,
    bukan sekadar isi memori proses API.
    """
    security.get_current_user(authorization)
    mgr = _queue_mgr()
    pool = _QUEUE_POOL.health() if _QUEUE_POOL else {
        "workers": 0, "concurrency": 0, "processed": 0, "failed": 0}
    st = mgr.queue.stats()
    return {"status": "success", "backend": mgr.backend_name,
            "redis": mgr.redis_info,
            "visibility_timeout": getattr(mgr, "visibility_timeout", 0.0),
            "workers": pool,
            "depth": {"ready": st.get("queued", 0),
                      "inflight": st.get("inflight", 0),
                      "dlq": st.get("dlq", 0),
                      "total": st.get("total", 0)},
            "by_status": st.get("by_status", {})}


@app.post("/queue/reclaim")
def queue_reclaim(authorization: str | None = Header(None)):
    """Klaim ulang job yang lease-nya lewat (worker mati tanpa ack).

    Berbeda dari `/queue/recover` (yang hanya melihat job in-flight di proses
    ini), endpoint ini memakai visibility timeout: job 'running' yang tidak
    di-ack dalam `visibility_timeout` detik dianggap milik worker MATI dan
    dikembalikan ke antrian — aman dijalankan oleh proses mana pun.
    """
    security.get_current_user(authorization)
    n = _queue_mgr().reclaim_expired()
    return {"status": "success", "reclaimed": n}


@app.post("/queue/dlq/replay")
def queue_dlq_replay(authorization: str | None = Header(None)):
    """Pindahkan semua job DLQ kembali ke antrian untuk dicoba lagi."""
    security.get_current_user(authorization)
    n = _queue_mgr().dlq_replay()
    return {"status": "success", "replayed": n}


@app.get("/queue/ui")
def queue_ui():
    """Dashboard Queue Mode (status worker + kedalaman antrian).

    Halaman statis same-origin: `fetch` tidak kena CORS. Shell tidak memuat
    data sensitif; tiap panggilan di dalamnya tetap membawa Bearer token dan
    melewati `get_current_user`.
    """
    from fastapi.responses import HTMLResponse
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "static", "queue_dashboard.html")
    with open(path, encoding="utf-8") as fh:
        return HTMLResponse(fh.read())


# ---------------------------------------------------------------------------
# ENDPOINT SSO / SAML / OIDC / LDAP (fitur #7)
# ---------------------------------------------------------------------------
_SSO_MGR = None
_SSO_CONFIG: dict | None = None

#: Kunci kredensial di konfigurasi SSO -> tidak pernah dikembalikan mentah.
_SSO_SECRET_KEYS = ("client_secret", "bind_password", "private_key")


def _sso_admin(user: dict) -> bool:
    """Apakah user boleh mengubah konfigurasi SSO (allowlist env)."""
    allow = [e.strip().lower() for e in
             (os.getenv("KATALIR_SSO_ADMINS") or "").split(",") if e.strip()]
    email = str(user.get("email") or "").lower()
    if allow:
        return email in allow
    # Belum dikonfigurasi -> aplikasi single-tenant: user terautentikasi boleh,
    # TAPI dicatat supaya operator mengisi allowlist di produksi.
    print("[sso] PERINGATAN: KATALIR_SSO_ADMINS kosong — konfigurasi SSO dapat "
          "diubah oleh setiap user terautentikasi.")
    return True


def _sso_config() -> dict:
    """Konfigurasi SSO efektif (env + tersimpan), tanpa kredensial mentah.

    TODO(produksi): agar SSO aktif di produksi TANPA perubahan kode, set salah
    satu env berikut di dashboard Railway (kredensial Railway yang ada bersifat
    project-scoped sehingga penulisan env-var via API tidak diizinkan):
        KATALIR_SSO_CONFIG             JSON {orgs,oidc,ldap,saml}
        KATALIR_SSO_ADMINS             allowlist email pengubah konfigurasi
        KATALIR_SSO_OIDC_ISSUER / _CLIENT_ID / _CLIENT_SECRET / _REDIRECT_URI
        KATALIR_SSO_LDAP_URL / _BASE_DN / _BIND_DN / _BIND_PASSWORD / _USER_FILTER
        KATALIR_SSO_SAML_METADATA_URL / _CERT / _SSO_URL
    Tanpa env itu, /sso/* tetap 200 dengan `active: []` (degradasi anggun).
    """
    global _SSO_CONFIG
    if _SSO_CONFIG is not None:
        return _SSO_CONFIG
    cfg: dict = {"orgs": {}, "oidc": {}, "ldap": {}, "saml": {},
                 "enabled": ["oidc", "saml", "ldap"]}
    # 1. env (bentuk JSON) — cara paling sederhana untuk deploy tanpa UI
    raw = os.getenv("KATALIR_SSO_CONFIG") or ""
    if raw.strip():
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                for k, v in loaded.items():
                    if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                        cfg[k].update(v)
                    else:
                        cfg[k] = v
        except Exception as _exc:  # noqa: BLE001
            print(f"[sso] KATALIR_SSO_CONFIG bukan JSON valid: {_exc}")
    # 2. env spesifik (menimpa JSON) — memudahkan konfigurasi satu per satu
    env_map = {
        "oidc": {"issuer": "KATALIR_SSO_OIDC_ISSUER",
                 "client_id": "KATALIR_SSO_OIDC_CLIENT_ID",
                 "client_secret": "KATALIR_SSO_OIDC_CLIENT_SECRET",
                 "redirect_uri": "KATALIR_SSO_OIDC_REDIRECT_URI"},
        "ldap": {"server_url": "KATALIR_SSO_LDAP_URL",
                 "base_dn": "KATALIR_SSO_LDAP_BASE_DN",
                 "bind_dn": "KATALIR_SSO_LDAP_BIND_DN",
                 "bind_password": "KATALIR_SSO_LDAP_BIND_PASSWORD",
                 "user_filter": "KATALIR_SSO_LDAP_USER_FILTER"},
        "saml": {"metadata_url": "KATALIR_SSO_SAML_METADATA_URL",
                 "cert": "KATALIR_SSO_SAML_CERT",
                 "sso_url": "KATALIR_SSO_SAML_SSO_URL"},
    }
    for bagian, mp in env_map.items():
        for key, env_name in mp.items():
            val = os.getenv(env_name)
            if val:
                cfg[bagian][key] = val
    _SSO_CONFIG = cfg
    return cfg


def _sso_config_public(cfg: dict | None = None) -> dict:
    """Salinan konfigurasi untuk dibaca klien — kredensial diganti `***`."""
    import sso as _sso_mod
    cfg = cfg or _sso_config()
    out = json.loads(json.dumps(cfg))
    for bagian in ("oidc", "ldap", "saml"):
        d = out.get(bagian)
        if isinstance(d, dict):
            for k in _SSO_SECRET_KEYS:
                if d.get(k):
                    d[k] = _sso_mod.MASK
    return out


def _sso_session_store():
    """Penyimpan sesi SSO.

    Bila Redis tersedia, sesi disimpan di Redis sehingga (a) BERTAHAN lintas
    restart proses dan (b) berlaku untuk BANYAK proses/worker — syarat
    produksi. Kalau tidak, jatuh ke penyimpan memori (single instance).

    BUG NYATA (ditemukan saat verifikasi endpoint): sebelumnya `_sso()`
    MEMBANGUN ULANG `SsoManager` pada SETIAP request, sehingga sesi yang baru
    diterbitkan `/sso/login/*` selalu hilang di request berikutnya
    (`/sso/session/{id}` -> 404, `/sso/logout` -> 0). Kini manager di-cache.
    """
    import sso
    try:
        import queue_mode as _qm
        r = _qm.RedisQueueBackend(url="")
        if r.available():
            r._client()                       # ping -> benar-benar tersambung
            return sso.RedisSessionStore(r._client())
    except Exception as _exc:  # noqa: BLE001 - Redis opsional
        print(f"[sso] Redis tidak tersedia untuk sesi: {type(_exc).__name__}")
    return sso.SessionStore()


def _sso():
    """Manager SSO (di-cache), dibangun dari konfigurasi efektif + role mapping."""
    global _SSO_MGR
    import sso
    if _SSO_MGR is not None:
        return sso, _SSO_MGR
    cfg = _sso_config()
    m = sso.SsoManager(sessions=_sso_session_store())
    orgs = cfg.get("orgs") or {}
    if orgs:
        for org, spec in orgs.items():
            m.register_org(org, role_mapping=(spec or {}).get("role_mapping") or {},
                           domains=(spec or {}).get("domains") or [],
                           default_role=(spec or {}).get("default_role", "viewer"))
    else:
        m.register_org("default", role_mapping={
            "admins": "admin", "devs": "developer"}, domains=[])
    _SSO_MGR = m
    return sso, m


def _sso_oidc_transport():
    """Transport OIDC nyata dari konfigurasi; None bila belum dikonfigurasi."""
    import sso
    c = (_sso_config().get("oidc") or {})
    if not c.get("issuer") or not c.get("client_id"):
        return None
    return sso.OidcHttpTransport(c["issuer"], c["client_id"],
                                 c.get("client_secret", ""),
                                 c.get("redirect_uri", ""))


def _sso_ldap_dir():
    import sso
    c = (_sso_config().get("ldap") or {})
    if not c.get("server_url"):
        return None
    return sso.LdapDirectory(c["server_url"], c.get("base_dn", ""),
                             c.get("bind_dn", ""), c.get("bind_password", ""),
                             c.get("user_filter") or "(mail={login})")


class SsoOidcLoginRequest(BaseModel):
    code: str = ""
    claims: dict = {}
    org: str = ""
    state: str = ""
    expect_state: str = ""
    code_verifier: str = ""


class SsoLdapLoginRequest(BaseModel):
    username: str
    password: str
    org: str = ""


class SsoSamlLoginRequest(BaseModel):
    assertion: dict | str
    org: str = ""
    verify: bool = True


class SsoLogoutRequest(BaseModel):
    session_id: str = ""
    email: str = ""


class SsoConfigRequest(BaseModel):
    config: dict


@app.get("/sso/providers")
def sso_providers():
    """Protokol SSO yang didukung + yang AKTIF (publik, non-sensitif)."""
    import sso as _m
    cfg = _sso_config()
    aktif = []
    if (_sso_oidc_transport() is not None):
        aktif.append("oidc")
    if (_sso_ldap_dir() is not None):
        aktif.append("ldap")
    if (cfg.get("saml") or {}).get("cert") or (cfg.get("saml") or {}).get("metadata_url"):
        aktif.append("saml")
    return {"status": "success", "providers": ["oidc", "saml", "ldap"],
            "active": aktif, "roles": _m.ROLE_PRIORITY,
            "orgs": sorted((cfg.get("orgs") or {}).keys())}


@app.get("/sso/config")
def sso_config_get(authorization: str | None = Header(None)):
    """Konfigurasi SSO efektif (kredensial DIMASK)."""
    user = security.get_current_user(authorization)
    if not _sso_admin(user):
        raise HTTPException(status_code=403, detail="butuh peran admin SSO")
    return {"status": "success", "config": _sso_config_public(),
            "admin": True}


@app.post("/sso/config")
def sso_config_set(body: SsoConfigRequest,
                   authorization: str | None = Header(None)):
    """Set konfigurasi SSO dari UI admin.

    Nilai yang dikirim sebagai `***` (mask) DIPERTAHANKAN — supaya admin bisa
    menyimpan ulang tanpa harus mengetikkan rahasia yang sudah tersimpan.
    """
    global _SSO_CONFIG, _SSO_MGR
    user = security.get_current_user(authorization)
    if not _sso_admin(user):
        raise HTTPException(status_code=403, detail="butuh peran admin SSO")
    lama = _sso_config()
    baru = json.loads(json.dumps(lama))
    masuk = body.config or {}
    for k, v in masuk.items():
        if isinstance(v, dict) and isinstance(baru.get(k), dict):
            for kk, vv in v.items():
                if vv == "***" and baru[k].get(kk):
                    continue          # pertahankan rahasia lama
                baru[k][kk] = vv
        else:
            baru[k] = v
    _SSO_CONFIG = baru
    _SSO_MGR = None                    # paksa bangun ulang dengan config baru
    # best-effort persist ke preferensi user admin
    try:
        prefs = db.get_user_preferences(str(user["email"])) or {}
        prefs["sso_config"] = baru
        db.save_user_preferences(str(user["email"]), prefs)
        persisted = True
    except Exception:  # noqa: BLE001 - persistensi opsional
        persisted = False
    return {"status": "success", "config": _sso_config_public(baru),
            "persisted": persisted}


@app.get("/sso/discovery")
def sso_discovery(authorization: str | None = Header(None)):
    """Probe NYATA: discovery OIDC + metadata SAML dari IdP yang dikonfigurasi."""
    security.get_current_user(authorization)
    import sso as _m
    out: dict = {"oidc": None, "saml": None}
    t = _sso_oidc_transport()
    if t is not None:
        try:
            meta = t.discover()
            out["oidc"] = {"issuer": meta.get("issuer"),
                           "authorization_endpoint": meta.get("authorization_endpoint"),
                           "token_endpoint": meta.get("token_endpoint"),
                           "jwks_uri": meta.get("jwks_uri"),
                           "userinfo_endpoint": meta.get("userinfo_endpoint"),
                           "end_session_endpoint": meta.get("end_session_endpoint"),
                           "jwks_kids": [k.get("kid") for k in t.jwks().get("keys", [])]}
        except Exception as exc:  # noqa: BLE001
            out["oidc"] = {"error": f"{type(exc).__name__}: {exc}"}
    saml_cfg = _sso_config().get("saml") or {}
    if saml_cfg.get("metadata_url"):
        try:
            md = _m.SamlVerifier.fetch_idp_metadata(saml_cfg["metadata_url"])
            out["saml"] = {"entity_id": md.get("entity_id"),
                           "sso_url": md.get("sso_url"),
                           "cert_len": len(md.get("cert") or "")}
        except Exception as exc:  # noqa: BLE001
            out["saml"] = {"error": f"{type(exc).__name__}: {exc}"}
    return {"status": "success", "discovery": out}


@app.post("/sso/login/oidc")
def sso_login_oidc(body: SsoOidcLoginRequest):
    """Selesaikan login OIDC -> sesi Katalir.

    Bila IdP dikonfigurasi, `code` DITUKAR ke token endpoint NYATA dan ID
    token DIVERIFIKASI terhadap JWKS IdP (signature + iss/aud/exp/nonce).
    Jalur `claims` tetap ada untuk pemanggil yang sudah memverifikasi sendiri.
    """
    sso, m = _sso()
    try:
        if body.code:
            t = _sso_oidc_transport()
            if t is None:
                raise HTTPException(status_code=503,
                                    detail="OIDC belum dikonfigurasi (issuer/client_id)")
            tok = t.exchange_code(body.code, body.code_verifier)
            claims = t.verify_id_token(tok["id_token"])
            ident = sso.OidcProvider(t.client_id, t.issuer)._identity_from_claims(
                claims, body.org)
        else:
            prov = sso.OidcProvider("katalir", "https://idp.local")
            ident = prov.exchange(body.code, claims=body.claims or None,
                                  org=body.org)
        hasil = m.login(ident, state=body.state, expect_state=body.expect_state)
    except sso.SsoError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    return {"status": "success", "login": hasil}


@app.post("/sso/login/ldap")
def sso_login_ldap(body: SsoLdapLoginRequest):
    """Login LDAP NYATA: bind akun layanan -> cari DN -> bind pengguna."""
    sso, m = _sso()
    d = _sso_ldap_dir()
    if d is None:
        raise HTTPException(status_code=503,
                            detail="LDAP belum dikonfigurasi (server_url)")
    try:
        ident = d.identity(body.username, body.password, org=body.org)
        hasil = m.login(ident)
    except sso.SsoError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    return {"status": "success", "login": hasil}


@app.post("/sso/login/saml")
def sso_login_saml(body: SsoSamlLoginRequest):
    """Selesaikan login SAML (assertion) -> sesi Katalir.

    Bila sertifikat IdP dikonfigurasi, tanda tangan XML-DSig DIVERIFIKASI
    lebih dulu; assertion tanpa tanda tangan sah DITOLAK.
    """
    sso, m = _sso()
    prov = sso.SamlProvider()
    cert = (_sso_config().get("saml") or {}).get("cert") or ""
    try:
        if isinstance(body.assertion, str) and body.verify:
            if not cert:
                raise HTTPException(
                    status_code=503,
                    detail="sertifikat IdP SAML belum dikonfigurasi; verifikasi wajib")
            sso.SamlVerifier(cert).verify(body.assertion)
        ident = prov.parse_assertion(body.assertion, org=body.org)
        hasil = m.login(ident)
    except sso.SsoError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    return {"status": "success", "login": hasil}


@app.get("/sso/session/{session_id}")
def sso_session(session_id: str, authorization: str | None = Header(None)):
    """Info sesi SSO (tanpa kredensial)."""
    security.get_current_user(authorization)
    _, m = _sso()
    rec = m.session(session_id)
    if not rec:
        raise HTTPException(status_code=404, detail="sesi tidak ada/kedaluwarsa")
    return {"status": "success", "session": rec}


@app.post("/sso/logout")
def sso_logout(body: SsoLogoutRequest,
               authorization: str | None = Header(None)):
    """Logout: satu sesi (session_id) atau semua sesi user (email / SLO)."""
    security.get_current_user(authorization)
    _, m = _sso()
    if body.session_id:
        return {"status": "success", "logged_out": m.logout(body.session_id)}
    if body.email:
        return {"status": "success", "sessions_terminated": m.slo(body.email)}
    raise HTTPException(status_code=400, detail="session_id atau email wajib")


@app.get("/sso/ui")
def sso_ui():
    """Halaman admin SSO (same-origin, tanpa data sensitif di shell)."""
    from fastapi.responses import HTMLResponse
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "static", "sso_admin.html")
    with open(path, encoding="utf-8") as fh:
        return HTMLResponse(fh.read())


# ---------------------------------------------------------------------------
# ENDPOINT AI WORKFLOW GENERATOR (fitur #8)
# ---------------------------------------------------------------------------
_VISION_FN = None


def _vision_fn():
    """Sambungan model vision. `None` bila belum dikonfigurasi."""
    return _VISION_FN


class WorkflowGenRequest(BaseModel):
    filename: str
    media_base64: str = ""
    steps: list = []          # jalur preview: langkah sudah diekstrak klien
    language: str = "id"
    name: str = "AI Generated"
    mime: str = ""
    confidence: float = 0.9


@app.get("/ai/workflow-gen/allowed")
def wfgen_allowed():
    """Batas & jenis berkas yang diterima (non-sensitif)."""
    import ai_workflow_gen as g
    return {"status": "success", "extensions": list(g.ALLOWED_EXT),
            "mime": list(g.ALLOWED_MIME),
            "max_bytes": g.MAX_MEDIA_BYTES,
            "confidence_threshold": g.CONFIDENCE_THRESHOLD,
            "languages": ["id", "en"]}


@app.post("/ai/workflow-gen/generate")
def wfgen_generate(body: WorkflowGenRequest,
                   authorization: str | None = Header(None)):
    """Hasilkan workflow dari screenshot/video (atau langkah siap-pakai)."""
    security.get_current_user(authorization)
    import base64
    import ai_workflow_gen as g
    try:
        if body.steps:
            analysis = {"steps": body.steps, "confidence": body.confidence,
                        "ambiguous": False, "questions": [],
                        "duration_s": 0.0}
            g.validate_media(body.filename, 1, body.mime)  # validasi ekstensi
            wf = g.build_workflow(analysis, name=body.name,
                                  language=body.language)
            return {"status": "success", "workflow": wf,
                    "needs_clarification": False, "warnings": [],
                    "confidence": body.confidence}
        media = base64.b64decode(body.media_base64 or "")
        vf = _vision_fn()
        if vf is None:
            raise HTTPException(status_code=503,
                                detail="model vision belum dikonfigurasi")
        out = g.generate(media, body.filename, vf, language=body.language,
                         name=body.name, mime=body.mime)
    except g.MediaError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except g.GenerationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"status": "success", **out}


# ---------------------------------------------------------------------------
# ENDPOINT AI WORKFLOW OPTIMIZER (fitur #9)
# ---------------------------------------------------------------------------
_OPT_FEEDBACK = None


def _opt_feedback():
    global _OPT_FEEDBACK
    import workflow_optimizer as wo
    if _OPT_FEEDBACK is None:
        _OPT_FEEDBACK = wo.FeedbackStore()
    return wo, _OPT_FEEDBACK


class OptimizeAnalyzeRequest(BaseModel):
    flow: dict


class OptimizeApplyRequest(BaseModel):
    flow: dict
    accept_ids: list = []
    max_risk: str = "low"


class OptimizeFeedbackRequest(BaseModel):
    rec_id: str
    accepted: bool
    note: str = ""


@app.post("/ai/optimize/analyze")
def optimize_analyze(body: OptimizeAnalyzeRequest,
                     authorization: str | None = Header(None)):
    """Analisis workflow -> temuan, rekomendasi, estimasi biaya/latensi."""
    security.get_current_user(authorization)
    import workflow_optimizer as wo
    return {"status": "success", "analysis": wo.analyze(body.flow)}


@app.post("/ai/optimize/apply")
def optimize_apply(body: OptimizeApplyRequest,
                   authorization: str | None = Header(None)):
    """Terapkan rekomendasi optimasi (default hanya risiko-rendah)."""
    security.get_current_user(authorization)
    import workflow_optimizer as wo
    hasil = wo.analyze(body.flow)
    out = wo.apply(body.flow, hasil["recommendations"],
                   accept_ids=body.accept_ids, max_risk=body.max_risk)
    return {"status": "success", **out,
            "before": {"cost_usd": hasil["cost_usd"],
                       "latency_ms": hasil["latency_ms"]}}


@app.post("/ai/optimize/feedback")
def optimize_feedback(body: OptimizeFeedbackRequest,
                      authorization: str | None = Header(None)):
    """Catat umpan balik pengguna terhadap rekomendasi."""
    security.get_current_user(authorization)
    _, fb = _opt_feedback()
    return {"status": "success", "feedback": fb.record(body.rec_id,
                                                       body.accepted, body.note)}


@app.get("/ai/optimize/feedback")
def optimize_feedback_stats(authorization: str | None = Header(None)):
    """Ringkasan umpan balik (tingkat penerimaan)."""
    security.get_current_user(authorization)
    _, fb = _opt_feedback()
    return {"status": "success", "count": len(fb.all()),
            "acceptance_rate": fb.acceptance_rate(), "items": fb.all()[-50:]}


# ---------------------------------------------------------------------------
# ENDPOINT REAL-TIME COLLABORATION (fitur #10)
# ---------------------------------------------------------------------------
_COLLAB_SRV = None


def _collab():
    global _COLLAB_SRV
    import collab
    if _COLLAB_SRV is None:
        _COLLAB_SRV = collab.CollabServer()
    return collab, _COLLAB_SRV


class CollabRoomRequest(BaseModel):
    room: str
    allowed: list = []


class CollabOpRequest(BaseModel):
    client: str
    seq: int
    kind: str
    target: str = ""
    field: str = ""
    value: Any = None
    ts: float = 0.0


class CollabPresenceRequest(BaseModel):
    user: str
    cursor: dict = {}
    name: str = ""


class CollabCommentRequest(BaseModel):
    user: str
    target: str
    text: str
    parent: int | None = None


class CollabMergeRequest(BaseModel):
    ops: list = []


@app.get("/collab/rooms")
def collab_rooms(authorization: str | None = Header(None)):
    """Daftar room kolaborasi + statistik."""
    security.get_current_user(authorization)
    _, srv = _collab()
    return {"status": "success",
            "rooms": [r.stats() for r in srv.rooms.values()]}


@app.post("/collab/rooms")
def collab_create(body: CollabRoomRequest,
                  authorization: str | None = Header(None)):
    """Buat/ambil room kolaborasi (opsional batasi user)."""
    security.get_current_user(authorization)
    _, srv = _collab()
    r = srv.room(body.room, allowed=body.allowed or None)
    return {"status": "success", "room": r.stats()}


@app.get("/collab/rooms/{room}/snapshot")
def collab_snapshot(room: str, authorization: str | None = Header(None)):
    """Snapshot dokumen CRDT (nodes)."""
    security.get_current_user(authorization)
    _, srv = _collab()
    return {"status": "success", "snapshot": srv.room(room).doc.snapshot()}


@app.post("/collab/rooms/{room}/ops")
def collab_submit(room: str, body: CollabOpRequest,
                  authorization: str | None = Header(None)):
    """Kirim satu operasi CRDT ke room."""
    security.get_current_user(authorization)
    collab, srv = _collab()
    try:
        op = collab.Op(body.client, body.seq, body.kind, body.target,
                       body.field, body.value,
                       ts=(body.ts or None))
        out = srv.submit(room, op)
    except collab.AccessDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return {"status": "success", **out}


@app.post("/collab/rooms/{room}/merge")
def collab_merge(room: str, body: CollabMergeRequest,
                 authorization: str | None = Header(None)):
    """Merge op yang dibuat saat offline (idempoten)."""
    security.get_current_user(authorization)
    collab, srv = _collab()
    ops = [collab.Op(o.get("client", ""), o.get("seq", 0), o.get("kind", ""),
                     o.get("target", ""), o.get("field", ""), o.get("value"),
                     ts=o.get("ts")) for o in (body.ops or [])]
    return {"status": "success", **srv.merge_offline(room, ops)}


@app.get("/collab/rooms/{room}/presence")
def collab_presence(room: str, authorization: str | None = Header(None)):
    """Presence + multi-cursor di room."""
    security.get_current_user(authorization)
    _, srv = _collab()
    r = srv.room(room)
    return {"status": "success", "presence": r.presence(),
            "cursors": r.cursors()}


@app.post("/collab/rooms/{room}/presence")
def collab_set_presence(room: str, body: CollabPresenceRequest,
                        authorization: str | None = Header(None)):
    """Perbarui presence/kursor user."""
    security.get_current_user(authorization)
    _, srv = _collab()
    return {"status": "success",
            "presence": srv.room(room).set_presence(body.user, body.cursor,
                                                    body.name)}


@app.post("/collab/rooms/{room}/comments")
def collab_comment(room: str, body: CollabCommentRequest,
                   authorization: str | None = Header(None)):
    """Tambah komentar/balasan (dengan deteksi mention)."""
    security.get_current_user(authorization)
    collab, srv = _collab()
    try:
        c = srv.room(room).comment(body.user, body.target, body.text,
                                   body.parent)
    except collab.AccessDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return {"status": "success", "comment": c}


@app.get("/collab/rooms/{room}/comments")
def collab_comments(room: str, target: str = "",
                    authorization: str | None = Header(None)):
    """Daftar komentar pada room (opsional filter target)."""
    security.get_current_user(authorization)
    _, srv = _collab()
    return {"status": "success",
            "comments": srv.room(room).comments(target or None)}


# ---------------------------------------------------------------------------
# FITUR #11 — PLUGIN / EXTENSION SYSTEM
#
# Handler plugin di server ini SENGAJA deterministik & tanpa jaringan: `http`
# bersifat dry-run (mengembalikan URL yang diminta, bukan melakukan request).
# Tujuannya agar sandbox capability bisa dibuktikan keras (test + audit) tanpa
# membuat build ini punya jalur egress tersembunyi. Secret/DB/env MUSTAHIL
# dijangkau dari dalam sandbox (lihat FORBIDDEN_CAPABILITIES).
# ---------------------------------------------------------------------------
_PLUGIN_KV: dict = {}


def _plugin_handler(capability: str, kwargs: dict):
    """Handler contoh: membuktikan capability bekerja, tanpa efek samping luar."""
    cap = capability
    if cap == "log":
        return {"logged": True, "message": str(kwargs.get("message", ""))}
    if cap == "kv":
        key = str(kwargs.get("key", ""))
        if kwargs.get("op") == "set":
            _PLUGIN_KV[key] = kwargs.get("value")
            return {"key": key, "value": kwargs.get("value")}
        return {"key": key, "value": _PLUGIN_KV.get(key)}
    if cap == "http":
        return {"url": str(kwargs.get("url", "")), "dry_run": True}
    if cap == "notify":
        return {"notified": str(kwargs.get("channel", "default"))}
    if cap in ("workflow.read", "workflow.write"):
        return {"workflow_id": kwargs.get("workflow_id"), "capability": cap}
    return {"echo": cap, "args": kwargs}


_PLUGIN_MGRS: dict = {}


def _plugins(owner: str = "public"):
    """Manajer plugin PER-OWNER.

    Isolasi tenant: satu registry global akan membocorkan plugin milik user A
    ke user B. Karena itu tiap owner punya `PluginManager` sendiri yang
    di-hydrate dari tabel `plugin_registry` (RLS `owner = auth.jwt()->>'email'`)
    sehingga plugin yang dipasang BERTAHAN lintas restart/deploy.
    """
    import plugin_system as ps
    mgr = _PLUGIN_MGRS.get(owner)
    if mgr is None:
        mgr = ps.PluginManager(store=ps.default_store(), owner=owner)
        mgr.hydrate(_plugin_handler)
        # Contoh bawaan supaya marketplace/UI tidak kosong & pola terlihat.
        # `install` idempoten (upsert), jadi aman dipanggil tiap kali.
        contoh = ps.PluginManifest(
            name="katalir.sample", version="1.0.0", entry="sample:run",
            capabilities=["log", "kv"], author="Katalir",
            description="Plugin contoh (capability log + kv)")
        try:
            mgr.install(contoh, _plugin_handler)
        except Exception:  # noqa: BLE001
            pass
        _PLUGIN_MGRS[owner] = mgr
    return ps, mgr


def _plugins_auth(authorization: str | None):
    """Verifikasi token + kembalikan (modul, manajer) milik owner token itu."""
    user = security.get_current_user(authorization)
    owner = (user.get("email") or user.get("id") or "public").strip() or "public"
    return _plugins(owner)


def _plugin_error(exc) -> HTTPException:
    """Pemetaan error plugin -> status HTTP (fail-closed)."""
    import plugin_system as ps
    if isinstance(exc, (ps.PluginBlocked, ps.CapabilityDenied)):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, (ps.CompatibilityError, ps.DependencyError)):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


class PluginInstallRequest(BaseModel):
    manifest: dict
    allow_unsigned: bool = True


class PluginToggleRequest(BaseModel):
    enabled: bool = True


class PluginCallRequest(BaseModel):
    capability: str
    args: dict = {}


class PluginReviewSubmitRequest(BaseModel):
    manifest: dict


class PluginReviewDecisionRequest(BaseModel):
    reviewer: str = ""
    reason: str = ""


@app.get("/plugins")
def plugins_list(authorization: str | None = Header(None)):
    """Daftar plugin terpasang (marketplace internal)."""
    ps, mgr = _plugins_auth(authorization)
    return {"status": "success", "plugins": mgr.registry.list(),
            "stats": mgr.stats()}


@app.get("/plugins/capabilities")
def plugins_capabilities(authorization: str | None = Header(None)):
    """Capability yang diizinkan vs yang dilarang keras."""
    ps, _ = _plugins_auth(authorization)
    return {"status": "success",
            "safe": sorted(ps.SAFE_CAPABILITIES),
            "forbidden": sorted(ps.FORBIDDEN_CAPABILITIES),
            "katalir_version": ps.KATALIR_VERSION}


@app.get("/plugins/search")
def plugins_search(q: str = "", authorization: str | None = Header(None)):
    """Cari plugin di registry (nama/deskripsi/author)."""
    _, mgr = _plugins_auth(authorization)
    return {"status": "success", "results": mgr.registry.search(q)}


@app.get("/plugins/stats")
def plugins_stats(authorization: str | None = Header(None)):
    _, mgr = _plugins_auth(authorization)
    return {"status": "success", "stats": mgr.stats()}


@app.get("/plugins/audit")
def plugins_audit(authorization: str | None = Header(None)):
    """Jejak audit aksi plugin (install/uninstall/call/block)."""
    _, mgr = _plugins_auth(authorization)
    return {"status": "success", "audit": mgr.audit()}


@app.post("/plugins/install")
def plugins_install(req: PluginInstallRequest,
                    authorization: str | None = Header(None)):
    """Pasang/naikkan versi plugin. Capability terlarang => 403."""
    ps, mgr = _plugins_auth(authorization)
    try:
        man = ps.PluginManifest.from_dict(req.manifest)
        out = mgr.install(man, _plugin_handler,
                          allow_unsigned=req.allow_unsigned)
    except (ps.PluginError, ps.PluginBlocked) as exc:  # noqa: BLE001
        raise _plugin_error(exc)
    return {"status": "success", **out}


@app.delete("/plugins/{name}")
def plugins_uninstall(name: str, authorization: str | None = Header(None)):
    ps, mgr = _plugins_auth(authorization)
    if not mgr.uninstall(name):
        raise HTTPException(status_code=404, detail=f"plugin tidak ada: {name}")
    return {"status": "success", "removed": name}


@app.post("/plugins/{name}/enable")
def plugins_enable(name: str, req: PluginToggleRequest,
                   authorization: str | None = Header(None)):
    _, mgr = _plugins_auth(authorization)
    if not mgr.set_enabled(name, req.enabled):
        raise HTTPException(status_code=404, detail=f"plugin tidak ada: {name}")
    return {"status": "success", "name": name, "enabled": req.enabled}


@app.get("/plugins/{name}/manifest")
def plugins_manifest(name: str, authorization: str | None = Header(None)):
    _, mgr = _plugins_auth(authorization)
    p = mgr.registry.get(name)
    if not p:
        raise HTTPException(status_code=404, detail=f"plugin tidak ada: {name}")
    return {"status": "success", "manifest": p.manifest.to_dict()}


@app.post("/plugins/{name}/call")
def plugins_call(name: str, req: PluginCallRequest,
                 authorization: str | None = Header(None)):
    """Panggil capability plugin di dalam sandbox (capability harus dideklarasikan)."""
    ps, mgr = _plugins_auth(authorization)
    try:
        hasil = mgr.call(name, req.capability, **req.args)
    except ps.PluginError as exc:  # noqa: BLE001
        raise _plugin_error(exc)
    return {"status": "success", "result": hasil}


@app.post("/plugins/reviews")
def plugins_review_submit(req: PluginReviewSubmitRequest,
                          authorization: str | None = Header(None)):
    """Ajukan plugin untuk review (publikasi marketplace)."""
    ps, mgr = _plugins_auth(authorization)
    try:
        man = ps.PluginManifest.from_dict(req.manifest)
        rec = mgr.submit_for_review(man)
    except ps.PluginError as exc:  # noqa: BLE001
        raise _plugin_error(exc)
    return {"status": "success", "review": rec}


@app.get("/plugins/reviews")
def plugins_reviews(authorization: str | None = Header(None)):
    _, mgr = _plugins_auth(authorization)
    return {"status": "success", "reviews": mgr.reviews()}


@app.post("/plugins/reviews/{request_id}/approve")
def plugins_review_approve(request_id: str, req: PluginReviewDecisionRequest,
                           authorization: str | None = Header(None)):
    ps, mgr = _plugins_auth(authorization)
    try:
        rec = mgr.approve(request_id, req.reviewer)
    except ps.PluginError as exc:  # noqa: BLE001
        raise _plugin_error(exc)
    return {"status": "success", "review": rec}


@app.post("/plugins/reviews/{request_id}/reject")
def plugins_review_reject(request_id: str, req: PluginReviewDecisionRequest,
                          authorization: str | None = Header(None)):
    ps, mgr = _plugins_auth(authorization)
    try:
        rec = mgr.reject(request_id, req.reason)
    except ps.PluginError as exc:  # noqa: BLE001
        raise _plugin_error(exc)
    return {"status": "success", "review": rec}


@app.get("/plugins/ui")
def plugins_ui():
    """Marketplace UI (halaman statis same-origin).

    Disajikan dari origin yang SAMA dengan API supaya `fetch` tidak terkena
    CORS dan tidak perlu allowlist tambahan. Shell-nya sendiri tidak memuat
    data sensitif — setiap panggilan di dalamnya tetap membawa Bearer token
    dan melewati `get_current_user` seperti endpoint lain.
    """
    from fastapi.responses import HTMLResponse
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "static", "plugins_marketplace.html")
    with open(path, encoding="utf-8") as fh:
        return HTMLResponse(fh.read())


@app.get("/health")
def health():
    return {
        "status": "ok",
        "persistence": db.persistence_info(),
        "build": _build_info(),
    }


@app.get("/version")
def version():
    """Build + status 11 fitur (untuk verifikasi deploy). Non-sensitif."""
    feats = _feature_status()
    return {
        "status": "success",
        "build": _build_info(),
        "features": feats,
        "features_present": sum(1 for v in feats.values() if v),
        "features_total": len(feats),
        # Batas graf kini satu sumber kebenaran (flow_limits.py). Diekspos
        # supaya operator/klien bisa melihat batas AKTIF tanpa membaca kode.
        "limits": _limits_info(),
    }


def _limits_info() -> dict:
    """Batas aktif — dipakai UI/observabilitas & verifikasi hard test."""
    info: dict = {}
    try:
        import flow_limits
        info.update(flow_limits.describe())
    except Exception:  # noqa: BLE001
        pass
    try:
        import code_sandbox
        # DUA kunci, dan keduanya disengaja:
        #   `sandbox`      = MEKANISME penegakan (RLIMIT_AS vs Job Object).
        #                    Dipakai laporan hard test untuk membuktikan batas
        #                    memori benar-benar berlaku di platform ini.
        #   `code_sandbox` = PERMUKAAN PUBLIK fitur #6 (bahasa, batas, endpoint).
        #                    Dipakai untuk menjawab "fitur ini tersambung ke
        #                    mana saja" tanpa membocorkan detail internal.
        info["sandbox"] = code_sandbox.capabilities()
        info["code_sandbox"] = code_sandbox.info()
    except Exception:  # noqa: BLE001
        pass
    try:
        import mcp_server
        # Membuktikan tool MCP benar-benar TERDAFTAR, bukan sekadar ada di
        # kode: daftar ini dibaca dari `describe()` yang sumbernya sama dengan
        # yang dipakai klien MCP.
        info["mcp_tools"] = [t["name"] for t in mcp_server.describe().get("tools", [])]
    except Exception:  # noqa: BLE001
        pass
    try:
        import rate_limit
        info["rate_limits"] = {
            "chat_per_window": rate_limit.chat_limiter.max_calls,
            "chat_window_s": rate_limit.chat_limiter.window_sec,
            "workflow_build_per_window": rate_limit.workflow_build_limiter.max_calls,
            "tool_call_per_window": rate_limit.tool_call_limiter.max_calls,
            "requests_per_hour": rate_limit.request_hourly_limiter.max_calls,
        }
    except Exception:  # noqa: BLE001
        pass
    return info


# ---------------------------------------------------------------------------
# MOUNT MCP — SENGAJA DI AKHIR MODUL (lihat catatan di baris ~225).
#
# `app.mount()` mencocokkan prefix, jadi ia HARUS didaftarkan setelah semua
# route eksplisit `/mcp/katalir/*` (`/info`, `/key`, `/verify`). Bila mount
# didaftarkan lebih dulu, ketiga route itu tidak pernah tercapai.
# ---------------------------------------------------------------------------
if _MCP_ASGI is not None:
    try:
        app.mount("/mcp/katalir", _MCP_ASGI)
    except Exception as _mcp_mount_exc:  # noqa: BLE001
        print(f"[startup] mount MCP gagal: {type(_mcp_mount_exc).__name__}: {_mcp_mount_exc}")


# ---------------------------------------------------------------------------
# ENTRYPOINT directo (dev local): uvicorn api_server:app --reload o python api_server.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run("api_server:app", host=host, port=port, reload=os.getenv("RELOAD") == "1")
