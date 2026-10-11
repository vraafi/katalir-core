"""workflow_ops.py — Edit workflow SECARA SEBAGIAN lewat daftar operasi.

Referensi (skill-first, brief 11 Okt 2026):
  `skills/n8n-autopilot/skills/n8n-autopilot/SKILL.md` Phase 3.2 —
  n8n tidak punya endpoint "edit sebagian"; ia memakai pola
  `n8n_update_partial_workflow({id, intent, operations:[{type:"addNode"|
  "addConnection"|"updateNode"|...}]})`. `skills/flowgent` (NL -> workflow)
  menunjukkan sisi bahasa alaminya.

Pembagian tanggung jawab (inilah alasan modul ini deterministik):
  - Lapisan LLM (flowgent-style) hanya perlu MENGHASILKAN daftar operasi.
  - PENERAPAN + VALIDASI + ROLLBACK tidak boleh bergantung pada model.
    Modul ini murni (tanpa I/O) sehingga bisa diuji tanpa LLM, tanpa DB,
    dan tanpa jaringan — dan hasilnya sama setiap kali (deterministik).

Sifat penting:
  * ATOMIK — bila satu operasi gagal, dokumen asli dikembalikan utuh
    (`flow_data` asli, `applied=0`). Tidak pernah ada dokumen setengah jadi.
  * VALIDASI menyebut id yang bermasalah (pola error Katalir yang sudah ada:
    pesan dikirim balik ke model sebagai umpan perbaikan / repair loop).
  * AMAN — menolak kunci berbahaya (prototype pollution), jumlah operasi
    dibatasi, id node unik, edge ke node asing DITOLAK (mencegah node hantu
    hasil halusinasi model).
"""
from __future__ import annotations

import copy
from typing import Any

# --------------------------------------------------------------------------
# Batas keras (dipakai juga sebagai uji keamanan/DoS).
# Batas graf mengimpor SUMBER KEBENARAN TUNGGAL (flow_limits.py) supaya tidak
# lahir nilai ke-4 untuk konsep yang sama (lihat catatan di flow_limits.py).
# --------------------------------------------------------------------------
MAX_OPS = 200

try:  # pragma: no cover - bergantung impor
    from flow_limits import MAX_FLOW_EDGES as MAX_EDGES  # noqa: N811
    from flow_limits import MAX_FLOW_NODES as MAX_NODES  # noqa: N811
except Exception:  # noqa: BLE001
    MAX_NODES = 500
    MAX_EDGES = 1000

SUPPORTED_OPS = (
    "addNode",
    "updateNode",
    "removeNode",
    "addConnection",
    "removeConnection",
)

# Kunci yang tidak boleh masuk ke dokumen (prototype pollution).
_FORBIDDEN_KEYS = frozenset({"__proto__", "constructor", "prototype"})

# Kunci yang boleh diubah lewat updateNode (whitelist, bukan blacklist).
_UPDATABLE_KEYS = frozenset(
    {"label", "config", "position", "data", "type", "kind", "notes", "name"}
)

# Cadangan bila execution_engine tidak bisa diimpor (mis. saat modul diuji
# terpisah). Sengaja konservatif: kind asing DITOLAK, bukan diterima diam-diam.
_DEFAULT_KINDS = frozenset(
    {
        "trigger", "agent", "mcp-tool", "code", "http", "condition",
        "transform", "guardrail", "hitl", "subworkflow", "evaluator",
        "memory", "loop", "merge", "delay", "webhook", "schedule",
    }
)


def _allowed_kinds() -> frozenset[str]:
    try:  # pragma: no cover - bergantung lingkungan
        import execution_engine as ee

        return frozenset(k.value for k in ee.NodeKind)
    except Exception:  # noqa: BLE001
        return _DEFAULT_KINDS


class OpError(ValueError):
    """Operasi tidak valid. Pesan SELALU menyebut op/id yang bermasalah."""


# --------------------------------------------------------------------------
# Helper bentuk dokumen (mendukung bentuk xyflow `data.kind` DAN bentuk spec
# `kind` supaya modul ini bisa dipakai di kedua sisi pipeline).
# --------------------------------------------------------------------------
def _node_id(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    return str(node.get("id") or node.get("node_id") or "")


def _node_kind(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    data = node.get("data")
    if isinstance(data, dict) and data.get("kind"):
        return str(data.get("kind"))
    return str(node.get("kind") or "")


def _is_xyflow(nodes: list[Any]) -> bool:
    """True bila dokumen memakai bentuk xyflow (node punya `data`)."""
    for n in nodes:
        if isinstance(n, dict) and isinstance(n.get("data"), dict):
            return True
    return False


def _deep_has_forbidden(value: Any, path: str = "") -> str | None:
    """Cari kunci terlarang secara rekursif. Return path pertama atau None."""
    if isinstance(value, dict):
        for k, v in value.items():
            if str(k) in _FORBIDDEN_KEYS:
                return f"{path}.{k}" if path else str(k)
            found = _deep_has_forbidden(v, f"{path}.{k}" if path else str(k))
            if found:
                return found
    elif isinstance(value, list):
        for i, v in enumerate(value):
            found = _deep_has_forbidden(v, f"{path}[{i}]")
            if found:
                return found
    return None


def _index(nodes: list[dict]) -> dict[str, dict]:
    return {_node_id(n): n for n in nodes if _node_id(n)}


def _edge_key(source: str, target: str) -> tuple[str, str]:
    return (str(source), str(target))


def _edge_set(edges: list[dict]) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for e in edges:
        if not isinstance(e, dict):
            continue
        a = str(e.get("source") or e.get("from") or "")
        b = str(e.get("target") or e.get("to") or "")
        if a and b:
            out.add((a, b))
    return out


# --------------------------------------------------------------------------
# Inti: terapkan operasi
# --------------------------------------------------------------------------
def apply_operations(
    flow_data: dict,
    operations: list[dict],
    *,
    intent: str = "",
    dry_run: bool = False,
    max_ops: int = MAX_OPS,
) -> dict:
    """Terapkan `operations` ke `flow_data` secara ATOMIK.

    Return dict:
      {
        "ok": bool,            # semua operasi berhasil diterapkan
        "flow_data": dict,     # dokumen BARU (ok=True) atau dokumen ASLI (ok=False)
        "applied": int,        # jumlah operasi yang benar-benar diterapkan
        "errors": [str, ...],  # daftar galat (kosong bila ok)
        "diff": dict|None,     # ringkasan perubahan (lihat environments.diff_flow)
        "intent": str,
        "dry_run": bool,
      }

    `dry_run=True` memvalidasi + menghitung diff tanpa mengubah apa pun
    (dipakai untuk pratinjau / "debug" sebelum commit).
    """
    if not isinstance(flow_data, dict):
        return _fail(flow_data, ["flow_data harus berupa objek {nodes, edges}."],
                     intent, dry_run)
    if not isinstance(operations, list):
        return _fail(flow_data, ["operations harus berupa daftar."], intent, dry_run)
    if len(operations) > max_ops:
        return _fail(
            flow_data,
            [f"terlalu banyak operasi: {len(operations)} > batas {max_ops}."],
            intent,
            dry_run,
        )

    original = flow_data
    work = copy.deepcopy(flow_data)
    nodes = work.get("nodes")
    edges = work.get("edges")
    if not isinstance(nodes, list):
        nodes = []
    if not isinstance(edges, list):
        edges = []
    work["nodes"] = nodes
    work["edges"] = edges
    xyflow = _is_xyflow(nodes)

    errors: list[str] = []
    applied = 0

    for idx, op in enumerate(operations):
        try:
            _apply_one(work, nodes, edges, op, xyflow=xyflow)
            applied += 1
        except OpError as exc:
            errors.append(f"operasi #{idx} ({_op_type(op)}): {exc}")
            break  # ATOMIK: berhenti di galat pertama

    if errors:
        return _fail(original, errors, intent, dry_run)

    # Batas keras pasca-terap.
    if len(nodes) > MAX_NODES:
        return _fail(
            original,
            [f"jumlah node {len(nodes)} melebihi batas {MAX_NODES}."],
            intent,
            dry_run,
        )
    if len(edges) > MAX_EDGES:
        return _fail(
            original,
            [f"jumlah edge {len(edges)} melebihi batas {MAX_EDGES}."],
            intent,
            dry_run,
        )

    diff = _diff(original, work)
    return {
        "ok": True,
        "flow_data": original if dry_run else work,
        "applied": applied,
        "errors": [],
        "diff": diff,
        "intent": intent,
        "dry_run": dry_run,
    }


def validate_operations(
    flow_data: dict, operations: list[dict], *, max_ops: int = MAX_OPS
) -> dict:
    """Dry-run: cek operasi tanpa menerapkannya. Selalu mengembalikan dict."""
    res = apply_operations(flow_data, operations, dry_run=True, max_ops=max_ops)
    return {
        "ok": res["ok"],
        "errors": res["errors"],
        "diff": res["diff"],
        "applied": res["applied"],
    }


def _op_type(op: Any) -> str:
    if isinstance(op, dict):
        return str(op.get("type") or op.get("op") or "?")
    return "?"


def _fail(flow_data: Any, errors: list[str], intent: str, dry_run: bool) -> dict:
    return {
        "ok": False,
        "flow_data": flow_data,
        "applied": 0,
        "errors": list(errors),
        "diff": None,
        "intent": intent,
        "dry_run": dry_run,
    }


def _apply_one(
    work: dict, nodes: list[dict], edges: list[dict], op: Any, *, xyflow: bool
) -> None:
    if not isinstance(op, dict):
        raise OpError("operasi harus berupa objek.")
    otype = _op_type(op)
    if otype not in SUPPORTED_OPS:
        raise OpError(
            f"jenis operasi tidak dikenal: '{otype}' "
            f"(didukung: {', '.join(SUPPORTED_OPS)})."
        )

    bad = _deep_has_forbidden(op)
    if bad:
        raise OpError(f"kunci terlarang '{bad}' pada operasi.")

    if otype == "addNode":
        _op_add_node(nodes, op, xyflow=xyflow)
    elif otype == "updateNode":
        _op_update_node(nodes, op, xyflow=xyflow)
    elif otype == "removeNode":
        _op_remove_node(nodes, edges, op)
    elif otype == "addConnection":
        _op_add_connection(nodes, edges, op)
    elif otype == "removeConnection":
        _op_remove_connection(edges, op)


def _op_add_node(nodes: list[dict], op: dict, *, xyflow: bool) -> None:
    node = op.get("node")
    if not isinstance(node, dict):
        raise OpError("addNode butuh 'node' berupa objek.")
    nid = _node_id(node)
    if not nid:
        raise OpError("addNode: 'node.id' wajib dan tidak boleh kosong.")
    if nid in _index(nodes):
        raise OpError(f"addNode: id '{nid}' sudah ada (id node harus unik).")
    kind = _node_kind(node)
    if not kind:
        raise OpError(f"addNode: node '{nid}' tidak punya kind/data.kind.")
    if kind not in _allowed_kinds():
        raise OpError(f"addNode: kind '{kind}' tidak dikenal pada node '{nid}'.")
    # Normalisasi ringan supaya bentuk dokumen tetap konsisten.
    new = copy.deepcopy(node)
    if xyflow and not isinstance(new.get("data"), dict):
        new = {
            "id": nid,
            "type": new.get("type") or kind,
            "position": new.get("position") or {},
            "data": {
                "kind": kind,
                "label": new.get("label") or kind,
                "config": new.get("config") or {},
            },
        }
    elif not xyflow and "kind" not in new:
        new["kind"] = kind
    nodes.append(new)


def _op_update_node(nodes: list[dict], op: dict, *, xyflow: bool) -> None:
    nid = str(op.get("id") or op.get("nodeId") or op.get("nodeName") or "")
    if not nid:
        raise OpError("updateNode: 'id' wajib.")
    updates = op.get("updates")
    if not isinstance(updates, dict) or not updates:
        raise OpError(f"updateNode: 'updates' untuk node '{nid}' kosong/invalid.")
    target = _index(nodes).get(nid)
    if target is None:
        raise OpError(f"updateNode: node '{nid}' tidak ditemukan.")
    for key in updates:
        if str(key) not in _UPDATABLE_KEYS:
            raise OpError(
                f"updateNode: kunci '{key}' tidak boleh diubah pada node '{nid}' "
                f"(boleh: {', '.join(sorted(_UPDATABLE_KEYS))})."
            )
    if isinstance(target.get("data"), dict):
        # bentuk xyflow: label/config masuk ke dalam data
        data = target["data"]
        for key, val in updates.items():
            if key in ("label", "config", "kind"):
                data[key] = copy.deepcopy(val)
            elif key == "data":
                if not isinstance(val, dict):
                    raise OpError(f"updateNode: 'data' node '{nid}' harus objek.")
                data.update(copy.deepcopy(val))
            else:
                target[key] = copy.deepcopy(val)
    else:
        # bentuk spec: label/config/kind di top-level
        for key, val in updates.items():
            if key == "data":
                if not isinstance(val, dict):
                    raise OpError(f"updateNode: 'data' node '{nid}' harus objek.")
                target.update(copy.deepcopy(val))
            else:
                target[key] = copy.deepcopy(val)


def _op_remove_node(nodes: list[dict], edges: list[dict], op: dict) -> None:
    nid = str(op.get("id") or op.get("nodeId") or op.get("nodeName") or "")
    if not nid:
        raise OpError("removeNode: 'id' wajib.")
    before = len(nodes)
    kept = [n for n in nodes if _node_id(n) != nid]
    if len(kept) == before:
        raise OpError(f"removeNode: node '{nid}' tidak ditemukan.")
    nodes[:] = kept
    # Buang edge yang menggantung (mencegah edge ke node hantu).
    edges[:] = [
        e for e in edges
        if _edge_key(
            str(e.get("source") or e.get("from") or ""),
            str(e.get("target") or e.get("to") or ""),
        )[0] != nid
        and str(e.get("target") or e.get("to") or "") != nid
    ]


def _op_add_connection(nodes: list[dict], edges: list[dict], op: dict) -> None:
    src = str(op.get("source") or op.get("from") or "")
    dst = str(op.get("target") or op.get("to") or "")
    if not src or not dst:
        raise OpError("addConnection: 'source' dan 'target' wajib.")
    ids = _index(nodes)
    if src not in ids:
        raise OpError(f"addConnection: source '{src}' tidak ada di daftar nodes.")
    if dst not in ids:
        raise OpError(f"addConnection: target '{dst}' tidak ada di daftar nodes.")
    if src == dst:
        raise OpError(f"addConnection: '{src}' tidak boleh terhubung ke dirinya.")
    if (src, dst) in _edge_set(edges):
        raise OpError(f"addConnection: edge '{src}->{dst}' sudah ada.")
    edge: dict[str, Any] = {"source": src, "target": dst}
    if op.get("id"):
        edge["id"] = str(op["id"])
    if isinstance(op.get("condition"), dict):
        edge["condition"] = copy.deepcopy(op["condition"])
    edges.append(edge)


def _op_remove_connection(edges: list[dict], op: dict) -> None:
    src = str(op.get("source") or op.get("from") or "")
    dst = str(op.get("target") or op.get("to") or "")
    if not src or not dst:
        raise OpError("removeConnection: 'source' dan 'target' wajib.")
    before = len(edges)
    edges[:] = [
        e for e in edges
        if not (
            str(e.get("source") or e.get("from") or "") == src
            and str(e.get("target") or e.get("to") or "") == dst
        )
    ]
    if len(edges) == before:
        raise OpError(f"removeConnection: edge '{src}->{dst}' tidak ditemukan.")


def _diff(a: dict, b: dict) -> dict:
    """Reuse environments.diff_flow bila tersedia (konsistensi diff repo)."""
    try:  # pragma: no cover - bergantung impor
        from environments import diff_flow

        return diff_flow(a, b)
    except Exception:  # noqa: BLE001
        na, nb = _index(a.get("nodes") or []), _index(b.get("nodes") or [])
        ea, eb = _edge_set(a.get("edges") or []), _edge_set(b.get("edges") or [])
        return {
            "nodes_added": sorted(set(nb) - set(na)),
            "nodes_removed": sorted(set(na) - set(nb)),
            "nodes_changed": sorted(
                n for n in set(na) & set(nb) if na[n] != nb[n]
            ),
            "edges_added": sorted(f"{x}->{y}" for x, y in (eb - ea)),
            "edges_removed": sorted(f"{x}->{y}" for x, y in (ea - eb)),
            "changed": bool((set(nb) - set(na)) or (set(na) - set(nb)) or (ea ^ eb)),
        }


def describe() -> dict[str, Any]:
    """Deskripsi mesin operasi (dipakai katalog MCP/agen & dokumentasi)."""
    return {
        "module": "workflow_ops",
        "reference": "n8n-autopilot SKILL.md Phase 3.2 (n8n_update_partial_workflow)",
        "supported_ops": list(SUPPORTED_OPS),
        "limits": {"max_ops": MAX_OPS, "max_nodes": MAX_NODES, "max_edges": MAX_EDGES},
        "atomic": True,
        "schema": {
            "addNode": {"node": "{id, kind|data.kind, label, config, position}"},
            "updateNode": {"id": "node-id", "updates": "{label|config|position|data}"},
            "removeNode": {"id": "node-id"},
            "addConnection": {"source": "node-id", "target": "node-id"},
            "removeConnection": {"source": "node-id", "target": "node-id"},
        },
    }
