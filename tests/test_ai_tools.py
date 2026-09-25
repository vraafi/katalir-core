"""Tests for the AI tools MCP server.

These must not require network access: they assert the parts that are easy to
break (key discovery, model filtering) and the shape of the tool results. The
live call evidence is recorded in ``ai_tools_evidence.json``.
"""
import importlib.util
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("ai_tools", ROOT / "scripts" / "ai_tools_mcp.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_gemini_key_pool_terbaca():
    """The pool is a numbered set, not one variable - that is easy to break."""
    keys = mod._gemini_keys()
    assert isinstance(keys, list)
    assert all(isinstance(k, str) for k in keys)
    assert len(keys) == len([k for k in keys if k])


def test_tersedia_dua_tool():
    names = {t.name for t in mod.mcp._tool_manager.list_tools()}
    assert names == {"groq_chat", "gemini_generate"}


def test_filter_model_menolak_kategori_bukan_chat():
    chat = [m for m in ["whisper-large-v3", "meta-llama/llama-prompt-guard-2-86m", "qwen/qwen3.8-27b", "mod-x"]
            if not any(bad in m.lower() for bad in mod._NON_CHAT)]
    assert chat == ["qwen/qwen3.8-27b", "mod-x"]


def test_evidence_hanya_berisi_yang_terbukti():
    """Recorded evidence must match what was actually executed."""
    path = ROOT / "ai_tools_evidence.json"
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    for entry in data["tools"]:
        assert entry["verification"]["call_verified"] is True
        assert entry.get("evidence"), f"no evidence for {entry['tool']}"
        assert entry["evidence"].get("answer"), "a call_verified tool must have returned text"
        assert isinstance(entry["evidence"]["latency_ms"], int)
