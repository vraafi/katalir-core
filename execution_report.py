"""execution_report.py — ubah baris eksekusi mentah menjadi laporan untuk chat.

KENAPA DI BACKEND (bukan di React): laporan adalah bahasa, bukan tampilan.
Menaruhnya di server membuatnya bisa diuji tanpa browser (lihat
`tests/test_execution_report.py`) dan membuat SEMUA klien (chat, kanvas,
CLI masa depan) memberi laporan yang sama.

Detail yang sengaja ditangani:
  * `execution_logs` memuat DUA baris per node (status `running` saat mulai dan
    status akhir), jadi laporan meng-COLLAPSE per node (entri terakhir menang).
    Tanpa itu user melihat node yang sama dua kali, salah satunya "running"
    padahal sudah selesai.
  * output node bisa panjang/JSON; yang ditampilkan hanya ringkasan pendek.
  * kegagalan tidak pernah disembunyikan: baris error + pesan error ditulis apa
    adanya, dan hitungan sukses/gagal selalu muncul.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MAX_SNIPPET = 160
_LOCALES = {"id": {}, "en": {}}
for _locale in _LOCALES:
    _LOCALES[_locale] = json.loads(
        (Path(__file__).parent / "locales" / f"{_locale}.json").read_text(encoding="utf-8")
    )


def t(key: str, locale: str = "id", **values: Any) -> str:
    """Lookup pesan execution report; locale tak dikenal jatuh ke Indonesia."""
    catalog = _LOCALES.get((locale or "id").split("-", 1)[0].lower(), _LOCALES["id"])
    return str(catalog.get(key, _LOCALES["id"].get(key, key))).format(**values)


def locale_from_accept_language(value: str | None) -> str:
    """Negotiate hanya ID/EN; bahasa lain memakai default ID."""
    for part in (value or "").split(","):
        tag = part.split(";", 1)[0].strip().lower()
        if tag.startswith("id"):
            return "id"
        if tag.startswith("en"):
            return "en"
    return "id"


def _snippet(value: Any) -> str:
    """Ringkasan pendek dari payload apa pun (aman, satu baris)."""
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("summary", "message", "result", "output", "text", "error"):
            if value.get(key):
                return _snippet(value[key])
        # fallback: pasangan kunci=nilai ringkas
        parts = [f"{k}={_snippet(v)}" for k, v in list(value.items())[:3]]
        text = ", ".join(p for p in parts if p and not p.endswith("="))
    else:
        text = str(value)
    text = " ".join(text.split())
    if len(text) > MAX_SNIPPET:
        text = text[: MAX_SNIPPET - 1].rstrip() + "…"
    return text


def collapse_steps(logs: list[dict] | None) -> list[dict]:
    """Entri TERAKHIR per node (lihat catatan modul)."""
    by_node: dict[str, dict] = {}
    order: list[str] = []
    for row in logs or []:
        if not isinstance(row, dict):
            continue          # entri non-dict dari upstream: dilewati, bukan crash
        node = str(row.get("node_id") or "?")
        if node not in by_node:
            order.append(node)
        by_node[node] = row
    return [by_node[n] for n in order]


def _step_failed(step: dict) -> bool:
    """True bila langkah GAGAL, walau `status`-nya 'completed'.

    Temuan nyata saat uji 2.5: node MCP menghasilkan
    `payload={'type': 'mcp.call', 'result': {'status': 'error', ...}}` tetapi
    `status` langkah tetap 'completed'. Kalau laporan hanya melihat `status`,
    user diberi tahu "2 langkah berhasil" untuk workflow yang sebenarnya gagal —
    persis kelas kebohongan yang harus dihindari.
    """
    if str(step.get("status") or "") == "error":
        return True
    payload = step.get("payload") or {}
    if isinstance(payload, dict):
        if payload.get("error"):
            return True
        inner = payload.get("result")
        if isinstance(inner, dict) and str(inner.get("status") or "").lower() in (
                "error", "failed", "failure"):
            return True
    return False


def format_execution_report(execution: dict | None,
                            logs: list[dict] | None,
                            locale: str = "id") -> str:
    """Laporan siap-tampil dalam locale ID/EN (default mempertahankan ID lama)."""
    steps = collapse_steps(logs)
    status = str((execution or {}).get("status") or ("completed" if steps else "unknown"))
    err = sum(1 for s in steps if _step_failed(s))
    ok = len(steps) - err

    if not steps:
        if status in ("pending", "running"):
            return t("workflow.running", locale)
        return t("workflow.no_steps", locale, status=status)

    head = t("workflow.success" if err == 0 else "workflow.error", locale, ok=ok, err=err)
    lines = [head]
    for i, step in enumerate(steps, 1):
        node = str(step.get("node_id") or "?")
        failed = _step_failed(step)
        st = str(step.get("status") or "?")
        icon = t("step.failed", locale) if failed else (
            t("step.ok", locale) if st == "completed" else st)
        payload = step.get("payload")
        detail = _snippet(payload)
        lines.append(f"{i}. {node} — {icon}" + (f": {detail}" if detail else ""))
    return "\n".join(lines)
