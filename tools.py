# tools.py - Tool Registry & Credential Intercept untuk Agentic Loop
# =====================================================================
# Menyediakan:
#   1. Tool simulasi: send_whatsapp_message(pesan, nomor_tujuan)
#   2. Custom exception: CredentialMissingError(provider_name)
#   3. Declaration schema Gemini (untuk Tool Calling)
#   4. Dispatcher eksekusi alat (execute_tool)
#
# Antarmuka dipakai oleh app_frontend.py / run_agent.
# =====================================================================

import os

from google.genai import types

# Load env bila dipanggil standalone (module-level: dotenv via database sudah load)
import database as db


class CredentialMissingError(Exception):
    """Custom exception ketika kredensial provider belum tersimpan.

    Atribut `provider_name` dipakai UI untuk memicu form Contextual Secret
    Injection (st.session_state["missing_credential"]).
    """
    def __init__(self, provider_name: str):
        self.provider_name = provider_name
        super().__init__(f"Credential missing for provider: {provider_name}")


# ---------------------------------------------------------------------------
# TOOL IMPLEMENTASI
# ---------------------------------------------------------------------------
def send_whatsapp_message(pesan: str, nomor_tujuan: str, email: str) -> str:
    """Kirim pesan WhatsApp (simulasi). Validasi kredensial dulu.

    Args:
        pesan: Isi pesan yang dikirim.
        nomor_tujuan: Nomor tujuan (format internasional).
        email: Email user — dipakai untuk ambil token dari user_integrations.

    Returns:
        str: konfirmasi sukses.

    Raises:
        CredentialMissingError: bila user belum menyimpan token whatsapp.
    """
    cred = db.get_integration(email, "whatsapp")
    if not cred or not cred.get("api_token"):
        raise CredentialMissingError("whatsapp")
    # Simulasi pengiriman sukses (BYOK: token sudah ada, aman dipakai)
    return f"Pesan terkirim ke {nomor_tujuan}"


def baca_google_sheets(spreadsheet_id: str, range_data: str, email: str) -> str:
    """Baca data Google Sheets (simulasi). Wajib validasi kredensial dulu."""
    cred = db.get_integration(email, "google_sheets")
    if not cred or not cred.get("api_token"):
        raise CredentialMissingError("google_sheets")
    return f"Data dari spreadsheet {spreadsheet_id} ({range_data}) berhasil dibaca."


def kirim_email_gmail(tujuan: str, subjek: str, isi: str, email: str) -> str:
    """Kirim email via Gmail (simulasi). Wajib validasi kredensial dulu."""
    cred = db.get_integration(email, "gmail")
    if not cred or not cred.get("api_token"):
        raise CredentialMissingError("gmail")
    return f"Email terkirim ke {tujuan} dengan subjek '{subjek}'."


def tambah_agenda_calendar(nama_acara: str, waktu: str, email: str) -> str:
    """Tambah agenda kalender (simulasi). Wajib validasi kredensial dulu."""
    cred = db.get_integration(email, "google_calendar")
    if not cred or not cred.get("api_token"):
        raise CredentialMissingError("google_calendar")
    return f"Agenda '{nama_acara}' ({waktu}) ditambahkan ke kalender."


# ---------------------------------------------------------------------------
# FASE 2.1 — TOOL: generate_workflow_json (Discovery Agent -> canvas)
# Tool ini TIDAK menyentuh jaringan: tugasnya memvalidasi bentuk workflow yang
# diusulkan model, lalu mengembalikan status + pesan perbaikan yang bisa dibaca
# model. Kalau valid, `spec` yang dipulangkan SUDAH siap dirender ke canvas.
# ---------------------------------------------------------------------------
def generate_workflow_json(spec_json: str, email: str = "") -> str:
    """Validasi JSON workflow dari model; kembalikan hasil + spec siap-canvas.

    Args:
        spec_json: JSON string {"name","nodes":[{"id","kind","label","config"}],
            "edges":[{"source","target"}]}. kind = trigger|agent|mcp.
        email: email user (dicatat di meta sebagai pemilik draf; opsional).

    Returns:
        str: JSON string {"ok":bool, ...} — `errors`/`hint` bila ditolak supaya
        model bisa memperbaiki dan memanggil ulang (repair loop).
    """
    import json as _json

    import workflow_spec as _ws

    result = _ws.validate_spec(spec_json or "")
    if result.get("ok"):
        spec = result.get("spec") or {}
        result = {
            "ok": True,
            "spec": spec,
            "warnings": result.get("warnings", []),
            "node_count": len(spec.get("nodes", [])),
            "edge_count": len(spec.get("edges", [])),
        }
    if email:
        result["owner"] = email
    return _json.dumps(result, ensure_ascii=False)



# ---------------------------------------------------------------------------
# SCHEMA DEKLARASI GEMINI (Tool Calling)
# ---------------------------------------------------------------------------
_send_whatsapp_declaration = types.FunctionDeclaration(
    name="send_whatsapp_message",
    description=(
        "Mengirim pesan WhatsApp ke nomor tujuan. Memerlukan kredensial "
        "WhatsApp Cloud API user; bila belum ada, sistem akan meminta credential."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "pesan": types.Schema(
                type=types.Type.STRING,
                description="Isi pesan yang akan dikirim."
            ),
            "nomor_tujuan": types.Schema(
                type=types.Type.STRING,
                description="Nomor WhatsApp tujuan dalam format internasional (misal +628123456789)."
            ),
        },
        required=["pesan", "nomor_tujuan"],
    ),
)

_baca_sheets_declaration = types.FunctionDeclaration(
    name="baca_google_sheets",
    description=(
        "Membaca data dari Google Spreadsheet. Memerlukan kredensial google_sheets "
        "user; bila belum ada, sistem akan meminta credential."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "spreadsheet_id": types.Schema(type=types.Type.STRING,
                description="ID spreadsheet Google Sheets."),
            "range_data": types.Schema(type=types.Type.STRING,
                description="Range sel yang dibaca, misal 'Sheet1!A1:C10'."),
        },
        required=["spreadsheet_id", "range_data"],
    ),
)

_kirim_email_declaration = types.FunctionDeclaration(
    name="kirim_email_gmail",
    description=(
        "Mengirim email melalui Gmail. Memerlukan kredensial gmail user; "
        "bila belum ada, sistem akan meminta credential."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "tujuan": types.Schema(type=types.Type.STRING,
                description="Alamat email tujuan."),
            "subjek": types.Schema(type=types.Type.STRING,
                description="Subjek email."),
            "isi": types.Schema(type=types.Type.STRING,
                description="Isi/pesan email."),
        },
        required=["tujuan", "subjek", "isi"],
    ),
)

_agenda_calendar_declaration = types.FunctionDeclaration(
    name="tambah_agenda_calendar",
    description=(
        "Menambahkan agenda/event ke Google Calendar. Memerlukan kredensial "
        "google_calendar user; bila belum ada, sistem akan meminta credential."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "nama_acara": types.Schema(type=types.Type.STRING,
                description="Nama event/agenda."),
            "waktu": types.Schema(type=types.Type.STRING,
                description="Waktu pelaksanaan agenda (misal '2026-09-06 09:00')."),
        },
        required=["nama_acara", "waktu"],
    ),
)

_generate_workflow_declaration = types.FunctionDeclaration(
    name="generate_workflow_json",
    description=(
        "Membuat/memperbarui draf workflow di canvas Katalir. PANGGIL HANYA "
        "SETELAH kamu punya info yang cukup (jenis trigger, aksi, provider, "
        "jadwal/detail). Kirim seluruh workflow sebagai JSON string. Bentuk: "
        '{"name":"...","nodes":[{"id":"n1","kind":"trigger|agent|mcp",'
        '"label":"...","config":{...}}],"edges":[{"source":"n1","target":"n2"}]}. '
        "Aturan: minimal 1 node kind=trigger; id unik; setiap edge harus "
        "menunjuk id yang ada; node kind=mcp WAJIB punya config.provider "
        "(contoh: telegram, gmail, google_sheets, slack, http). Bila jawaban "
        "ditolak, baca `errors`/`hint` lalu panggil ulang dengan perbaikan."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "spec_json": types.Schema(
                type=types.Type.STRING,
                description="Seluruh workflow sebagai JSON string (bukan object).",
            ),
            "summary": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Ringkasan 1-2 kalimat untuk user tentang apa yang dibangun."
                ),
            ),
        },
        required=["spec_json"],
    ),
)


TOOL_DECLARATIONS = [
    types.Tool(function_declarations=[
        _send_whatsapp_declaration,
        _baca_sheets_declaration,
        _kirim_email_declaration,
        _agenda_calendar_declaration,
        _generate_workflow_declaration,
    ])
]


# ---------------------------------------------------------------------------
# SKEMA JSON UNTUK PROVIDER OPENAI-COMPATIBLE (gateway / BYOK / OpenAI)
# Turunan dari TOOL_DECLARATIONS di atas supaya dua format tidak drift:
# provider OpenAI-compatible (free-llm-gateway, BYOK) tidak paham types.Tool
# Gemini dan butuh JSON Schema ({type: function, function: {name, parameters}}).
# ---------------------------------------------------------------------------
_TYPE_MAP = {
    "STRING": "string",
    "NUMBER": "number",
    "INTEGER": "integer",
    "BOOLEAN": "boolean",
    "ARRAY": "array",
    "OBJECT": "object",
}


def _json_schema(schema) -> dict:
    """Konversi types.Schema (Gemini) -> JSON Schema (OpenAI)."""
    if schema is None:
        return {}
    raw_type = getattr(schema, "type", None)
    type_name = getattr(raw_type, "name", None) or str(raw_type or "")
    out: dict = {}
    mapped = _TYPE_MAP.get(str(type_name).upper())
    if mapped:
        out["type"] = mapped
    desc = getattr(schema, "description", None)
    if desc:
        out["description"] = desc
    props = getattr(schema, "properties", None) or {}
    if props:
        out["properties"] = {k: _json_schema(v) for k, v in props.items()}
    required = getattr(schema, "required", None)
    if required:
        out["required"] = list(required)
    items = getattr(schema, "items", None)
    if items is not None:
        out["items"] = _json_schema(items)
    enum = getattr(schema, "enum", None)
    if enum:
        out["enum"] = list(enum)
    return out


def openai_tool_schemas() -> list[dict]:
    """Skema tools format OpenAI untuk `bind_tools` (gateway/BYOK)."""
    out: list[dict] = []
    for tool in TOOL_DECLARATIONS:
        for decl in (getattr(tool, "function_declarations", None) or []):
            out.append({
                "type": "function",
                "function": {
                    "name": decl.name,
                    "description": decl.description or "",
                    "parameters": _json_schema(decl.parameters),
                },
            })
    return out


TOOL_SCHEMAS_OPENAI = openai_tool_schemas()


# ---------------------------------------------------------------------------
# DISPATCHER EKSEKUSI ALAT
# ---------------------------------------------------------------------------
def execute_tool(name: str, args: dict, email: str) -> str:
    """Eksekusi alat by name dengan argumen + konteks user.

    Semua CredentialMissingError dibiarkan menyebar agar caller (app_frontend)
    dapat menangkapnya untuk memicu UI form kredensial.

    Raises:
        CredentialMissingError: kredensial provider belum tersedia.
        ValueError: alat tidak dikenal.
    """
    if name == "send_whatsapp_message":
        return send_whatsapp_message(
            pesan=args.get("pesan", ""),
            nomor_tujuan=args.get("nomor_tujuan", ""),
            email=email,
        )
    if name == "baca_google_sheets":
        return baca_google_sheets(
            spreadsheet_id=args.get("spreadsheet_id", ""),
            range_data=args.get("range_data", ""),
            email=email,
        )
    if name == "kirim_email_gmail":
        return kirim_email_gmail(
            tujuan=args.get("tujuan", ""),
            subjek=args.get("subjek", ""),
            isi=args.get("isi", ""),
            email=email,
        )
    if name == "tambah_agenda_calendar":
        return tambah_agenda_calendar(
            nama_acara=args.get("nama_acara", ""),
            waktu=args.get("waktu", ""),
            email=email,
        )
    if name == "generate_workflow_json":
        return generate_workflow_json(
            spec_json=args.get("spec_json", ""),
            email=email,
        )
    raise ValueError(f"Unknown tool: {name}")