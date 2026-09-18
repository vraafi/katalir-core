"""LiteLLM key guard + Dodo Payments hook + Token Ledger (Modal 0)."""
from __future__ import annotations
import os
from typing import Any

MAINTENANCE_MSG = (
    "Model premium ini sedang dalam pemeliharaan. "
    "Silakan gunakan model DeepSeek atau Llama untuk sementara waktu."
)

CLAUDE_MODELS = ("claude", "anthropic")
GPT_MODELS = ("gpt", "openai", "o1", "o3")


def validate_model_key(model: str) -> dict[str, Any]:
    """Graceful fallback: cek API key sebelum memanggil model premium."""
    m = (model or "").lower()
    if any(k in m for k in CLAUDE_MODELS):
        if not os.getenv("ANTHROPIC_API_KEY"):
            return {"ok": False, "error": MAINTENANCE_MSG}
    elif any(k in m for k in GPT_MODELS):
        if not os.getenv("OPENAI_API_KEY"):
            return {"ok": False, "error": MAINTENANCE_MSG}
    return {"ok": True}


def litellm_complete(model: str, messages: list[dict], **kw: Any) -> dict[str, Any]:
    """Panggil LiteLLM dengan guard. Return {ok, text} atau {ok:False, error}."""
    gate = validate_model_key(model)
    if not gate["ok"]:
        return {"ok": False, "error": gate["error"]}
    try:
        import litellm
        resp = litellm.completion(model=model, messages=messages, **kw)
        text = resp.choices[0].message.content if resp.choices else ""
        usage = getattr(resp, "usage", None)
        return {"ok": True, "text": text,
                "usage": {"prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                          "completion_tokens": getattr(usage, "completion_tokens", 0) or 0}}
    except Exception as exc:  # jangan crash
        return {"ok": False, "error": f"LLM error: {exc}"}


class TokenLedger:
    """Ledger token per-eksekusi (Modal 0): catat pemakaian per model."""

    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = []

    def record(self, execution_id: str, model: str, prompt_t: int = 0,
               compl_t: int = 0, cost_usd: float = 0.0) -> dict[str, Any]:
        row = {"execution_id": execution_id, "model": model,
               "prompt_tokens": prompt_t, "completion_tokens": compl_t,
               "total_tokens": prompt_t + compl_t, "cost_usd": cost_usd}
        self._rows.append(row)
        return row

    def for_execution(self, execution_id: str) -> list[dict[str, Any]]:
        return [r for r in self._rows if r["execution_id"] == execution_id]

    def total_cost(self, execution_id: str) -> float:
        return sum(r["cost_usd"] for r in self.for_execution(execution_id))


LEDGER = TokenLedger()


def dodo_checkout_url(plan: str = "pro", email: str = "") -> str:
    base = os.getenv("DODO_CHECKOUT_URL", "") or os.getenv("DODO_PAYMENTS_URL", "")
    if not base:
        return ""
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}plan={plan}&email={email}"


def _deprecated_verify_dodo_webhook(payload: bytes, signature: str = "") -> bool:
    """DEPRECATED — JANGAN DIPAKAI. Selalu `False`.

    Versi lama fungsi ini memakai HMAC-hex sederhana atas body saja dan
    mengandung **dev-bypass**: `if not secret: return True` -> tanpa secret,
    SETIAP webhook diterima tanpa verifikasi. Fungsi itu tidak pernah dipanggil
    endpoint (endpoint memakai `dodo_verify.verify_dodo_webhook` yang mengikuti
    Standard Webhooks + SDK unwrap), tetapi menyimpannya sebagai panggilan yang
    "siap dipakai" adalah ranjau: sekali seseorang memasangnya, spoof langsung
    diterima.

    Sekarang: gagal-tertutup (selalu False) + peringatan log, supaya sisa
    pemanggil mana pun terlihat sebagai 401 alih-alih lubang keamanan.
    """
    import logging

    logging.getLogger(__name__).warning(
        "billing_llm._deprecated_verify_dodo_webhook dipanggil: fungsi ini "
        "DEPRECATED (dev-bypass). Gunakan dodo_verify.verify_dodo_webhook."
    )
    return False


def verify_dodo_webhook(payload: bytes, signature: str = "") -> bool:  # noqa: D401
    """Alias lama -> dialihkan ke versi deprecated (fail-closed)."""
    return _deprecated_verify_dodo_webhook(payload, signature)
