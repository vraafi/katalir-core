"""Normalizer untuk spec workflow yang ditulis model.

BUG FIX 2026-10-04 - workflow selalu ditolak validator.

Bukti nyata (qwen/qwen3.8-27b via free-llm-gateway, system prompt Katalir):

    {"workflow": {"name": "Ambil Data & Kirim ke Telegram", "nodes": [
      {"id": "trigger_manual", "type": "trigger", "config": {...}},
      {"id": "fetch_data",    "type": "http",  "config": {...}},
      {"id": "send_telegram", "type": "telegram", "config": {...}}],
     "edges": [{"from": "trigger_manual", "to": "fetch_data"}, ...]}}

ortingkan yang di’espèrekan workflow_spec.validate_spec:
    root  = {name, nodes, edges}          (bukan dibungkus "workflow")
    node  = {id, kind, label, config}     (bukan "type")
    edge  = {source, target}              (bukan "from"/"to")

Tiga bentuk ketidakcocokan yang ditemukan:
    1. pembungkus "workflow" di level root
    2. "type"代替 "kind", DAN kind seperti "http"/"telegram" yang seharusnya
       "mcp" (provider ada di config)
    3. edge memakai "from"/"to"

Karena tool `generate_workflow_json` menerima argumen bernama `spec_json`,
payload yang datang pada kunci lain (`workflow`, `draft`, `spec`) tidak pernah
sampai ke validator - ia menerima string kosong dan menolak dengan
"spec_json kosong".

Fungsi ini TIDAK melempar. Kalau tidak mengenali bentuk, ia mengembalikan
payload apa adanya supaya validator tetap memberi pesan error yang biasa.
"""

from __future__ import annotations

import json
from typing import Any

_WRAPPER_KEYS = ("workflow", "draft", "spec", "workflow_json", "data")

# Kind yang bukan "mcp" tapi services nyata -> dipetakan ke "mcp" karena
# provider-nya ada di dalam config.
_SERVICE_KINDS = {
    "http", "telegram", "slack", "gmail", "whatsapp", "sheets",
    "google_sheets", "google_calendar", "calendar", "email", "api",
    "webhook", "action", "step",
}


def _as_dict(value: Any) -> dict | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:  # noqa: BLE001
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _unwrap(root: dict) -> dict:
    """Buang pembungkus {"workflow": {...}} bila ada."""
    for key in _WRAPPER_KEYS:
        inner = root.get(key)
        if isinstance(inner, dict) and "nodes" in inner:
            merged = dict(inner)
            for k, v in root.items():
                if k not in _WRAPPER_KEYS:
                    merged.setdefault(k, v)
            return merged
    return root


def _normalize_node(node: dict) -> dict:
    out = dict(node)
    # 1) "type" -> "kind"
    kind = out.pop("type", None)
    if kind is None:
        kind = out.get("kind")
    else:
        out.setdefault("kind", kind)
    if isinstance(kind, str):
        k = kind.strip().lower()
        if k in _SERVICE_KINDS:
            out["kind"] = "mcp"
        elif k:
            out["kind"] = k
    # 2) alias label
    if not out.get("label"):
        for alt in ("name", "title"):
            if out.get(alt):
                out["label"] = out[alt]
                break
    # 3) alias config
    if not isinstance(out.get("config"), dict):
        for alt in ("params", "parameters", "settings", "options"):
            cand = out.get(alt)
            if isinstance(cand, dict):
                out["config"] = dict(cand)
                break
    # 4) params di dalam config -> digabung
    cfg = out.get("config")
    if isinstance(cfg, dict):
        merged = dict(cfg)
        for alt in ("params", "parameters"):
            inner = merged.get(alt)
            if isinstance(inner, dict):
                for k, v in inner.items():
                    merged.setdefault(k, v)
                merged.pop(alt, None)
        # alias field yang sering dipakai model
        for src, dst in (("spreadsheet", "spreadsheet_id"),
                         ("sheet", "sheet_name"),
                         ("sheetName", "sheet_name"),
                         ("spreadsheetId", "spreadsheet_id"),
                         ("to", "tujuan"), ("chatId", "chat_id"),
                         ("message", "pesan"), ("text", "isi")):
            if src in merged and dst not in merged:
                merged[dst] = merged[src]
        out["config"] = merged
    return out


def _normalize_edge(edge: dict) -> dict:
    out = dict(edge)
    if "source" not in out:
        for alt in ("from", "src", "start"):
            if alt in out:
                out["source"] = out[alt]
                break
    if "target" not in out:
        for alt in ("to", "dest", "destination", "end"):
            if alt in out:
                out["target"] = out[alt]
                break
    return out


def normalize_workflow_payload(payload: Any) -> dict:
    """Kembalikan dict spec yang hopefully bisa divalidasi.

    Selalu mengembalikan dict; tidak pernah melempar. Bentuk yang tidak
    dikenali diteruskan apa adanya agar pesan error dari validator tetap
    informatif (dan bukan kabut karena exception di sini).
    """
    root = _as_dict(payload)
    if root is None:
        return {}
    root = _unwrap(root)
    out = dict(root)
    nodes = out.get("nodes")
    if isinstance(nodes, list):
        out["nodes"] = [_normalize_node(n) for n in nodes if isinstance(n, dict)]
    edges = out.get("edges")
    if isinstance(edges, list):
        out["edges"] = [_normalize_edge(e) for e in edges if isinstance(e, dict)]
    return out