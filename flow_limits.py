# -*- coding: utf-8 -*-
"""flow_limits.py — SUMBER KEBENARAN TUNGGAL untuk batas graf workflow.

Dibuat dari temuan hard test: sebelumnya ADA TIGA nilai berbeda untuk konsep
yang sama, sehingga sebuah workflow bisa DITOLAK di satu jalur tulis tapi
DITERIMA di jalur lain:

    api_server.MAX_WORKFLOW_NODES   = 500     (POST/PUT /workflows)
    mcp_server.MAX_FLOW_NODES       = 200     (tool MCP create_workflow)
    workflow_templates.MAX_NODES    = 100     (simpan template kustom)

    api_server.MAX_WORKFLOW_EDGES   = 1000
    workflow_templates.MAX_EDGES    = 200

Akibatnya user bisa membuat workflow 300 node lewat API, lalu gagal
menyimpannya sebagai template (batas 100) dan gagal mengirimnya lewat MCP
(batas 200) — tanpa penjelasan yang konsisten.

Semua jalur tulis sekarang mengimpor dari sini. Ubah di SATU tempat.
Nilai dapat di-override lewat env agar operator bisa menyesuaikan tanpa
deploy ulang kode.
"""
from __future__ import annotations

import os


def _env_int(name: str, default: int) -> int:
    try:
        v = int(str(os.getenv(name, "")).strip() or default)
    except (TypeError, ValueError):
        return default
    return v if v > 0 else default


# Batas keras graf workflow — berlaku untuk SEMUA jalur tulis.
MAX_FLOW_NODES = _env_int("MAX_FLOW_NODES", 500)
MAX_FLOW_EDGES = _env_int("MAX_FLOW_EDGES", 1000)

# Batas "disarankan" (bukan penolakan) — dipakai template bawaan & UI.
# Sengaja TERPISAH dari batas keras supaya template tetap ringkas tanpa
# membuat jalur tulis jadi tidak konsisten.
RECOMMENDED_TEMPLATE_NODES = 100


def describe() -> dict:
    """Untuk /version, UI, dan observabilitas."""
    return {
        "max_flow_nodes": MAX_FLOW_NODES,
        "max_flow_edges": MAX_FLOW_EDGES,
        "recommended_template_nodes": RECOMMENDED_TEMPLATE_NODES,
    }
