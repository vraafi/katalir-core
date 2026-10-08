# ai_workflow_gen.py — Fitur #8: AI Workflow Generator dari video/screenshot
# ======================================================================
# User mengunggah screenshot/video demo; model vision menganalisis langkah;
# sistem mengekstrak langkah -> membangun workflow JSON (DAG) siap-preview.
#
# RISET (Okt 2026): model vision (Gemini/GPT-4V class) dipakai lewat SEAM
# `vision_fn` yang disuntik -> logika ekstraksi & pembangunan DAG dapat
# di-hard-test deterministik tanpa memanggil model. Produksi menyambungkan
# `vision_fn` ke klien vision (Gemini) yang sudah ada di stack.
#
# KEAMANAN: validasi berkas (ekstensi, MIME, ukuran) sebelum diproses; batas
# 100 MB; nama berkas tidak pernah dipakai sebagai path (hanya metadata).
# ======================================================================

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Callable, Optional

#: Batas ukuran unggahan (100 MB).
MAX_MEDIA_BYTES = 100 * 1024 * 1024

ALLOWED_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
ALLOWED_VIDEO_EXT = (".mp4", ".mov", ".webm", ".mkv", ".avi")
ALLOWED_EXT = ALLOWED_IMAGE_EXT + ALLOWED_VIDEO_EXT

ALLOWED_MIME = (
    "image/png", "image/jpeg", "image/webp", "image/gif", "image/bmp",
    "video/mp4", "video/quicktime", "video/webm", "video/x-matroska",
)

#: Ambang keyakinan minimum sebelum workflow dianggap siap (tanpa klarifikasi).
CONFIDENCE_THRESHOLD = 0.6

#: Pemetaan aksi -> jenis node engine.
_KIND_MAP = {
    "open": "code", "navigate": "code", "click": "code", "type": "code",
    "input": "code", "submit": "code", "download": "code", "upload": "code",
    "api": "mcp", "http": "mcp", "request": "mcp", "webhook": "mcp",
    "ai": "agent", "agent": "agent", "prompt": "agent", "summarize": "agent",
    "approve": "wait_for_human", "review": "wait_for_human",
    "check": "guardrails", "validate": "guardrails",
    "search": "vector_store", "embed": "vector_store", "retrieve": "vector_store",
}

_LABELS = {
    "id": {"trigger": "Mulai", "step": "Langkah", "condition": "Jika",
           "on_error": "Jika gagal", "true": "Ya", "false": "Tidak"},
    "en": {"trigger": "Start", "step": "Step", "condition": "If",
           "on_error": "On error", "true": "Yes", "false": "No"},
}


class MediaError(ValueError):
    """Berkas unggahan tidak valid (ekstensi/MIME/ukuran)."""


class GenerationError(Exception):
    """Model vision gagal / keluaran tidak dapat dipakai."""


# ---------------------------------------------------------------------------
# Validasi unggahan
# ---------------------------------------------------------------------------

def _ext(filename: str) -> str:
    return os.path.splitext(filename or "")[1].lower()


def validate_media(filename: str, size_bytes: int,
                   mime: str = "") -> dict:
    """Validasi berkas. Return metadata. Raise MediaError bila tidak valid."""
    ext = _ext(filename)
    if ext not in ALLOWED_EXT:
        raise MediaError(f"ekstensi tidak diizinkan: {ext or '(kosong)'}")
    if mime and mime not in ALLOWED_MIME:
        raise MediaError(f"MIME tidak diizinkan: {mime}")
    if size_bytes is None or size_bytes <= 0:
        raise MediaError("berkas kosong")
    if size_bytes > MAX_MEDIA_BYTES:
        raise MediaError(
            f"berkas terlalu besar: {size_bytes} byte > {MAX_MEDIA_BYTES} byte")
    jenis = "video" if ext in ALLOWED_VIDEO_EXT else "image"
    return {"filename": os.path.basename(filename), "ext": ext, "kind": jenis,
            "size_bytes": size_bytes, "mime": mime or ""}


# ---------------------------------------------------------------------------
# Analisis (vision_fn disuntik)
# ---------------------------------------------------------------------------

def analyze_media(media: bytes, filename: str, vision_fn: Callable,
                  language: str = "id", timeout: float = 30.0) -> dict:
    """Panggil `vision_fn(media, filename, language)` -> langkah terstruktur.

    `vision_fn` WAJIB mengembalikan dict:
      {"steps": [{"action","target","condition"?,"on_error"?,"detail"?}],
       "confidence": float, "ambiguous": bool, "questions": [str]}
    """
    if vision_fn is None:
        raise GenerationError("vision_fn tidak tersedia")
    t0 = time.time()
    try:
        raw = vision_fn(media, filename, language)
    except Exception as exc:  # noqa: BLE001 - error model -> GenerationError
        raise GenerationError(f"vision gagal: {type(exc).__name__}") from exc
    dt = time.time() - t0
    if dt > timeout:
        # model lambat: tetap kembalikan hasil bila ada, beri catatan
        pass
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GenerationError(f"keluaran model bukan JSON: {exc}") from exc
    if not isinstance(raw, dict) or "steps" not in raw:
        raise GenerationError("keluaran model tidak memuat 'steps'")
    langkah = []
    for s in raw.get("steps") or []:
        if not isinstance(s, dict):
            continue
        langkah.append({
            "action": str(s.get("action") or "step").strip().lower(),
            "target": str(s.get("target") or s.get("detail") or "").strip(),
            "condition": s.get("condition") or None,
            "on_error": s.get("on_error") or None,
            "detail": s.get("detail") or "",
        })
    return {"steps": langkah,
            "confidence": float(raw.get("confidence", 0.0) or 0.0),
            "ambiguous": bool(raw.get("ambiguous", False)),
            "questions": list(raw.get("questions") or []),
            "duration_s": round(dt, 3)}


# ---------------------------------------------------------------------------
# Bangun workflow (DAG)
# ---------------------------------------------------------------------------

def _kind(action: str) -> str:
    return _KIND_MAP.get((action or "").lower(), "code")


def _label(language: str, key: str) -> str:
    return _LABELS.get(language, _LABELS["en"]).get(key, key)


def build_workflow(analysis: dict, name: str = "AI Generated",
                   language: str = "id") -> dict:
    """Langkah -> `flow_data` {nodes, edges} yang valid untuk engine."""
    langkah = analysis.get("steps") or []
    if not langkah:
        raise GenerationError("tidak ada langkah untuk dibangun")
    L = _LABELS.get(language, _LABELS["en"])
    nodes: list[dict] = []
    edges: list[dict] = []

    trigger_id = "trigger"
    nodes.append({"id": trigger_id, "kind": "trigger", "label": L["trigger"],
                  "config": {"trigger_type": "manual"}})

    id_map: list[str] = []
    for i, s in enumerate(langkah):
        nid = f"step_{i + 1}"
        id_map.append(nid)
        node = {
            "id": nid,
            "kind": _kind(s["action"]),
            "label": f"{L['step']} {i + 1}: {s['action']}"
                     + (f" {s['target']}" if s["target"] else ""),
            "config": {"action": s["action"], "target": s["target"],
                       "language": language},
        }
        if s.get("condition"):
            node["config"]["condition"] = s["condition"]
            node["branch"] = True
        if s.get("on_error"):
            node["config"]["on_error"] = s["on_error"]
            node["on_error"] = s["on_error"]
        nodes.append(node)

    # edge berurutan: trigger -> step_1 -> step_2 ...
    rantai = [trigger_id] + id_map
    for a, b in zip(rantai, rantai[1:]):
        edges.append({"source": a, "target": b, "label": ""})

    # cabang kondisi: step dengan condition -> dua label true/false ke berikutnya
    for i, s in enumerate(langkah):
        if s.get("condition") and i + 1 < len(id_map):
            nid = id_map[i]
            nxt = id_map[i + 1]
            edges.append({"source": nid, "target": nxt,
                          "label": L["true"], "branch": "true"})
            edges.append({"source": nid, "target": nxt,
                          "label": L["false"], "branch": "false"})

    return {"name": name, "nodes": nodes, "edges": edges,
            "meta": {"generated_by": "ai_workflow_gen", "language": language,
                     "confidence": analysis.get("confidence", 0.0)}}


def generate(media: bytes, filename: str, vision_fn: Callable,
             language: str = "id", name: str = "AI Generated",
             mime: str = "") -> dict:
    """Pipeline lengkap: validasi -> analisis -> bangun workflow.

    Return {workflow, needs_clarification, questions, confidence, warnings}.
    """
    warnings: list[str] = []
    try:
        meta = validate_media(filename, len(media or b""), mime)
    except MediaError as exc:
        raise MediaError(str(exc))
    analysis = analyze_media(media, meta["filename"], vision_fn, language)

    perlu = (analysis["ambiguous"]
             or analysis["confidence"] < CONFIDENCE_THRESHOLD
             or not analysis["steps"])
    if analysis["ambiguous"] and not analysis["questions"]:
        analysis["questions"] = [
            "Apa langkah pertama yang harus dijalankan?" if language == "id"
            else "What is the first step to run?"]
    if not analysis["steps"]:
        return {"workflow": None, "needs_clarification": True,
                "questions": analysis["questions"] or ["Detail langkah kosong"],
                "confidence": analysis["confidence"], "warnings": warnings,
                "analysis": analysis}
    workflow = build_workflow(analysis, name=name, language=language)
    if analysis["confidence"] < CONFIDENCE_THRESHOLD:
        warnings.append("keyakinan rendah — tinjau sebelum menyimpan")
    return {"workflow": workflow, "needs_clarification": perlu,
            "questions": analysis["questions"],
            "confidence": analysis["confidence"], "warnings": warnings,
            "analysis": analysis, "media": meta}
