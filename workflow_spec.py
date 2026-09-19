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

# Kind node HARUS sama dengan META di types.ts (trigger | agent | mcp).
Kind = Literal["trigger", "agent", "mcp"]

# Provider yang punya jalur kredensial (dipakai alur credential prompt 2.3).
KNOWN_PROVIDERS = ("telegram", "gmail", "google_sheets", "slack", "http", "whatsapp")


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
        if n.kind == "mcp":
            prov = str(n.config.get("provider") or "").strip().lower()
            if not prov:
                errors.append(f"node mcp '{n.id}' wajib punya config.provider "
                              f"(contoh: {', '.join(KNOWN_PROVIDERS[:3])})")
            elif prov not in KNOWN_PROVIDERS:
                warnings.append(f"provider '{prov}' belum punya jalur kredensial bawaan")

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