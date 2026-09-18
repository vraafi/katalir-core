"""Kontrak retry tanpa tools di _agentic_run_gateway (temuan U).

Gateway free-llm-gateway membalas 500 polos bila payload memuat tools untuk
model tertentu (mis. groq/compound). Retry tanpa tools harus terjadi, dan
hasilnya harus jujur dilaporkan lewat meta.tools_dropped.

Tiga skenario:
  1. helper pengklasifikasi 500-polos-tools mengenali error tsb
  2. helper tidak menuduh error lain (tanpa false positive)
  3. wiring: retry tanpa tools + meta.tools_dropped benar-benar terpasang
"""
import inspect
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent
SRC = (ROOT / "api_server.py").read_text(encoding="utf-8")

import api_server as A  # noqa: E402


def _helper():
    fn = getattr(A, "_tools_unsupported", None)
    assert fn is not None, "helper _tools_unsupported tidak ada di api_server"
    return fn


def _invoke(fn, candidates):
    """Panggil fn dengan kwargs yang cocok dengan signature-nya."""
    params = inspect.signature(fn).parameters
    if any(p.kind == p.VAR_KEYWORD for p in params.values()):
        return fn(**candidates)
    kw = {k: v for k, v in candidates.items() if k in params}
    try:
        return fn(**kw)
    except TypeError as exc:
        pytest.fail(
            "signature %s tidak tercakup kandidat: %s" % (inspect.signature(fn), exc)
        )


ERR_500 = Exception("Internal Server Error")
ERR_OTHER = Exception("connection reset by peer")

CAND = {
    "err": ERR_500,
    "exc": ERR_500,
    "error": ERR_500,
    "e": ERR_500,
    "status": 500,
    "status_code": 500,
    "code": 500,
    "body": "Internal Server Error",
    "text": "Internal Server Error",
    "message": "Internal Server Error",
    "detail": "Internal Server Error",
    "response": None,
    "payload": None,
    "model": "groq/compound",
    "tools": [{"type": "function"}],
    "tool_names": ["x"],
    "tools_bound": True,
    "bound": True,
    "had_tools": True,
    "with_tools": True,
    "tools_present": True,
}


def test_helper_mengenali_500_polos_dengan_tools():
    fn = _helper()
    assert _invoke(fn, CAND) is True


def test_helper_tidak_menuduh_error_lain():
    fn = _helper()
    cand = dict(CAND)
    for k in ("err", "exc", "error", "e"):
        cand[k] = ERR_OTHER
    for k in ("status", "status_code", "code"):
        cand[k] = 400
    for k in ("body", "text", "message", "detail"):
        cand[k] = "bad request"
    assert _invoke(fn, cand) is False


def test_retry_tanpa_tools_terpasang_dan_meta_jujur():
    assert re.search(r"_tools_unsupported", SRC), "pemicu retry tidak ada"
    assert re.search(r"tools_dropped", SRC), "meta.tools_dropped tidak ada"
    calls = re.findall(r"chat_model.invoke\s*\(", SRC)
    assert len(calls) >= 2, "hanya %d pemanggilan chat_model.invoke; retry tak terpasang" % len(calls)
