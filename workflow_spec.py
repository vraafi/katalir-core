"""Kontrak WorkflowSpec — jembatan "chat → workflow JSON → canvas".

KENAPA MODUL TERPISAH (bukan dict bebas di prompt):
Model bahasa bisa mengarang bentuk JSON apa pun. Tanpa kontrak yang
divalidasi, kesalahan baru muncul di canvas (node hilang / edge menunjuk id
yang tidak ada) dan user hanya melihat "tidak jalan". Di sini JSON divalidasi
+ dinormalkan SEBELUM pernah menyentuh frontend, dan kegagalan dikembalikan
sebagai daftar kesalahan yang bisa dibaca model (supaya ia memperbaiki
sendiri) — pola "structured output + repair loop".

Bentuknya SENGAJA 1:1 dengan tipe canvas yang sudah ada
(`nexus-frontend/src/features/builder/types.ts` FlowNode dan
`store/canvas-store.ts` setNodes/setEdges) supaya renderer 2.2 tidak perlu
menerjemahkan apa pun lagi.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

# FASE 2.6: kelengkapan config provider diperiksa memakai tabel yang sama dengan
# eksekusi, supaya "draf valid" == "draf bisa dijalankan".
import provider_registry

# Kind node HARUS sama dengan META di types.ts (trigger | agent | mcp).
Kind = Literal["trigger", "agent", "mcp"]

# Provider yang punya jalur kredensial (dipakai alur credential prompt 2.3).
# BUG FIX 2026-10-03: `google_calendar` DITAMBAHKAN.
#
# `provider_registry.REQUIRED_CONFIG` sudah punya entri google_calendar
# ("nama_acara", "waktu") dan `tambah_agenda_calendar` sudah terdaftar sebagai
# tool, tapi nama provider-nya TIDAK ada di sini. Akibatnya `validate_spec`
# masuk cabang `prov not in KNOWN_PROVIDERS` -> hanya memberi WARNING, tanpa
# memeriksa kelengkapan config. Akibatnya node kalender tanpa `waktu` lolos
# validasi lalu gagal saat eksekusi.
#
# Itu persis keluhan n8n yang dipetakan sebagai "hint tidak lengkap": draf
# dianggap valid padahal tidak bisa dijalankan.
#
# Daftar ini sekarang WAJIB sama dengan kunci `REQUIRED_CONFIG`; test
# `tests/test_n8n_ai_comparison.py::test_required_config_ada_per_provider`
# mengunci kedua sisi supaya tidak ada lagi yang luput.
KNOWN_PROVIDERS = (
    "telegram",
    "gmail",
    "google_sheets",
    "google_calendar",
    "slack",
    "http",
    "whatsapp",
    # 2026-10-06: jembatan katalog MCP agentgateway. Test
    # tests/test_n8n_ai_comparison.py::test_required_config_ada_per_provider
    # mengunci daftar ini agar sama dengan kunci REQUIRED_CONFIG — menambah
    # provider di satu sisi tanpa sisi lain membuat draf lolos validasi lalu
    # gagal saat eksekusi.
    "gateway",
)


class SpecNode(BaseModel):
    id: str = Field(min_length=1)
    kind: Kind
    label: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    position: dict[str, float] | None = None


class SpecEdge(BaseModel):
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)


class WorkflowSpec(BaseModel):
    name: str = Field(default="Workflow", min_length=1)
    nodes: list[SpecNode] = Field(min_length=1)
    edges: list[SpecEdge] = Field(default_factory=list)


def validate_spec(raw: str) -> dict[str, Any]:
    """Validasi + normalkan JSON workflow. SELALU mengembalikan dict.

      {"ok": True,  "spec": {...}, "warnings": [...]}
      {"ok": False, "errors": [...], "hint": "cara memperbaiki"}

    `errors` sengaja spesifik + menyebut id yang bermasalah, karena hasil ini
    dikirim balik ke model sebagai umpan perbaikan (repair loop).
    """
    text = strip_code_fence(raw)
    if not text:
        return {"ok": False, "errors": ["spec_json kosong"], "hint": "kirim JSON workflow"}

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "errors": [f"JSON tidak valid: {exc.msg} (baris {exc.lineno} kolom {exc.colno})"],
            "hint": "keluarkan JSON murni tanpa komentar/teks tambahan",
        }
    if not isinstance(parsed, dict):
        return {"ok": False, "errors": ["root JSON harus object"],
                "hint": "root = {name,nodes,edges}"}

    try:
        spec = WorkflowSpec.model_validate(parsed)
    except ValidationError as exc:
        details = []
        for err in exc.errors()[:8]:
            loc = ".".join(str(p) for p in err.get("loc", ()))
            details.append(f"{loc}: {err.get('msg')}")
        return {"ok": False, "errors": details,
                "hint": "perbaiki field yang disebut di atas"}

    errors: list[str] = []
    warnings: list[str] = []

    ids = [n.id for n in spec.nodes]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        errors.append(f"id node duplikat: {', '.join(dupes)}")

    known = set(ids)
    for e in spec.edges:
        for end, label in ((e.source, "source"), (e.target, "target")):
            if end not in known:
                errors.append(f"edge {label} '{end}' tidak ada di daftar nodes")

    if not [n for n in spec.nodes if n.kind == "trigger"]:
        errors.append("tidak ada node kind='trigger' (tanpa pemicu workflow tak bisa jalan)")

    for n in spec.nodes:
        if n.kind != "mcp":
            continue
        prov = str(n.config.get("provider") or "").strip().lower()
        if not prov:
            errors.append(f"node mcp '{n.id}' wajib punya config.provider "
                          f"(contoh: {', '.join(KNOWN_PROVIDERS[:3])})")
            continue
        if prov not in KNOWN_PROVIDERS:
            # ANTI-FABRIKASI (brief 2026-10-03, kelemahan n8n #7): provider
            # yang tidak dikenal TIDAK boleh lolos sebagai sekadar warning.
            # Dulu `x_twitter`, `gdrive`, atau nama karangan lain diterima
            # sebagai "valid", padahal saat eksekusi tidak ada satu pun
            # handler yang bisa memanggilnya - user baru sadar setelah
            # menunggu. Aturan: pakai provider yang terdaftar, atau pakai
            # `http` generik dengan URL.
            errors.append(
                f"node mcp '{n.id}' memakai provider '{prov}' yang tidak "
                f"dikenal. Pilihan yang tersedia: "
                f"{', '.join(KNOWN_PROVIDERS)}. Untuk API lain pakai "
                "provider 'http' dengan config.url."
            )
            continue
        # FASE 2.6: draf yang tidak bisa dijalankan DITOLAK di sini, bukan gagal
        # saat eksekusi sebagai HTTP 400 dari provider. Model lalu memanggil ulang
        # tool dengan config lengkap (repair loop) — atau bertanya ke user dulu.
        # Konten (pesan/isi) boleh datang dari node hulu; tujuan (chat_id/url/..)
        # tidak — itu keputusan user.
        has_upstream = any(e.target == n.id for e in spec.edges)
        missing = provider_registry.missing_required(prov, n.config, None, has_upstream)
        if missing:
            errors.append(f"node mcp '{n.id}' (provider {prov}) belum lengkap: "
                          f"{', '.join(missing)} wajib ada di config")

    # TRIASE ADVERSARIAL 2026-10-06 (BUG-1/BUG-6): config yang TIDAK pernah
    # dibaca runner membuat "draf bohong" - node berlabel IF / batch /
    # sub-workflow tersimpan tapi tetap dieksekusi linear tanpa error
    # (silent failure by design). Tolak di sini supaya model jujur lewat
    # repair loop, bukan mengaku bisa (bukti: skenario S1/S2/S5).
    _DEAD_CONFIG_KEYS = (
        "condition", "batch_size", "sub_workflow", "subworkflow",
        "split_in_batches", "delegate", "delegation",
    )
    for n in spec.nodes:
        dead = [k for k in _DEAD_CONFIG_KEYS if k in (n.config or {})]
        if dead:
            errors.append(
                f"node '{n.id}' memakai config '{', '.join(dead)}' yang tidak "
                "didukung runtime (tidak ada IF/cabang, Split In Batches, atau "
                "sub-workflow). Hapus kunci itu; jalankan logika kondisi di "
                "dalam prompt agent atau susun workflow linear berurutan."
            )

    # TRIASE ADVERSARIAL 2026-10-06 (BUG-6): placeholder {{...}} dicek saat
    # SAVE, bukan baru ketahuan saat eksekusi:
    #   {{tanpa_titik}}   placeholder isi-user (chat_id, url, ...) -> warning
    #                     supaya user tahu ada nilai yang belum diisi di kanvas.
    #   {{akar.segmen}}   ekspresi antar-node -> akar wajib ada di workflow
    #                     (id node) atau alias; selain itu ERROR di sini
    #                     (runtime juga menolak: PlaceholderResolutionError).
    _PH_RX = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
    _PH_ALIASES = {"trigger", "input", "payload", "data"}
    _ph_roots = set(ids) | _PH_ALIASES

    def _str_leaves(v: Any):
        if isinstance(v, str):
            yield v
        elif isinstance(v, dict):
            for x in v.values():
                yield from _str_leaves(x)
        elif isinstance(v, list):
            for x in v:
                yield from _str_leaves(x)

    for n in spec.nodes:
        for key, val in (n.config or {}).items():
            for s in _str_leaves(val):
                for m in _PH_RX.finditer(s):
                    expr = m.group(1).strip()
                    if "." not in expr:
                        warnings.append(
                            f"node '{n.id}' config '{key}': placeholder "
                            f"{{{{{expr}}}}} belum diisi - user harus mengisi "
                            "nilai ini di kanvas sebelum workflow dijalankan")
                        continue
                    head = expr.split(".", 1)[0].strip()
                    if head and head not in _ph_roots:
                        errors.append(
                            f"node '{n.id}' memakai ekspresi {{{{{expr}}}}} "
                            f"tapi akar '{head}' tidak ada di workflow (id "
                            f"node: {', '.join(sorted(set(ids)))} atau alias "
                            "trigger/input/payload/data). Perbaiki id node "
                            "atau hapus referensi itu.")

    if not spec.edges and len(spec.nodes) > 1:
        warnings.append("tidak ada edge: node akan tampil terpisah di canvas")

    if errors:
        return {"ok": False, "errors": errors,
                "hint": "perbaiki lalu panggil generate_workflow_json lagi"}

    return {"ok": True, "spec": _normalize(spec), "warnings": warnings}


def _normalize(spec: WorkflowSpec) -> dict[str, Any]:
    """Bentuk final untuk canvas: posisi ada, edge punya id deterministik.

    Posisi dihitung otomatis bila model tidak memberikannya (model tidak bisa
    menebak koordinat yang bagus) — kolom per langkah dari kiri ke kanan
    mengikuti kedalaman topologi.
    """
    depths = _layer_by_depth(spec)
    counters: dict[int, int] = {}
    nodes: list[dict[str, Any]] = []
    for n in spec.nodes:
        d = depths.get(n.id, 0)
        idx = counters.get(d, 0)
        counters[d] = idx + 1
        pos = n.position or {}
        nodes.append({
            "id": n.id,
            "type": n.kind,               # xyflow memetakan `type` -> custom node
            "position": {"x": float(pos.get("x", 80 + d * 260)),
                         "y": float(pos.get("y", 80 + idx * 140))},
            "data": {"kind": n.kind, "label": n.label or n.id, "config": n.config},
        })

    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for e in spec.edges:
        key = (e.source, e.target)
        if key in seen:
            continue                  # dedupe: edge ganda tidak menambah nilai
        seen.add(key)
        # id edge deterministik — pola sama dengan connectionEdgeId() di canvas-store.
        edges.append({
            "id": f"rf-{json.dumps([e.source, None, e.target, None], separators=(',', ':'))}",
            "source": e.source,
            "target": e.target,
            "animated": True,
            "style": {"stroke": "rgb(var(--accent))", "strokeWidth": 2},
        })

    return {"name": spec.name, "nodes": nodes, "edges": edges}


def _layer_by_depth(spec: WorkflowSpec) -> dict[str, int]:
    """Kedalaman = panjang jalur terpanjang dari sumber tanpa predecessor."""
    adj: dict[str, list[str]] = {n.id: [] for n in spec.nodes}
    indeg: dict[str, int] = {n.id: 0 for n in spec.nodes}
    for e in spec.edges:
        if e.source in adj and e.target in adj:
            adj[e.source].append(e.target)
            indeg[e.target] += 1

    depth = {n.id: 0 for n in spec.nodes}
    queue = [i for i, v in indeg.items() if v == 0]
    guard = 0
    while queue and guard < 10_000:      # guard: edge bisa membentuk siklus
        guard += 1
        cur = queue.pop(0)
        for nxt in adj[cur]:
            depth[nxt] = max(depth[nxt], depth[cur] + 1)
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    return depth


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def strip_code_fence(raw: str) -> str:
    """Buang pagar ```json yang sering ditambahkan model di sekeliling JSON."""
    return _FENCE.sub("", (raw or "").strip()).strip()