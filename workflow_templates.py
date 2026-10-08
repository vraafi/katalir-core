"""Fitur #10 — Workflow Templates.

MASALAH YANG DISELESAIKAN
-------------------------
Sebelum fitur ini setiap user memulai dari kanvas KOSONG. Tidak ada titik awal
yang bisa dipakai langsung, sehingga "time-to-first-working-workflow" tinggi
dan user pemula tidak tahu node apa yang harus disusun.

Fitur ini menambahkan:
  * **Template bawaan** (kode, tanpa DB) — 10 alur siap pakai yang menutup
    pola n8n paling umum (email->sheets, RSS->slack, cron->telegram, webhook->HTTP).
  * **Template kustom per user** (tabel `workflow_templates`, RLS owner-scoped) —
    user bisa menyimpan workflow-nya sendiri sebagai template.
  * **Instantiate** — satu panggilan membuat workflow NYATA milik user dari
    template (lewat `database.create_workflow`, sumber kebenaran yang sama
    dengan endpoint POST /workflows).

DESAIN
------
* Template bawaan = konstanta Python (tidak butuh DB, selalu tersedia walau
  Supabase sedang mati). ID-nya ber-prefix `tpl-` supaya tidak pernah bentrok
  dengan UUID kustom.
* Placeholder isi-user (`{{chat_id}}`, `{{spreadsheet_id}}`, ...) SENGAJA
  dibiarkan utuh di flow_data: user mengisinya di kanvas. Ini konsisten dengan
  perilaku mesin (`_resolve_text` hanya menyentuh placeholder ber-titik).
* Validasi graf dijalankan SEBELUM menulis apa pun, jadi template rusak tidak
  pernah sampai ke DB.
"""
from __future__ import annotations

import copy
import uuid
from typing import Any, Optional

import database as db

#: Prefix ID template bawaan — membedakan dari UUID kustom (yang selalu uuid4).
BUILTIN_PREFIX = "tpl-"

#: Kategori yang dikenali (dipakai endpoint GET /templates?category=...).
CATEGORIES = (
    "notification",
    "marketing",
    "data",
    "ops",
    "ai",
    "integration",
)

#: Batas keras node/edge — SATU sumber kebenaran dengan API & MCP
#: (lihat flow_limits.py). Dulu di sini 100/200 sementara API 500/1000,
#: sehingga workflow 300 node bisa dibuat lewat API tapi gagal jadi template.
from flow_limits import MAX_FLOW_EDGES as MAX_EDGES  # noqa: E402
from flow_limits import MAX_FLOW_NODES as MAX_NODES  # noqa: E402
from flow_limits import RECOMMENDED_TEMPLATE_NODES  # noqa: E402,F401


# ---------------------------------------------------------------------------
# Validasi
# ---------------------------------------------------------------------------
class TemplateError(ValueError):
    """Template/flow_data tidak valid."""


def validate_flow_data(flow: Any) -> dict:
    """Validasi bentuk graf. Mengembalikan flow yang sama bila sah.

    Aturan (sama semangatnya dengan `mcp_server._validate_flow_data`):
      * harus dict ber-`nodes` (list) dan opsional `edges` (list)
      * setiap node wajib punya `id` unik (string non-kosong)
      * setiap edge wajib punya `source` + `target` yang menunjuk node ADA
      * tanpa self-loop
      * batas jumlah node/edge
    """
    if not isinstance(flow, dict):
        raise TemplateError("flow_data harus objek JSON.")
    nodes = flow.get("nodes")
    if not isinstance(nodes, list):
        raise TemplateError("flow_data.nodes harus list.")
    if len(nodes) > MAX_NODES:
        raise TemplateError(f"terlalu banyak node ({len(nodes)} > {MAX_NODES}).")
    ids: set[str] = set()
    for i, n in enumerate(nodes):
        if not isinstance(n, dict):
            raise TemplateError(f"node[{i}] bukan objek.")
        nid = n.get("id")
        if not isinstance(nid, str) or not nid.strip():
            raise TemplateError(f"node[{i}] tanpa id.")
        if nid in ids:
            raise TemplateError(f"node id duplikat: {nid!r}.")
        ids.add(nid)
    edges = flow.get("edges", [])
    if not isinstance(edges, list):
        raise TemplateError("flow_data.edges harus list.")
    if len(edges) > MAX_EDGES:
        raise TemplateError(f"terlalu banyak edge ({len(edges)} > {MAX_EDGES}).")
    for i, e in enumerate(edges):
        if not isinstance(e, dict):
            raise TemplateError(f"edge[{i}] bukan objek.")
        src, tgt = e.get("source"), e.get("target")
        if not isinstance(src, str) or not isinstance(tgt, str):
            raise TemplateError(f"edge[{i}] harus punya source & target string.")
        if src not in ids:
            raise TemplateError(f"edge[{i}] source {src!r} tidak ada di nodes.")
        if tgt not in ids:
            raise TemplateError(f"edge[{i}] target {tgt!r} tidak ada di nodes.")
        if src == tgt:
            raise TemplateError(f"edge[{i}] self-loop {src!r} tidak diizinkan.")
    return flow


def count_nodes(flow: Any) -> int:
    """Jumlah node (tahan bentuk rusak) — memakai helper DB agar konsisten."""
    return db.count_nodes(flow)


# ---------------------------------------------------------------------------
# Pembangun node ringkas
# ---------------------------------------------------------------------------
def _node(nid: str, kind: str, label: str, config: dict | None = None,
          x: float = 0, y: float = 0) -> dict:
    return {
        "id": nid,
        "type": kind if kind == "trigger" else "mcp-tool",
        "position": {"x": x, "y": y},
        "data": {"kind": kind, "label": label, "config": dict(config or {})},
    }


def _edge(src: str, tgt: str) -> dict:
    return {"id": f"e-{src}-{tgt}", "source": src, "target": tgt}


def _flow(nodes: list[dict], edges: list[dict]) -> dict:
    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# Template bawaan (kode)
# ---------------------------------------------------------------------------
def _builtin() -> list[dict]:
    t: list[dict] = []

    t.append({
        "id": BUILTIN_PREFIX + "email-ke-sheets",
        "name": "Email masuk → Google Sheets",
        "description": ("Setiap email baru dirangkum oleh Agent lalu barisnya "
                        "ditambahkan ke Google Sheets."),
        "category": "data",
        "tags": ["gmail", "sheets", "agent"],
        "icon": "mail",
        "flow_data": _flow(
            [
                _node("t1", "trigger", "Email Masuk",
                      {"event_name": "gmail.new_email"}, 0, 0),
                _node("a1", "agent", "Rangkum Email",
                      {"prompt": ("Ringkas email berikut menjadi satu baris: "
                                  "pengirim, subjek, inti. "
                                  "Data: {{trigger.webhook_payload}}")}, 260, 0),
                _node("m1", "mcp", "Tambah ke Sheets",
                      {"provider": "google_sheets",
                       "spreadsheet_id": "{{spreadsheet_id}}",
                       "sheet_name": "Sheet1",
                       "values": "{{a1.instruction}}"}, 520, 0),
            ],
            [_edge("t1", "a1"), _edge("a1", "m1")],
        ),
    })

    t.append({
        "id": BUILTIN_PREFIX + "rss-ke-slack",
        "name": "RSS → Slack",
        "description": "Cek feed RSS lalu kirim ringkasan item terbaru ke Slack.",
        "category": "notification",
        "tags": ["http", "slack", "cron"],
        "icon": "rss",
        "flow_data": _flow(
            [
                _node("t1", "trigger", "Jadwal Harian",
                      {"event_name": "schedule.cron", "cron": "0 8 * * *"}, 0, 0),
                _node("m1", "mcp", "Ambil RSS",
                      {"provider": "http", "method": "GET",
                       "url": "{{rss_url}}"}, 260, 0),
                _node("a1", "agent", "Pilih 5 Teratas",
                      {"prompt": ("Pilih maksimal 5 item paling relevan dari "
                                  "feed dan tulis ringkasannya. "
                                  "Data: {{m1.result}}")}, 520, 0),
                _node("m2", "mcp", "Kirim ke Slack",
                      {"provider": "slack", "channel": "{{channel}}",
                       "pesan": "{{a1.instruction}}"}, 780, 0),
            ],
            [_edge("t1", "m1"), _edge("m1", "a1"), _edge("a1", "m2")],
        ),
    })

    t.append({
        "id": BUILTIN_PREFIX + "telegram-digest-harian",
        "name": "Digest Harian → Telegram",
        "description": "Setiap pagi Agent menyusun digest lalu mengirimkannya ke Telegram.",
        "category": "notification",
        "tags": ["telegram", "cron", "agent"],
        "icon": "send",
        "flow_data": _flow(
            [
                _node("t1", "trigger", "Setiap Pagi 07:00",
                      {"event_name": "schedule.cron", "cron": "0 7 * * *"}, 0, 0),
                _node("a1", "agent", "Susun Digest",
                      {"prompt": ("Susun digest harian singkat: agenda, prioritas, "
                                  "pengingat. Konteks: {{trigger.context}}")}, 260, 0),
                _node("m1", "mcp", "Kirim Telegram",
                      {"provider": "telegram", "chat_id": "{{chat_id}}",
                       "pesan": "{{a1.instruction}}"}, 520, 0),
            ],
            [_edge("t1", "a1"), _edge("a1", "m1")],
        ),
    })

    t.append({
        "id": BUILTIN_PREFIX + "webhook-ke-http",
        "name": "Webhook → API HTTP",
        "description": "Terima webhook lalu teruskan payload ke API HTTP eksternal.",
        "category": "integration",
        "tags": ["webhook", "http"],
        "icon": "webhook",
        "flow_data": _flow(
            [
                _node("t1", "trigger", "Webhook Masuk",
                      {"event_name": "webhook.received"}, 0, 0),
                _node("m1", "mcp", "Teruskan ke API",
                      {"provider": "http", "method": "POST",
                       "url": "{{api_url}}",
                       "body": "{{trigger.webhook_payload}}"}, 260, 0),
            ],
            [_edge("t1", "m1")],
        ),
    })

    t.append({
        "id": BUILTIN_PREFIX + "tanya-jawab-ai",
        "name": "Tanya Jawab AI",
        "description": "Trigger manual → Agent menjawab pertanyaan dengan instruksi tetap.",
        "category": "ai",
        "tags": ["agent"],
        "icon": "sparkles",
        "flow_data": _flow(
            [
                _node("t1", "trigger", "Input Manual",
                      {"event_name": "manual.run"}, 0, 0),
                _node("a1", "agent", "Jawab",
                      {"prompt": ("Jawab pertanyaan user dengan bahasa Indonesia "
                                  "yang ringkas dan akurat. "
                                  "Input: {{trigger.webhook_payload}}")}, 260, 0),
            ],
            [_edge("t1", "a1")],
        ),
    })

    t.append({
        "id": BUILTIN_PREFIX + "laporan-sheets-bulanan",
        "name": "Laporan Bulanan → Google Sheets",
        "description": "Awal bulan, Agent menyusun laporan lalu menuliskannya ke Sheets.",
        "category": "data",
        "tags": ["sheets", "cron", "agent"],
        "icon": "table",
        "flow_data": _flow(
            [
                _node("t1", "trigger", "Tanggal 1 Pukul 09:00",
                      {"event_name": "schedule.cron", "cron": "0 9 1 * *"}, 0, 0),
                _node("a1", "agent", "Susun Laporan",
                      {"prompt": ("Susun laporan bulanan: ringkasan, angka kunci, "
                                  "rekomendasi. Konteks: {{trigger.context}}")}, 260, 0),
                _node("m1", "mcp", "Tulis ke Sheets",
                      {"provider": "google_sheets",
                       "spreadsheet_id": "{{spreadsheet_id}}",
                       "values": "{{a1.instruction}}"}, 520, 0),
            ],
            [_edge("t1", "a1"), _edge("a1", "m1")],
        ),
    })

    t.append({
        "id": BUILTIN_PREFIX + "form-ke-email",
        "name": "Form → Email",
        "description": "Webhook dari form lalu kirim email notifikasi via Gmail.",
        "category": "notification",
        "tags": ["webhook", "gmail"],
        "icon": "mail",
        "flow_data": _flow(
            [
                _node("t1", "trigger", "Form Terkirim",
                      {"event_name": "webhook.received"}, 0, 0),
                _node("a1", "agent", "Susun Email",
                      {"prompt": ("Susun email notifikasi dari data form: "
                                  "subjek jelas + isi ringkas. "
                                  "Data: {{trigger.webhook_payload}}")}, 260, 0),
                _node("m1", "mcp", "Kirim Gmail",
                      {"provider": "gmail", "tujuan": "{{email_tujuan}}",
                       "subjek": "Form baru masuk",
                       "isi": "{{a1.instruction}}"}, 520, 0),
            ],
            [_edge("t1", "a1"), _edge("a1", "m1")],
        ),
    })

    t.append({
        "id": BUILTIN_PREFIX + "agenda-ke-calendar",
        "name": "Pesan → Google Calendar",
        "description": "Terima pesan, Agent mengekstrak acara, lalu tambahkan ke kalender.",
        "category": "ops",
        "tags": ["calendar", "agent"],
        "icon": "calendar",
        "flow_data": _flow(
            [
                _node("t1", "trigger", "Pesan Masuk",
                      {"event_name": "manual.run"}, 0, 0),
                _node("a1", "agent", "Ekstrak Acara",
                      {"prompt": ("Dari pesan berikut, ekstrak nama acara dan waktu "
                                  "dalam format ISO. Pesan: {{trigger.webhook_payload}}")},
                      260, 0),
                _node("m1", "mcp", "Tambah Agenda",
                      {"provider": "google_calendar",
                       "nama_acara": "{{a1.instruction}}",
                       "waktu": "{{waktu}}"}, 520, 0),
            ],
            [_edge("t1", "a1"), _edge("a1", "m1")],
        ),
    })

    t.append({
        "id": BUILTIN_PREFIX + "monitoring-http",
        "name": "Monitoring Endpoint → Telegram",
        "description": "Cek endpoint tiap 15 menit; bila gagal, kirim peringatan ke Telegram.",
        "category": "ops",
        "tags": ["http", "telegram", "cron"],
        "icon": "activity",
        "flow_data": _flow(
            [
                _node("t1", "trigger", "Setiap 15 Menit",
                      {"event_name": "schedule.cron", "cron": "*/15 * * * *"}, 0, 0),
                _node("m1", "mcp", "Cek Endpoint",
                      {"provider": "http", "method": "GET",
                       "url": "{{target_url}}"}, 260, 0),
                _node("m2", "mcp", "Lapor Telegram",
                      {"provider": "telegram", "chat_id": "{{chat_id}}",
                       "pesan": "Status cek: {{m1.result}}"}, 520, 0),
            ],
            [_edge("t1", "m1"), _edge("m1", "m2")],
        ),
    })

    t.append({
        "id": BUILTIN_PREFIX + "whatsapp-broadcast",
        "name": "Broadcast → WhatsApp",
        "description": "Trigger manual → Agent menyusun pesan → kirim WhatsApp.",
        "category": "marketing",
        "tags": ["whatsapp", "agent"],
        "icon": "message-circle",
        "flow_data": _flow(
            [
                _node("t1", "trigger", "Input Manual",
                      {"event_name": "manual.run"}, 0, 0),
                _node("a1", "agent", "Susun Pesan",
                      {"prompt": ("Susun pesan broadcast yang sopan dan singkat "
                                  "(maks 3 kalimat). Konteks: {{trigger.webhook_payload}}")},
                      260, 0),
                _node("m1", "mcp", "Kirim WhatsApp",
                      {"provider": "whatsapp", "nomor_tujuan": "{{nomor_tujuan}}",
                       "pesan": "{{a1.instruction}}"}, 520, 0),
            ],
            [_edge("t1", "a1"), _edge("a1", "m1")],
        ),
    })

    return t


#: Daftar template bawaan (salinan defensif supaya pemanggil tidak memutasi).
BUILTIN_TEMPLATES: list[dict] = _builtin()


# ---------------------------------------------------------------------------
# Penyimpanan kustom (memori untuk test, PostgREST untuk produksi)
# ---------------------------------------------------------------------------
_LTEMPLATES: dict[str, dict] = {}


def _row_to_template(row: dict, source: str = "custom") -> dict:
    t = dict(row)
    t["source"] = source
    t["node_count"] = count_nodes(t.get("flow_data"))
    return t


def _builtin_list() -> list[dict]:
    return [_row_to_template(t, "builtin") for t in BUILTIN_TEMPLATES]


def list_templates(user_id: Optional[str] = None, category: Optional[str] = None,
                   query: Optional[str] = None) -> list[dict]:
    """Template bawaan + kustom milik `user_id`, dengan filter opsional."""
    out = _builtin_list()

    if user_id:
        if not db.is_configured():
            rows = [dict(r) for r in _LTEMPLATES.values()
                    if str(r.get("user_id")) == str(user_id)]
        else:
            try:
                c = db.get_write_client()
                res = (c.table("workflow_templates").select("*")
                       .eq("user_id", user_id)
                       .order("created_at", desc=True).execute())
                rows = res.data or []
            except Exception:  # noqa: BLE001 - tabel belum dimigrasi -> bawaan saja
                rows = []
        out.extend(_row_to_template(r, "custom") for r in rows)

    if category:
        cat = str(category).strip().lower()
        out = [t for t in out if str(t.get("category") or "").lower() == cat]
    if query:
        q = str(query).strip().lower()
        out = [t for t in out
               if q in str(t.get("name") or "").lower()
               or q in str(t.get("description") or "").lower()
               or any(q in str(tag).lower() for tag in (t.get("tags") or []))]
    return out


def get_template(template_id: str, user_id: Optional[str] = None) -> Optional[dict]:
    """Satu template (bawaan atau kustom milik user). None bila tidak ada."""
    tid = str(template_id or "").strip()
    if not tid:
        return None
    if tid.startswith(BUILTIN_PREFIX):
        for t in BUILTIN_TEMPLATES:
            if t["id"] == tid:
                return _row_to_template(t, "builtin")
        return None
    if not db.is_configured():
        row = _LTEMPLATES.get(tid)
        if row and (not user_id or str(row.get("user_id")) == str(user_id)):
            return _row_to_template(row, "custom")
        return None
    # ID kustom adalah uuid. ID berbentuk lain TIDAK mungkin ada, dan
    # meneruskannya ke PostgREST membuat Postgres menolak sintaks uuid ->
    # exception -> HTTP 500 "Internal Server Error" (bug nyata yang terbukti
    # di produksi: GET /templates/nonexistent-id-xyz). Jawaban yang benar
    # untuk "tidak ada" adalah None (-> 404), bukan 500.
    try:
        uuid.UUID(tid)
    except (ValueError, AttributeError, TypeError):
        return None
    c = db.get_write_client()
    q = c.table("workflow_templates").select("*").eq("id", tid)
    if user_id:
        q = q.eq("user_id", user_id)
    res = q.limit(1).execute()
    rows = res.data or []
    return _row_to_template(rows[0], "custom") if rows else None


def create_custom_template(user_id: str, name: str, description: str = "",
                           category: str = "ops", flow_data: Optional[dict] = None,
                           tags: Optional[list] = None) -> dict:
    """Simpan workflow user sebagai template kustom (owner-scoped)."""
    if not user_id:
        raise TemplateError("user_id wajib.")
    clean = str(name or "").strip()
    if not clean:
        raise TemplateError("Nama template tidak boleh kosong.")
    flow = validate_flow_data(copy.deepcopy(flow_data or {"nodes": [], "edges": []}))
    cat = str(category or "ops").strip().lower()
    if cat not in CATEGORIES:
        raise TemplateError(f"kategori tidak dikenal: {cat!r}.")
    payload = {
        "user_id": user_id,
        "name": clean[:120],
        "description": str(description or "")[:1000],
        "category": cat,
        "tags": [str(t)[:40] for t in (tags or [])][:20],
        "flow_data": flow,
    }
    if not db.is_configured():
        tid = str(uuid.uuid4())
        row = {**payload, "id": tid, "created_at": db._now()}
        _LTEMPLATES[tid] = row
        return _row_to_template(row, "custom")
    c = db.get_write_client()
    res = c.table("workflow_templates").insert(payload).execute()
    rows = res.data or []
    if not rows:
        raise TemplateError("Gagal menyimpan template.")
    return _row_to_template(rows[0], "custom")


def delete_custom_template(template_id: str, user_id: str) -> bool:
    """Hapus template kustom milik user. Template bawaan TIDAK bisa dihapus."""
    tid = str(template_id or "").strip()
    if not tid or tid.startswith(BUILTIN_PREFIX):
        return False
    if not db.is_configured():
        row = _LTEMPLATES.get(tid)
        if row and str(row.get("user_id")) == str(user_id):
            del _LTEMPLATES[tid]
            return True
        return False
    # Sama seperti `get_template`: id non-uuid tidak mungkin ada, dan
    # meneruskannya ke PostgREST menghasilkan 500, bukan 404.
    try:
        uuid.UUID(tid)
    except (ValueError, AttributeError, TypeError):
        return False
    c = db.get_write_client()
    res = (c.table("workflow_templates").delete()
           .eq("id", tid).eq("user_id", user_id).execute())
    return bool(res.data)


def instantiate(template_id: str, user_id: str, name: Optional[str] = None,
                description: Optional[str] = None) -> dict:
    """Buat workflow NYATA milik `user_id` dari template.

    Mengembalikan `{"template": {...}, "workflow": {...}}`.
    Raises TemplateError bila template tidak ada / graf tidak valid.
    """
    tpl = get_template(template_id, user_id)
    if not tpl:
        raise TemplateError(f"Template {template_id!r} tidak ditemukan.")
    flow = validate_flow_data(copy.deepcopy(tpl.get("flow_data") or {}))
    wf = db.create_workflow(
        user_id,
        (name or tpl.get("name") or "Workflow baru")[:120],
        (description if description is not None else tpl.get("description") or "")[:1000],
        flow,
    )
    return {"template": {k: tpl.get(k) for k in
                         ("id", "name", "category", "source", "node_count")},
            "workflow": wf}


def describe() -> dict:
    """Metadata untuk endpoint GET /templates/info."""
    return {
        "builtin_count": len(BUILTIN_TEMPLATES),
        "categories": list(CATEGORIES),
        "builtin_ids": [t["id"] for t in BUILTIN_TEMPLATES],
        "max_nodes": MAX_NODES,
        "max_edges": MAX_EDGES,
    }
