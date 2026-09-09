# agent_reasoner.py - Reasoning Agent (Enterprise September 2026)
# =============================================================================
# Eksekutor untuk node AGENT, dibangun di atas framework agentic modern
# (LangChain Core + integrasi Google Generative AI) — BUKAN raw SDK.
#
# Fitur:
#   1. Tool Calling NATIVE via `bind_tools` (MCP readiness).
#   2. Multi-nama env Google: GOOGLE_API_KEY / GEMINI_API_KEY / GEMINI_KEY_1.
#   3. Model default `gemma-4-31b-it`, fallback otomatis `gemini-2.5-flash`.
#   4. Tidak crash tanpa key -> return {status, error} yang jelas.
#   5. Output "pemikiran" tersimpan ke execution_logs via output_data.
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


def google_api_key() -> str | None:
    """Baca kunci Google AI Studio dari berbagai nama env (.env otonom)."""
    return (
        os.getenv("GOOGLE_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GEMINI_KEY_1")
    )


DEFAULT_MODEL = os.getenv("GOOGLE_MODEL", "gemma-4-31b-it")
FALLBACK_MODEL = os.getenv("GOOGLE_FALLBACK_MODEL", "gemini-2.5-flash")


# ---------------------------------------------------------------------------
# Factory model Google (LangChain)
# ---------------------------------------------------------------------------
def build_model(model_name: str | None = None):
    """Bangun ChatGoogleGenerativeAI dengan tools binding, atau None tanpa key."""
    api_key = google_api_key()
    if not api_key:
        return None
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=model_name or DEFAULT_MODEL,
        google_api_key=api_key,
        temperature=float(os.getenv("AGENT_TEMPERATURE", "0.4")),
    )


# ---------------------------------------------------------------------------
# Run Agent - reasoning dengan konteks + tool-ready
# ---------------------------------------------------------------------------
async def run_agent(system_prompt: str, user_input: dict[str, Any]) -> dict:
    """Jalankan Reasoning Agent (Google) dengan konteks workflow.

    Args:
        system_prompt: instruksi dari config node (System Prompt).
        user_input: data konteks dari Trigger/node sebelumnya.

    Returns:
        dict success {status, reply, output_data, model} atau
        {status: skipped/error, error: ...} yang jelas.
    """
    if not google_api_key():
        return {
            "status": "skipped",
            "error": (
                "GOOGLE_API_KEY tidak ditemukan. "
                "Tambahkan GOOGLE_API_KEY (atau GEMINI_API_KEY/GEMINI_KEY_1) "
                "ke .env / Railway env untuk mengaktifkan Reasoning Agent."
            ),
        }

    user_context = (
        user_input.get("context")
        if isinstance(user_input, dict)
        else user_input
    ) or user_input or {}
    user_msg = (
        "Contexto del workflow (recibido del nodo previo):\n"
        f"{user_context}\n\n"
        "Jika tugas membutuhkan tool eksternal, sebutkan nama dan parameternya."
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    last_err: Exception | None = None
    for model_name in (DEFAULT_MODEL, FALLBACK_MODEL):
        try:
            model = build_model(model_name)
            try:
                model_with_tools = model.bind_tools(TOOLS)
            except Exception as exc:  # noqa: BLE001
                model_with_tools = model
                print(f"[agent_reasoner] tool binding skip: {exc}")
            resp = await model_with_tools.ainvoke(messages)
            reply = getattr(resp, "content", str(resp))
            if not reply:
                reply = "[Agent tanpa respons tekstual]"
            return {
                "status": "success",
                "reply": str(reply),
                "output_data": {"reply": str(reply), "model": model_name},
                "model": model_name,
            }
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            print(f"[agent_reasoner] model {model_name} gagal: {exc}")
            continue
    return {"status": "error", "error": f"[{type(last_err).__name__}] {last_err}"}


def agent_ready() -> bool:
    """True jika kunci Google tersedia (untuk UI/logs)."""
    return bool(google_api_key())
