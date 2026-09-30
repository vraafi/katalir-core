# agent_reasoner.py - Universal AI Router (Enterprise September 2026)
# =============================================================================
# Eksekutor untuk node AGENT, dibangun di atas framework agentic modern
# (LangChain Core + konektor provider) — BUKAN raw SDK.
#
# Universal AI Router (prioritas otonom dari .env):
#   1. GROQ_API_KEY            -> Groq (openai/gpt-oss-20b, live Sep 2026)
#   2. NVIDIA_API_KEY          -> NVIDIA NIM (integrate.api.nvidia.com/v1)
#   3. GITHUB_TOKEN/API_KEY    -> GitHub Models (models.inference.ai.azure.com)
#   4. GOOGLE_API_KEY dkk      -> Google Generative AI (gemma-4-31b-it)
#
# Fitur:
#   1. Tool Calling NATIVE via `bind_tools` (kompatibel NativeMCPClient).
#   2. Gembok Bahasa: selalu jawab Bahasa Indonesia (anti language drift).
#   3. Tidak crash tanpa key -> return {status: skipped, error} yang jelas.
#   4. Output "pemikiran" tersimpan ke execution_logs via output_data.
# =============================================================================

import os
from typing import Any

from dotenv_loader import load_repo_env

load_repo_env()

from langchain_core.tools import tool


# ---------------------------------------------------------------------------
# MCP Readiness - schema tool yang akan dikenali LLM (placeholder)
# ---------------------------------------------------------------------------
@tool
def mcp_tool_probe(tool_name: str, arguments: str) -> str:
    """Prototipe pemanggilan tool MCP secara agnostik.

    Args:
        tool_name: nama tool MCP (web_search, read_database, ...).
        arguments: string JSON berisi parameter tool.
    Returns:
        Hasil simulasi tool.
    """
    return f"[MCP::probe] tool={tool_name} args={arguments}"


TOOLS = [mcp_tool_probe]


# Gembok Bahasa - anti language drift (disisipkan ke setiap system prompt).
LANGUAGE_LOCK = (
    "CRITICAL RULE: You MUST always respond in Indonesian (Bahasa Indonesia) "
    "perfectly. Never use Spanish, Chinese, or other languages unless "
    "explicitly requested."
)


# ---------------------------------------------------------------------------
# Provider: ekosistem Google (Google AI Studio) — prioritas utama.
#   GOOGLE_API_KEY (atau GEMINI_API_KEY / GEMINI_KEY_1) dibaca otonom
#   dari .env via load_dotenv() di atas.
#   Model default: gemma-4-31b-it, fallback: gemini-2.5-flash.
#   Provider lain (Groq/NVIDIA/GitHub) tetap didukung sebagai fallback.
# ---------------------------------------------------------------------------
def detect_provider() -> tuple[str | None, str | None]:
    """Kembalikan (provider_name, api_key) — Google diprioritaskan."""
    ggl = (
        os.getenv("GOOGLE_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GEMINI_KEY_1")
    )
    if ggl:
        return "google", ggl
    groq = os.getenv("GROQ_API_KEY")
    if groq:
        return "groq", groq
    nvidia = os.getenv("NVIDIA_API_KEY")
    if nvidia:
        return "nvidia", nvidia
    gh = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_API_KEY")
    if gh:
        return "github", gh
    return None, None


def google_api_key() -> str | None:
    """Kompatibilitas: baca kunci Google AI Studio dari berbagai nama env."""
    return (
        os.getenv("GOOGLE_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GEMINI_KEY_1")
    )


GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "meta/llama-3.1-405b-instruct")
GITHUB_MODEL = os.getenv("GITHUB_MODEL", "openai/gpt-4o-mini")
GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemma-4-31b-it")
GOOGLE_FALLBACK_MODEL = os.getenv("GOOGLE_FALLBACK_MODEL", "gemini-2.5-flash")

NVIDIA_BASE_URL = os.getenv(
    "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
GITHUB_BASE_URL = os.getenv(
    "GITHUB_BASE_URL", "https://models.inference.ai.azure.com")


# ---------------------------------------------------------------------------
# FREE-LLM-GATEWAY (self-hosted di VPS) — SATU PINTU untuk semua trafik LLM.
#   LLM_GATEWAY_URL    : base URL gateway TANPA /v1 (mis. tunnel cloudflare)
#   LLM_GATEWAY_KEY    : MASTER_KEY gateway (dipakai sebagai Bearer token)
#   LLM_GATEWAY_MODELS : roster id model yang lolos probe (dipisah koma).
#                        Bila kosong -> pakai GW_FALLBACK_MODELS.
# Bila dua variabel pertama terisi, seluruh pemanggilan LLM lewat gateway;
# fallback antar provider (google/nvidia/groq) ditangani gateway, bukan di sini.
# ---------------------------------------------------------------------------
GW_FALLBACK_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3-flash-preview",
    "openai/gpt-oss-20b",
]


def gateway_config() -> tuple[str | None, str | None]:
    """(base_url, master_key) gateway; (None, None) bila belum dikonfigurasi.

    Delegasi ke `gateway_roster.gateway_config()` agar alias env
    (`LLM_GATEWAY_URL` / `FREELM_GATEWAY_URL` / `GATEWAY_URL`) hanya punya SATU
    implementasi — dua salinan pernah membuat roster dan pemanggil chat membaca
    env yang berbeda.
    """
    try:
        import gateway_roster as gr

        return gr.gateway_config()
    except Exception as exc:  # noqa: BLE001 - gateway opsional
        print(f"[agent_reasoner] gateway_config fallback: {exc}")
        url = (os.getenv("LLM_GATEWAY_URL") or "").strip().rstrip("/")
        key = (os.getenv("LLM_GATEWAY_KEY") or "").strip()
        if url and key:
            return url, key
        return None, None


def gateway_models() -> list[str]:
    """Roster model yang benar-benar diserve gateway (hasil probe empiris)."""
    raw = (os.getenv("LLM_GATEWAY_MODELS") or "").strip()
    if raw:
        picked = [m.strip() for m in raw.split(",") if m.strip()]
        if picked:
            return picked
    return list(GW_FALLBACK_MODELS)


# ---------------------------------------------------------------------------
# Factory model Universal (prioritas otonom .env)
# ---------------------------------------------------------------------------
def build_model(provider: str | None = None, model_name: str | None = None):
    """Bangun chat model LangChain sesuai provider, atau None tanpa key."""
    prov = (provider or detect_provider()[0] or "").lower()
    key = detect_provider()[1]
    temp = float(os.getenv("AGENT_TEMPERATURE", "0.4"))

    if prov == "groq" and key:
        from langchain_groq import ChatGroq

        return ChatGroq(model=model_name or GROQ_MODEL,
                        groq_api_key=key, temperature=temp)
    if prov == "nvidia" and key:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model_name or NVIDIA_MODEL,
                          api_key=key, base_url=NVIDIA_BASE_URL,
                          temperature=temp)
    if prov == "github" and key:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model_name or GITHUB_MODEL,
                          api_key=key, base_url=GITHUB_BASE_URL,
                          temperature=temp)
    if prov == "google" and key:
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model_name or GOOGLE_MODEL,
            google_api_key=key, temperature=temp)
    return None


def _bind(model):
    """Tempel TOOLS ke model (bind_tools) agar MCP-ready; fallback polos."""
    try:
        return model.bind_tools(TOOLS)
    except Exception as exc:  # noqa: BLE001
        print(f"[agent_reasoner] tool binding skip: {exc}")
        return model


# ---------------------------------------------------------------------------
# Run Agent - reasoning dengan konteks + tool-ready + gembok bahasa
# ---------------------------------------------------------------------------
async def run_agent(
        system_prompt: str, user_input: dict[str, Any],
        config: dict[str, Any] | None = None) -> dict:
    """Jalankan Reasoning Agent dengan universal routing + BYOK."""

    # Graceful fallback (Modal 0): validasi key model premium
    try:
        from billing_llm import validate_model_key as _vkey
        _sel = str(locals().get('model') or globals().get('DEFAULT_MODEL', ''))
        _g = _vkey(_sel)
        if not _g['ok']:
            return {'status': 'error', 'error': _g['error'], 'reply': _g['error'], 'output_data': {}}
    except Exception:
        pass
    """Jalankan Reasoning Agent dengan konteks workflow (Universal Router).

    Args:
        system_prompt: instruksi dari config node (System Prompt).
        user_input: data konteks dari Trigger/node sebelumnya.

    Returns:
        dict success {status, reply, output_data, model, provider} atau
        {status: skipped/error, error: ...} yang jelas.
    """
    provider, key = detect_provider()
    if not provider or not key:
        return {
            "status": "skipped",
            "error": (
                "Tidak ada API key AI di environment. Tambahkan salah satu: "
                "GROQ_API_KEY / NVIDIA_API_KEY / GITHUB_TOKEN / GOOGLE_API_KEY "
                "ke .env / Railway env untuk mengaktifkan Reasoning Agent."
            ),
        }

    locked_prompt = f"{system_prompt}\n\n{LANGUAGE_LOCK}\n\nMCP_PICKER_RULE: Jika pengguna menyebut kebutuhan integrasi eksternal, gunakan registry metadata untuk menyaring 3-5 kandidat MCP yang paling relevan. Jangan mengarang server. Nyatakan kandidat sebagai rekomendasi dan minta konfirmasi sebelum instalasi."
    user_context = (
        user_input.get("context")
        if isinstance(user_input, dict)
        else user_input
    ) or user_input or {}
    user_msg = (
        "Konteks workflow (diterima dari node sebelumnya):\n"
        f"{user_context}\n\n"
        "Jika tugas membutuhkan tool eksternal, sebutkan nama dan parameternya."
    )
    messages = [
        {"role": "system", "content": locked_prompt},
        {"role": "user", "content": user_msg},
    ]

    # EXTRACT PAYLOAD dari config node (frontend)
    custom_key = str((config or {}).get("custom_api_key") or "").strip()
    ai_model = str((config or {}).get("model") or "universal").lower()
    skip_cost = bool(custom_key)  # BYOK: cost dibayar user, abaikan LiteLLM

    # Routing kandidat selon tier & BYOK
    candidates: list[tuple[str, str]] = []
    gw_url, gw_key = gateway_config()          # self-hosted free-llm-gateway
    gateway_ready = bool(gw_url and gw_key)
    if custom_key:
        # 1) BYOK (prioritas utama): abaikan sistem acak, langsung guna kunci user.
        candidates = [("byok", "custom")]
    elif ai_model == "deepseek-flash":
        # 4) PLUS: DeepSeek V4 Flash, key server .env.
        dkey = os.getenv("DEEPSEEK_API_KEY") or os.getenv("DEEPSEEK_KEY")
        if not dkey:
            return {"status": "skipped",
                    "error": "DEEPSEEK_API_KEY tidak di .env untuk tier PLUS.",
                    "reply": "DEEPSEEK_API_KEY tidak di .env untuk tier PLUS.",
                    "output_data": {}}
        candidates = [("deepseek", os.getenv("DEEPSEEK_MODEL", "deepseek-chat"))]
    elif gateway_ready:
        # 0) GATEWAY self-hosted (VPS free-llm-gateway) — jalur utama.
        #    Roster = model yang lolos probe empiris (LLM_GATEWAY_MODELS).
        #    Bila user memilih model spesifik yang ada di roster, pakai itu.
        roster = gateway_models()
        picked = [ai_model] if ai_model in roster else roster
        candidates = [("gateway", m) for m in picked]
    elif ai_model == "universal":
        # 3) FREE: rute acak (random) dari dira model gratis di .env.
        candidates = _free_candidates(provider)
        if not candidates:
            candidates = [(provider, _default_model(provider))]
    else:
        candidates = [(provider, _default_model(provider))]

    last_err: Exception | None = None
    for prov, model_name in candidates:
        try:
            if prov == "byok":
                # BYOK: model OpenAI-kompatibel dengan kunci user (tidak ke DB).
                from langchain_openai import ChatOpenAI
                model = ChatOpenAI(
                    model=os.getenv("BYOK_MODEL", "openai/gpt-4o-mini"),
                    api_key=custom_key,
                    base_url=os.getenv("BYOK_BASE_URL") or None,
                    temperature=float(os.getenv("AGENT_TEMPERATURE", "0.4")),
                )
            elif prov == "gateway":
                # Self-hosted gateway: OpenAI-compatible (/v1), Bearer MASTER_KEY.
                # `timeout` wajib: tunnel cloudflared yang menggantung tidak
                # pernah memutus koneksi, jadi tanpa batas ini kandidat gateway
                # memblokir seluruh loop dan kandidat provider lain tak dicoba.
                from langchain_openai import ChatOpenAI
                model = ChatOpenAI(
                    model=model_name,
                    api_key=gw_key,
                    base_url=f"{gw_url}/v1",
                    temperature=float(os.getenv("AGENT_TEMPERATURE", "0.4")),
                    timeout=float(os.getenv("LLM_GATEWAY_TIMEOUT", "45")),
                    max_retries=0,
                )
            elif prov == "deepseek":
                from langchain_openai import ChatOpenAI
                model = ChatOpenAI(
                    model=model_name,
                    api_key=os.getenv("DEEPSEEK_API_KEY") or os.getenv("DEEPSEEK_KEY"),
                    base_url=os.getenv(
                        "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
                    temperature=float(os.getenv("AGENT_TEMPERATURE", "0.4")),
                )
            else:
                model = build_model(prov, model_name)
            if model is None:
                continue
            resp = await _bind(model).ainvoke(messages)
            raw = getattr(resp, "content", str(resp))
            # Google/Gemma bisa mengembalikan list blok [{type:thinking},{type:text}]
            # -> ambil hanya blok teks agar terminal bersih.
            if isinstance(raw, list):
                texts = [b.get("text", "") for b in raw
                         if isinstance(b, dict) and b.get("type") == "text"
                         and b.get("text")]
                reply = "\n".join(texts).strip() or "[Agent tanpa respons tekstual]"
            else:
                reply = str(raw or "").strip() or "[Agent tanpa respons tekstual]"
            if not reply:
                reply = "[Agent tanpa respons tekstual]"
            # Bersihkan sisa blok thinking jika masih lolos (rapikan terminal).
            if isinstance(reply, str) and "{'type': 'thinking'" in reply:
                import re as _re
                m = _re.findall(r"'text':\s*'((?:[^'\\]|\\.)*)'", reply)
                if m:
                    reply = "\n".join(s.encode().decode("unicode_escape", "ignore")
                                      for s in m).strip() or reply
            # --- Usage + biaya (LiteLLM) ---
            usage = getattr(resp, "usage_metadata", None) or {}
            try:
                prompt_t = usage.get("input_tokens", 0) if isinstance(usage, dict) else getattr(usage, "input_tokens", 0)
                compl_t = usage.get("output_tokens", 0) if isinstance(usage, dict) else getattr(usage, "output_tokens", 0)
            except Exception:
                prompt_t, compl_t = 0, 0
            cost_usd = 0.0 if skip_cost else estimate_cost(model_name, prompt_t, compl_t)
            return {
                "status": "success",
                "reply": str(reply),
                "output_data": {"reply": str(reply), "model": model_name,
                                "provider": prov},
                "model": model_name,
                "provider": prov,
                "usage": {"prompt_tokens": int(prompt_t or 0),
                          "completion_tokens": int(compl_t or 0)},
                "cost_usd": float(cost_usd or 0.0),
            }
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            print(f"[agent_reasoner] {prov}/{model_name} gagal: {exc}")
            continue
    return {"status": "error", "error": f"[{type(last_err).__name__}] {last_err}"}


def _default_model(provider: str) -> str:
    return {"groq": GROQ_MODEL, "nvidia": NVIDIA_MODEL,
            "github": GITHUB_MODEL, "google": GOOGLE_MODEL}.get(
                provider, GROQ_MODEL)


def _free_candidates(primary: str | None) -> list[tuple[str, str]]:
    """Tier FREE: list model gratis dari .env (random.choice di caller)."""
    pool: list[tuple[str, str]] = []
    providers: dict[str, tuple[str, str]] = {
        "groq": ("GROQ_API_KEY", GROQ_MODEL),
        "nvidia": ("NVIDIA_API_KEY", NVIDIA_MODEL),
        "github": ("GITHUB_TOKEN", GITHUB_MODEL),
        "google": ("GOOGLE_API_KEY", GOOGLE_MODEL),
    }
    for p, (env, model) in providers.items():
        if os.getenv(env):
            pool.append((p, model))
    # Garantir primary detektasi jika dahun sisällä.
    if primary and all(x[0] != primary for x in pool):
        key = providers.get(primary, (None, None))[0]
        if key and os.getenv(key):
            pool.append((primary, _default_model(primary)))
    if not pool:
        return []
    import random
    picked = random.choice(pool)   # Round-Robin/random FREE rute
    return [picked]


def agent_ready() -> bool:
    """True jika ada kunci AI apa pun (untuk UI/logs)."""
    prov, _ = detect_provider()
    return bool(prov)


# --- Biaya (LiteLLM) ---
def estimate_cost(model, prompt_t, compl_t):
 try:
  from litellm import completion_cost
  return float(completion_cost(completion_response={'usage':{'prompt_tokens':int(prompt_t or 0),'completion_tokens':int(compl_t or 0)}}, model=model))
 except Exception:
  return 0.0
