# agent_reasoner.py - Reasoning Agent (Enterprise September 2026)
# =============================================================================
# Eksekutor para node AGENT del Execution Engine, construido sobre un agent
# framework moderno (LangChain Core) en lugar de raw SDK chat completions.
#
# Caracteristicas:
#   1. Tool Calling NATIVO via LangChain `bind_tools` (MCP readiness).
#   2. Sistema multi-proveedor: lee OPENAI_API_KEY o ANTHROPIC_API_KEY.
#   3. State/Memory implicito via session de mensajes (system + user + tool).
#   4. No crashea si no hay API key -> devuelve {status, error} claro.
#   5. El resultado "pemikiran" (teks) se expone como output_data para
#      persistir en execution_logs.
# =============================================================================

import os
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from langchain_core.tools import tool

# ---------------------------------------------------------------------------
# MCP Readiness - schema de los tools que el LLM podra llamar en el futuro
# ---------------------------------------------------------------------------
@tool
def mcp_tool_probe(tool_name: str, arguments: str) -> str:
    """Alta pooled prototipo para invocar una herramienta MCP de forma agnostica.

    En el futuro esta llamada se resuelve via el MCPRegistry del execution_engine.
    Args:
        tool_name: nombre del tool MCP (web_search, read_database, ...).
        arguments: string JSON con los parametros de la herramienta.
    Returns:
        Resultado simulado de la herramienta.
    """
    return f"[MCP::probe] tool={tool_name} args={arguments}"


TOOLS = [mcp_tool_probe]


# ---------------------------------------------------------------------------
# Factory de modelo multi-proveedor
# ---------------------------------------------------------------------------
def build_model():
    """Construye un chat model LangChain segun las claves disponibles.

    Returns:
        langchain BaseChatModel con tools bindings, o None si no hay clave.
    """
    openai_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_KEY")

    if openai_key:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            api_key=openai_key,
            temperature=float(os.getenv("AGENT_TEMPERATURE", "0.4")),
        )
    if anthropic_key:
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"),
            api_key=anthropic_key,
            temperature=float(os.getenv("AGENT_TEMPERATURE", "0.4")),
        )
    return None


# ---------------------------------------------------------------------------
# Run Agent - orquesta un "pensamiento" con contexto + tool-ready
# ---------------------------------------------------------------------------
async def run_agent(system_prompt: str, user_input: dict[str, Any]) -> dict:
    """Ejecuta el Reasoning Agent con contexto.

    Args:
        system_prompt: instrucciones del node (System Prompt).
        user_input: data de context recibida del Trigger/nodo anterior.

    Returns:
        dict:
            - on success: {status, reply, output_data, model}
            - on missing key: {status: "skipped", error: "..."}
            - on error:      {status: "error", error: "..."}
    """
    model = build_model()
    if model is None:
        return {
            "status": "skipped",
            "error": (
                "No se detecto OPENAI_API_KEY ni ANTHROPIC_API_KEY. "
                "Agrega una clave en Railway env para activar el Reasoning Agent."
            ),
        }

    # Tool calling nativo (MCP readiness) - modelo con bind_tools
    try:
        model_with_tools = model.bind_tools(TOOLS)
    except Exception as exc:  # noqa: BLE001
        model_with_tools = model
        print(f"[agent_reasoner] tool binding skip: {exc}")

    user_context = user_input.get("context") or user_input or {}
    user_msg = (
        "Contexto del workflow (recibido del nodo previo):\n"
        f"{user_context}\n\n"
        "Si tu tarea requiere una herramienta externa, indica su nombre y parametros."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    try:
        resp = await model_with_tools.ainvoke(messages)
        reply = getattr(resp, "content", str(resp))
        if not reply:
            reply = "[Agent sin respuesta textual]"
        model_name = getattr(getattr(model_with_tools, "model_name", None), "value", None) or "llm"
        return {
            "status": "success",
            "reply": str(reply),
            "output_data": {"reply": str(reply), "model": model_name},
            "model": model_name,
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"[{type(exc).__name__}] {exc}"}


def agent_ready() -> bool:
    """True si hay una clave de LLM configurada (para UI/logs)."""
    return bool(os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY")
                or os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_KEY"))