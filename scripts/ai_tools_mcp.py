"""Real MCP tools for the AI providers we actually hold keys for.

Why this file exists: "30 AI integrations" is only worth anything if the calls
run. Groq and Gemini are the two providers whose keys are present in the
environment, so they are wired here and exercised for real. Everything else
(HuggingFace, Replicate, Together, Pinecone...) stays out until a key exists -
an integration that cannot be called is a catalogue entry, not a working one.

Credentials are read from the environment and never logged or echoed.
"""
from __future__ import annotations

import os
import time

import httpx
from dotenv_loader import load_repo_env
from mcp.server.fastmcp import FastMCP

load_repo_env(override=True)
mcp = FastMCP("katalir-ai-tools")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
# Substrings that mark a model as unsuitable for plain text generation. The
# available catalogue changes often - llama models vanished from Groq between
# sessions - so the default is discovered at runtime instead of hardcoded.
_NON_CHAT = ("whisper", "guard", "tts", "embedding", "moderation")
_MODEL_CACHE: dict[str, object] = {}


async def _discover_groq_model() -> str:
    if "groq" in _MODEL_CACHE:
        return str(_MODEL_CACHE["groq"])
    key = os.environ.get("GROQ_API_KEY") or ""
    if not key:
        return "llama-3.3-70b-versatile"
    ids: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(GROQ_MODELS_URL, headers={"Authorization": f"Bearer {key}"})
            if r.status_code == 200:
                ids = [m.get("id", "") for m in r.json().get("data", [])]
    except Exception:  # noqa: BLE001
        ids = []
    chat = [i for i in ids if i and not any(bad in i.lower() for bad in _NON_CHAT)]
    chosen = chat[0] if chat else "llama-3.3-70b-versatile"
    _MODEL_CACHE["groq"] = chosen
    return chosen


async def _discover_gemini_model() -> str:
    if "gemini" in _MODEL_CACHE:
        return str(_MODEL_CACHE["gemini"])
    chosen = "gemini-2.5-flash"
    for key in _gemini_keys()[:3]:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(GEMINI_MODELS_URL, headers={"x-goog-api-key": key})
                if r.status_code == 200:
                    for m in r.json().get("models", []):
                        methods = m.get("supportedGenerationMethods") or []
                        name = str(m.get("name") or "")
                        if "generateContent" in methods and "flash" in name and "tts" not in name:
                            chosen = name.replace("models/", "")
                            break
                    break
        except Exception:  # noqa: BLE001
            continue
    _MODEL_CACHE["gemini"] = chosen
    return chosen



def _first_gemini_key() -> str:
    """Gemini keys are stored in a numbered pool, not a single variable."""
    plain = os.environ.get("GEMINI_API_KEY") or ""
    if plain:
        return plain
    for i in range(1, 20):
        value = os.environ.get(f"GEMINI_KEY_{i}") or ""
        if value:
            return value
    return ""


def _gemini_keys() -> list[str]:
    plain = os.environ.get("GEMINI_API_KEY") or ""
    keys = [plain] if plain else []
    for i in range(1, 20):
        value = os.environ.get(f"GEMINI_KEY_{i}") or ""
        if value:
            keys.append(value)
    return keys


@mcp.tool(name="groq_chat", description="Call a Groq chat model. The model is discovered from Groq's live catalogue. Requires GROQ_API_KEY.")
async def groq_chat(prompt: str, model: str = "") -> dict:
    """Send a prompt to Groq and return the model's answer plus latency."""
    key = os.environ.get("GROQ_API_KEY") or ""
    if not key:
        return {"ok": False, "error": "GROQ_API_KEY not configured"}
    chosen = model or await _discover_groq_model()
    started = time.time()
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": chosen,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 128,
            },
        )
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.text[:400]}
    answer = ""
    try:
        answer = body["choices"][0]["message"]["content"]
    except Exception:  # noqa: BLE001
        pass
    return {
        "ok": r.status_code == 200 and bool(answer),
        "status": r.status_code,
        "model": chosen,
        "answer": answer,
        "latency_ms": int((time.time() - started) * 1000),
        "error": None if r.status_code == 200 else str(body)[:300],
    }


@mcp.tool(name="gemini_generate", description="Call Google Gemini. The model is discovered from the live Gemini catalogue and the key pool is rotated. Requires a GEMINI key.")
async def gemini_generate(prompt: str, model: str = "") -> dict:
    """Send a prompt to Gemini and return the generated text plus latency."""
    keys = _gemini_keys()
    if not keys:
        return {"ok": False, "error": "no GEMINI key configured"}
    chosen = model or await _discover_gemini_model()
    last_error = ""
    started = time.time()
    async with httpx.AsyncClient(timeout=60) as client:
        for key in keys:
            url = f"{GEMINI_MODELS_URL}/{chosen}:generateContent"
            r = await client.post(
                url,
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": prompt}]}]},
            )
            if r.status_code == 200:
                try:
                    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                except Exception:  # noqa: BLE001
                    text = ""
                return {
                    "ok": bool(text),
                    "status": r.status_code,
                    "model": chosen,
                    "answer": text,
                    "latency_ms": int((time.time() - started) * 1000),
                }
            last_error = f"HTTP {r.status_code}: {r.text[:200]}"
    return {"ok": False, "error": last_error, "keys_tried": len(keys)}


if __name__ == "__main__":
    mcp.run()
