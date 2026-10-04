"""textual_tool_handlers.py — eksekusi hasil `textual_tool_parser`.

Bridge antara teks `[TOOL: args]` dan fungsi nyata di `tools.py`.

CATATAN PENTING SOAL NAMA FUNGSI
-------------------------------
Brief menyebut modul `tools/check_credential_tool.py`,
`tools/workflow_generator.py`, `tools/sheets_writer.py`,
`tools/telegram.py`, `tools/slack.py`. SATU-SATUNYA yang benar-benar
ada adalah `credential_forms.check_credential`; sisanya TIDAK ADA
(diverifikasi: tidak ada file itu di repo). Yang dipakai di sini:

    VAULT    -> tools.check_credential_tool
    TELEGRAM -> tools.kirim_telegram_message
    SLACK    -> tools.kirim_slack_message
    SHEETS   -> tools.write_sheets_dynamic_tool
    EMAIL    -> tools.trigger_gmail_imap_tool

JUJUR SOAL `[WORKFLOW: nama]`
-----------------------------
Format itu hanya membawa NAMA, bukan spec workflow.
`generate_workflow_json` membutuhkan spec lengkap ({nodes, edges}).
Tidak ada cara mengubah "inventory_email_to_sheets" menjadi spec yang
benar tanpa model yang menyediakannya. Jadi handler ini TIDAK mengarang
workflow: ia mengembalikan `status="needs_spec"` supaya pemanggil bisa
meminta model menyediakan spec di giliran berikutnya. Mengarang node
di sini akan menghasilkan workflow palsu yang "terlihat berhasil".
"""

from __future__ import annotations

import json
from typing import Any

import tools

#: Provider yang boleh di-[VAULT: ...]. Diselaraskan dengan registry.
_KNOWN_PROVIDERS = frozenset({
    "supabase", "gmail_imap", "telegram", "slack", "google_sheets",
})


def _as_int(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _run(fn, **kwargs) -> dict:
    """Jalankan tool nyata, ubah hasilnya jadi dict seragam.

    `CredentialMissingError` TIDAK ditelan: ia diteruskan supaya
    endpoint bisa merender form inline. Kegagalan lain dikembalikan
    sebagai dict berisi pesan agar tidak mematikan satu putaran.
    """
    try:
        result = fn(**kwargs)
    except tools.CredentialMissingError:
        raise
    except Exception as exc:  # noqa: BLE001 - satu tool gagal tak boleh stop semua
        return {"status": "error",
                "message": f"{type(exc).__name__}: {exc}"[:300]}
    if isinstance(result, dict):
        return result
    return {"status": "ok",
            "result": result if isinstance(result, str) else str(result)}


def _handle_vault(args: dict, user_email: str) -> dict:
    """`[VAULT: provider]` -> cek status kredensial (form inline bila perlu)."""
    provider = str(args.get("provider") or "").strip().lower()
    if provider not in _KNOWN_PROVIDERS:
        return {"status": "unknown_provider", "provider": provider,
                "message": f"Provider '{provider}' tidak dikenal."}
    raw = tools.check_credential_tool(provider=provider, email=user_email)
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {"status": "error", "provider": provider,
                "message": "Gagal membaca status kredensial."}


def _handle_workflow(args: dict, user_email: str) -> dict:
    """`[WORKFLOW: nama]` -> minta spec, jangan mengarang."""
    name = str(args.get("name") or "").strip()
    if not name:
        return {"status": "error", "message": "Nama workflow kosong."}
    return {"status": "needs_spec", "name": name,
            "message": ("Butuh spec workflow lengkap {name, nodes, edges} "
                        "sebelum bisa dibuat.")}


def _handle_email(args: dict, user_email: str) -> dict:
    """`[EMAIL: cek subjek=X max=N]` -> polling Gmail via IMAP.

    `email_address`/`app_password` sengaja dikosongkan: `tools.py`
    mengambilnya sendiri dari vault bila kosong, jadi nilai asli tidak
    pernah melewati argumen dan tidak pernah masuk konteks LLM.
    """
    return _run(tools.trigger_gmail_imap_tool,
                email_address="", app_password="",
                subject_filter=str(args.get("subjek") or ""),
                max_messages=_as_int(args.get("max"), 10),
                unread_only=str(args.get("unread_only") or "true").lower()
                not in ("false", "0", "no"),
                email=user_email)


def _handle_sheets(args: dict, user_email: str) -> dict:
    """`[SHEETS: write spreadsheet=X sheet=Y]` -> tulis baris.

    `values` opsional: tanpa nilainya handler menulis placeholder yang
    bisa diisi model pada giliran berikutnya, bukan mengarang isi sel.
    """
    return _run(tools.write_sheets_dynamic_tool,
                spreadsheet_id=str(args.get("spreadsheet") or ""),
                sheet_name=str(args.get("sheet") or "Sheet1"),
                data={"values": args.get("values") or []},
                email=user_email)


def _handle_telegram(args: dict, user_email: str) -> dict:
    return _run(tools.kirim_telegram_message,
                chat_id=str(args.get("chat_id") or ""),
                pesan=str(args.get("pesan") or ""),
                email=user_email)


def _handle_slack(args: dict, user_email: str) -> dict:
    return _run(tools.kirim_slack_message,
                channel=str(args.get("channel") or ""),
                pesan=str(args.get("pesan") or ""),
                email=user_email)


HANDLERS = {
    "VAULT": _handle_vault,
    "WORKFLOW": _handle_workflow,
    "EMAIL": _handle_email,
    "SHEETS": _handle_sheets,
    "TELEGRAM": _handle_telegram,
    "SLACK": _handle_slack,
}


def execute_textual_tool(call: dict, user_email: str) -> dict:
    """Jalankan satu call hasil `parse_textual_tools`.

    Bentuk call yang tidak dikenal DITOLAK diam (return error), bukan
    dieksekusi lalu meledak.
    """
    tool = str((call or {}).get("tool") or "").upper()
    handler = HANDLERS.get(tool)
    if handler is None:
        return {"status": "error",
                "message": f"Tool tidak dikenal: {tool or '(kosong)'}"}
    args = call.get("args") or {}
    if not isinstance(args, dict):
        return {"status": "error", "message": "Argumen tidak valid."}
    return handler(args, user_email)


__all__ = ["HANDLERS", "execute_textual_tool"]
