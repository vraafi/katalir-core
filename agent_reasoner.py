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

from dotenv import load_dotenv

load_dotenv()

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
# Deteksi provider otonom (prioritas: Groq > NVIDIA > GitHub > Google)
# ---------------------------------------------------------------------------
def detect_provider() -> tuple[str | None, str | None]:
    """Kembalikan (provider_name, api_key) sesuai prioritas .env."""
    groq = os.getenv("GROQ_API_KEY")
    if groq:
        return "groq", groq
    nvidia = os.getenv("NVIDIA_API_KEY")
    if nvidia:
        return "nvidia", nvidia
    gh = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_API_KEY")
    if gh:
        return "github", gh
    ggl = (
        os.getenv("GOOGLE_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GEMINI_KEY_1")
    )
    if ggl:
        return "google", ggl
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
async def run_agent(system_prompt: str, user_input: dict[str, Any]) -> dict:
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

    locked_prompt = f"{system_prompt}\n\n{LANGUAGE_LOCK}"
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

    # Kandidat model: provider terdeteksi dulu, lalu fallback berurutan.
    candidates: list[tuple[str, str]] = [(provider, _default_model(provider))]
    for p in ("groq", "nvidia", "github", "google"):
        if p != provider and os.getenv({
                "groq": "GROQ_API_KEY", "nvidia": "NVIDIA_API_KEY",
                "github": "GITHUB_TOKEN", "google": "GOOGLE_API_KEY"}[p]):
            candidates.append((p, _default_model(p)))

    last_err: Exception | None = None
    for prov, model_name in candidates:
        try:
            model = build_model(prov, model_name)
            if model is None:
                continue
            resp = await _bind(model).ainvoke(messages)
            reply = getattr(resp, "content", str(resp))
            if not reply:
                reply = "[Agent tanpa respons tekstual]"
            return {
                "status": "success",
                "reply": str(reply),
                "output_data": {"reply": str(reply), "model": model_name,
                                "provider": prov},
                "model": model_name,
                "provider": prov,
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


def agent_ready() -> bool:
    """True jika ada kunci AI apa pun (untuk UI/logs)."""
    prov, _ = detect_provider()
    return bool(prov)
