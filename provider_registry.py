"""provider_registry.py — jembatan "node MCP" -> tool native di `tools.py`.

MASALAH YANG DIPERBAIKI
Node MCP hasil buatan AI menyimpan `config.provider` (telegram/slack/http/…),
tetapi executor lama mengabaikannya dan memilih tool dari `config.tool_name`
dengan default `web_search`. Akibatnya workflow yang jelas-jelas minta "kirim
Telegram" justru menjalankan pencarian web — dan tetap dilaporkan "completed"
karena pencarian kosong hanya mengembalikan `result.status=error` tanpa
menaikkan status langkah.

POLA YANG DIPILIH: **declarative provider registry + argument adapter**
- satu tabel `PROVIDERS` (nama provider -> spec), bukan if/elif bertingkat;
- tiap provider punya *adapter* argumen sendiri karena bentuk argumennya memang
  berbeda (Telegram `chat_id`, Slack `channel`, HTTP `url+method`, Gmail
  `tujuan/subjek/isi`). Perbedaan itu dikumpulkan di tabel sehingga menambah
  provider berikutnya = menambah satu entri, bukan mengubah cabang logika.

KONTRAK HASIL (tidak pernah melempar):
    {"status": "success",          "provider": p, "tool": nama, "result": ...}
    {"status": "needs_credential", "provider": p, "tool": nama, "error": ...}
    {"status": "error",            "provider": p, "tool": nama, "error": ...}
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable

import tools


def _pick(cfg: dict, params: dict, *names: str) -> str:
    """Nilai pertama tidak kosong: config dulu, lalu input node sebelumnya.

    Config menang karena itu pilihan eksplisit untuk node ini; input dipakai
    bila config tidak menyebutkannya (mis. teks pesan dari node Agent).
    """
    for name in names:
        for src in (cfg, params):
            if not isinstance(src, dict):
                continue
            val = src.get(name)
            if val not in (None, "", [], {}):
                return val if isinstance(val, str) else str(val)
    return ""


def _message(cfg: dict, params: dict) -> str:
    """Teks pesan/isi: eksplisit di config, atau keluaran node sebelumnya."""
    return _pick(cfg, params, "pesan", "message", "text", "body", "isi",
                 "instruction", "reply", "query")



# --- adapter argumen per provider -------------------------------------------
def _args_telegram(cfg: dict, params: dict, email: str) -> dict:
    return {"chat_id": _pick(cfg, params, "chat_id", "chatId", "to", "channel_id"),
            "pesan": _message(cfg, params), "email": email}


def _args_slack(cfg: dict, params: dict, email: str) -> dict:
    return {"channel": _pick(cfg, params, "channel", "to", "chat_id") or "#umum",
            "pesan": _message(cfg, params), "email": email}


def _args_http(cfg: dict, params: dict, email: str) -> dict:
    return {"url": _pick(cfg, params, "url", "endpoint", "href"),
            "method": (_pick(cfg, params, "method") or "GET").upper(),
            "body": _pick(cfg, params, "body", "payload", "data"),
            "email": email}


def _args_gmail(cfg: dict, params: dict, email: str) -> dict:
    return {"tujuan": _pick(cfg, params, "tujuan", "to", "email_tujuan"),
            "subjek": _pick(cfg, params, "subjek", "subject"),
            "isi": _message(cfg, params), "email": email}


def _args_sheets(cfg: dict, params: dict, email: str) -> dict:
    return {"spreadsheet_id": _pick(cfg, params, "spreadsheet_id", "sheet_id"),
            "range_data": _pick(cfg, params, "range_data", "range") or "A1:C10",
            "email": email}


def _args_whatsapp(cfg: dict, params: dict, email: str) -> dict:
    return {"pesan": _message(cfg, params),
            "nomor_tujuan": _pick(cfg, params, "nomor_tujuan", "to", "phone"),
            "email": email}


def _args_calendar(cfg: dict, params: dict, email: str) -> dict:
    return {"nama_acara": _pick(cfg, params, "nama_acara", "title", "acara"),
            "waktu": _pick(cfg, params, "waktu", "start", "when"),
            "email": email}


def _gateway_arguments(cfg: dict, params: dict) -> dict:
    """Argumen tool MCP: `config.arguments` (dict ATAU JSON string).

    Bila node tidak menyebut argumen, pakai input node sebelumnya apa adanya —
    itu perilaku wajar MCP ("Agent menulis pesan -> tool echo menggemakannya")
    dan lebih jujur daripada mengarang field tertentu yang skema tool-nya tidak
    kita ketahui.
    """
    raw = cfg.get("arguments")
    if raw is None:
        raw = cfg.get("args")
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        import json
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            # Bukan JSON: kirim sebagai field `message`, konvensi paling umum,
            # tapi jangan sembunyikan bentuk aslinya.
            return {"message": raw}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    upstream = {k: v for k, v in (params or {}).items()
                if not str(k).startswith("_")}
    return upstream


def _args_gateway(cfg: dict, params: dict, email: str) -> dict:
    return {"tool": _pick(cfg, params, "tool", "tool_name", "mcp_tool"),
            "arguments": _gateway_arguments(cfg, params)}


def _gateway_call_tool(tool: str, arguments: dict | None = None) -> dict:
    """Panggil satu tool di agentgateway (MCP streamable HTTP).

    Sengaja TIDAK menelan kegagalan: `run()` sudah memetakan exception menjadi
    `status=error` yang eksplisit, dan itu yang membuat node MCP gagal-terbaca
    alih-alih dilaporkan "completed" palsu.
    """
    from mcp_gateway.client import GatewayClient
    if not str(tool or "").strip():
        raise ValueError("nama tool MCP kosong")
    result = GatewayClient().call_tool_sync(str(tool), arguments or {})
    return {"tool": str(tool), "result": result}



@dataclass(frozen=True)
class ProviderSpec:
    name: str
    fn: Callable[..., Any]
    credential: str            # nama kredensial di Brankas ("" = tidak perlu)
    build_args: Callable[[dict, dict, str], dict]
    summary: str
    required: tuple[str, ...] = ()   # field config WAJIB (lihat REQUIRED_CONFIG)
    # Label tool untuk laporan langkah. Provider biasa memakai nama fungsi, tapi
    # jembatan MCP harus melaporkan NAMA TOOL MCP ("everything_echo"), bukan
    # nama fungsi Python-nya ("_gateway_call_tool") - itu yang dibaca user di
    # laporan eksekusi.
    tool_label: Callable[[Any], str] | None = None


# Field TUJUAN/struktur yang HARUS ada di config node agar bisa dijalankan.
# Tanpa ini, model cenderung hanya menulis {"provider": "telegram"} dan
# kegagalannya baru muncul sebagai HTTP 400 dari provider.
REQUIRED_CONFIG: dict[str, tuple[str, ...]] = {
    "telegram": ("chat_id",),
    "slack": ("channel",),
    "http": ("url",),
    "gmail": ("tujuan", "subjek"),
    "google_sheets": ("spreadsheet_id",),
    "whatsapp": ("nomor_tujuan",),
    "google_calendar": ("nama_acara", "waktu"),
    # Tool MCP gateway: nama tool WAJIB; argumen opsional (boleh dari node hulu).
    "gateway": ("tool",),
}

# Field KONTEN: boleh datang dari config node ATAU dari node sebelumnya
# (keluaran Agent). Menuntutnya di config akan menolak workflow sah seperti
# "Agent menulis ringkasan -> Telegram mengirimkannya".
CONTENT_CONFIG: dict[str, tuple[str, ...]] = {
    "telegram": ("pesan",),
    "slack": ("pesan",),
    "gmail": ("isi",),
    "whatsapp": ("pesan",),
}

# Sinonim field yang tetap diterima saat MEMERIKSA kelengkapan config, supaya
# model tidak dihukum hanya karena memakai nama lain yang sama jelasnya.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "chat_id": ("chat_id", "chatId", "to", "channel_id"),
    "pesan": ("pesan", "message", "text", "body", "isi",
              "instruction", "reply", "query"),
    "channel": ("channel", "to"),
    "url": ("url", "endpoint", "href"),
    "tujuan": ("tujuan", "to", "email_tujuan"),
    "subjek": ("subjek", "subject"),
    "isi": ("isi", "pesan", "message", "body", "text",
            "instruction", "reply", "query"),
    "spreadsheet_id": ("spreadsheet_id", "sheet_id"),
    "nomor_tujuan": ("nomor_tujuan", "to", "phone"),
    "nama_acara": ("nama_acara", "title", "acara"),
    "waktu": ("waktu", "start", "when"),
    "tool": ("tool", "tool_name", "mcp_tool"),
}


PROVIDERS: dict[str, ProviderSpec] = {
    "telegram": ProviderSpec("telegram", tools.kirim_telegram_message, "telegram",
                             _args_telegram, "Kirim pesan Telegram"),
    "slack": ProviderSpec("slack", tools.kirim_slack_message, "slack",
                          _args_slack, "Kirim pesan Slack"),
    "http": ProviderSpec("http", tools.http_request, "",
                         _args_http, "Panggil API HTTP publik"),
    "gmail": ProviderSpec("gmail", tools.kirim_email_gmail, "gmail",
                          _args_gmail, "Kirim email via Gmail"),
    "google_sheets": ProviderSpec("google_sheets", tools.baca_google_sheets,
                                  "google_sheets", _args_sheets,
                                  "Baca Google Sheets"),
    "whatsapp": ProviderSpec("whatsapp", tools.send_whatsapp_message, "whatsapp",
                             _args_whatsapp, "Kirim WhatsApp"),
    "google_calendar": ProviderSpec("google_calendar", tools.tambah_agenda_calendar,
                                    "google_calendar", _args_calendar,
                                    "Tambah agenda kalender"),
    # Bridge ke katalog MCP agentgateway (44 tool live: everything/fetch/memory/
    # filesystem/time/openconnector). Kredensial BUKAN milik vault user —
    # autentikasi gateway dari env server (AGENTGATEWAY_TOKEN), jadi credential
    # sengaja kosong supaya tidak memunculkan alur isi-kredensial yang salah.
    "gateway": ProviderSpec("gateway", _gateway_call_tool, "",
                            _args_gateway,
                            "Panggil tool MCP apa pun dari katalog agentgateway",
                            tool_label=lambda out: str(
                                (out or {}).get("tool") or "").strip()),
}

# Sinonim: model kadang menulis "sheet"/"gcal"/"wa". Dipetakan, bukan ditolak.
ALIASES = {
    "sheet": "google_sheets", "sheets": "google_sheets",
    "google_sheet": "google_sheets", "spreadsheet": "google_sheets",
    "gcal": "google_calendar", "calendar": "google_calendar",
    "wa": "whatsapp", "whatsapp_cloud": "whatsapp",
    "mail": "gmail", "email": "gmail",
    "telegram_bot": "telegram", "tg": "telegram",
    # Nama lain untuk jembatan MCP. "mcp" SENGAJA tidak dipetakan: kunci itu
    # plausibel berisi NAMA TOOL, dan memetakannya ke provider akan mengubah
    # error "provider tak dikenal" yang sudah dikunci test.
    "mcp_gateway": "gateway", "agentgateway": "gateway",
    "mcp_tool": "gateway",
}


def list_providers() -> list[dict]:
    """Daftar provider untuk dokumentasi/tool discovery."""
    return [{"name": s.name, "summary": s.summary, "credential": s.credential}
            for s in PROVIDERS.values()]


def resolve(cfg: dict | None, params: dict | None = None) -> str | None:
    """Provider dari config node (dengan alias), atau None bila tidak disebut.

    SENGAJA tidak menebak dari `tool_name`: bila node tidak menyebut provider,
    pemanggil memakai jalur lama (tool bawaan mesin seperti web_search).
    """
    cfg = cfg or {}
    params = params or {}
    raw = _pick(cfg, params, "provider", "mcp", "integration", "service").strip().lower()
    if not raw:
        return None
    return ALIASES.get(raw, raw)   # nama tak dikenal tetap dikembalikan -> run() menolak



def missing_required(provider: str, cfg: dict | None,
                     params: dict | None = None,
                     has_upstream: bool = True) -> list[str]:
    """Field yang belum lengkap: tujuan WAJIB di config, konten boleh dari hulu.

    - Field TUJUAN (chat_id/url/channel) hanya diperiksa di `config`: itu
      keputusan user, bukan efek samping alur.
    - Field KONTEN (pesan/isi) boleh berasal dari (a) config, (b) input node
      sebelumnya saat eksekusi (`params`), atau (c) node hulu yang akan mengisi
      saat runtime (`has_upstream`). Validasi draf memakai (c) karena pada saat
      validasi belum ada data; ini mencegah penolakan workflow sah seperti
      "Agent menulis ringkasan -> Telegram mengirimkannya".
    - Node MCP tanpa pendahulu memang harus menyebut kontennya sendiri, kalau
      tidak akan terkirim pesan kosong.
    """
    cfg = cfg or {}
    params = params or {}
    missing: list[str] = []
    for key in REQUIRED_CONFIG.get(provider, ()):
        names = FIELD_ALIASES.get(key, (key,))
        if not any(cfg.get(n) not in (None, "", [], {}) for n in names):
            missing.append(key)
    for key in CONTENT_CONFIG.get(provider, ()):
        names = FIELD_ALIASES.get(key, (key,))
        in_cfg = any(cfg.get(n) not in (None, "", [], {}) for n in names)
        in_params = any(params.get(n) not in (None, "", [], {}) for n in names)
        if not (in_cfg or in_params or has_upstream):
            missing.append(key)
    return missing


def build_args(provider: str, cfg: dict | None, params: dict | None,
               email: str = "") -> dict:
    spec = PROVIDERS.get(provider)
    return spec.build_args(cfg or {}, params or {}, email) if spec else {}


def _tool_label(spec: "ProviderSpec", out: Any) -> str:
    """Nama tool untuk laporan: label khusus provider bila ada, else nama fungsi."""
    if spec.tool_label is not None:
        try:
            label = (spec.tool_label(out) or "").strip()
            if label:
                return label
        except Exception:  # noqa: BLE001 - label tidak boleh menjatuhkan eksekusi
            pass
    return spec.fn.__name__


def run(provider: str, cfg: dict | None, params: dict | None,
        email: str = "") -> dict:
    """Jalankan provider. SELALU mengembalikan dict (tidak pernah melempar).

    CredentialMissingError dipetakan ke `needs_credential` supaya pemanggil
    (chat maupun mesin eksekusi) bisa memunculkan alur isi kredensial. Provider
    TAK DIKENAL = error eksplisit — jangan pernah diam-diam jatuh ke tool lain.
    """
    spec = PROVIDERS.get(provider)
    if not spec:
        known = ", ".join(sorted(PROVIDERS))
        return {"status": "error", "provider": provider, "tool": None,
                "error": f"provider '{provider}' belum terdaftar (tersedia: {known})"}
    args = build_args(provider, cfg, params, email)
    # Kelengkapan config diperiksa LEBIH DULU: kegagalan "chat_id kosong" harus
    # terbaca sebagai masalah konfigurasi, bukan HTTP 400 dari provider.
    missing = missing_required(provider, cfg, params)
    if missing:
        return {"status": "needs_configuration", "provider": provider,
                "tool": spec.fn.__name__, "missing": missing,
                "error": (f"config node '{provider}' belum lengkap: "
                          f"{', '.join(missing)}")}
    try:
        out = spec.fn(**args)
    except tools.CredentialMissingError as exc:
        return {"status": "needs_credential", "provider": provider,
                "tool": spec.fn.__name__, "credential": exc.provider_name,
                "error": f"Kredensial '{exc.provider_name}' belum ada"}
    except Exception as exc:  # noqa: BLE001 - target mati tidak boleh menjatuhkan DAG
        return {"status": "error", "provider": provider,
                "tool": spec.fn.__name__,
                "error": f"[{type(exc).__name__}] {exc}"}
    return {"status": "success", "provider": provider,
            "tool": _tool_label(spec, out), "result": out}


async def run_async(provider: str, cfg: dict | None, params: dict | None,
                    email: str = "") -> dict:
    """Versi async untuk mesin eksekusi: tool sinkron dijalankan di thread.

    Tanpa `to_thread`, satu panggilan HTTP (Telegram/Slack) memblokir event loop
    server selama detik-an sehingga request lain ikut menunggu.
    """
    return await asyncio.to_thread(run, provider, cfg, params, email)
