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

import json as _json
import os

from google.genai import types

# Gmail IMAP trigger (TIDAK OAuth - scope gmail.readonly itu restricted/CASA).
# Import ringan di level modul: hanya konstanta + helper normalisasi, tidak
# ada koneksi jaringan sampai tool benar-benar dipanggil.
from gmail_imap import VAULT_PROVIDER, normalize_app_password

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


def buat_google_spreadsheet(title: str, sheet_name: str = "Sheet1",
                           sheet_names=None, email: str = "") -> str:
    """Membuat Google Spreadsheet BARU lewat REST API (bukan simulasi).

    BUG FIX 2026-10-03. Sebelumnya satu-satunya tool Sheets adalah
    `baca_google_sheets`, yang WAJIB punya `spreadsheet_id`. Jadi model tidak
    pernah bisa membuat spreadsheet dan satu-satunya jalan adalah meminta user
    membuatnya manual lalu menyalin ID.

    Memakai token OAuth yang SUDAH ada di vault (`oauth_google.access_token`,
    scope `auth/spreadsheets`) dengan refresh otomatis. Bila user belum Connect,
    naikkan `CredentialMissingError` supaya UI menampilkan tombol Connect
    (dipetakan di `api_server.chat` ke `/oauth/google/authorize`) - BUKAN
    meminta user menempel token manual.

    Returns:
        Ringkasan berisi judul, daftar tab, `spreadsheet_id`, dan URL.

    Raises:
        CredentialMissingError: user belum Connect / token ditolak Google.
        RuntimeError: Google Sheets API mengembalikan error lain.
    """
    import httpx
    import oauth_google

    try:
        token = oauth_google.access_token(email)
    except RuntimeError as exc:
        # Belum Connect (atau refresh token dicabut) ->_ui offering Connect.
        raise CredentialMissingError("google_sheets") from exc

    tabs = [sheet_name or "Sheet1"]
    for extra in (sheet_names or []):
        name = str(extra).strip()
        if name and name not in tabs:
            tabs.append(name)

    payload = {
        "properties": {"title": str(title)},
        "sheets": [{"properties": {"title": t}} for t in tabs],
    }
    try:
        resp = httpx.post(
            "https://sheets.googleapis.com/v4/spreadsheets",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30.0,
        )
    except httpx.HTTPError as exc:  # noqa: BLE001
        raise RuntimeError(f"Gagal menghubungi Google Sheets API: {exc}") from exc

    if resp.status_code in (401, 403):
        # Token ditolak/kedaluwarsa total -> suruh Connect ulang.
        raise CredentialMissingError("google_sheets")
    if resp.status_code != 200:
        raise RuntimeError(
            f"Google Sheets API {resp.status_code}: {resp.text[:200]}"
        )

    data = resp.json() or {}
    sid = data.get("spreadsheetId") or ""
    url = data.get("spreadsheetUrl") or ""
    return (
        f"Spreadsheet '{title}' berhasil dibuat. "
        f"Tab: {', '.join(tabs)}. "
        f"spreadsheet_id={sid} URL={url}"
    )


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
# FASE 2.4 — MCP REGISTRY (native, tanpa dependency baru)
# ---------------------------------------------------------------------------
# Penghitung proses untuk membuktikan berapa kali API Telegram BENAR-BENAR
# dipanggil (bukti "1 perintah = 1 pesan"; lihat `kirim_telegram_message`).
_TELEGRAM_SEND_SEQ = 0


def _text_fp(text: object) -> str:
    """Sidik jari teks (8 hex) — untuk membandingkan pesan TANPA mencetak isinya."""
    import hashlib

    return hashlib.sha1(str(text).encode("utf-8")).hexdigest()[:8]


def _trace(line: str) -> None:
    """Catat satu baris jejak ke berkas (bukan stdout — lihat pemanggilnya).

    Lokasi: `TELEGRAM_SEND_LOG` bila di-set, kalau tidak
    `<temp>/telegram_sends.log`. Kegagalan menulis jejak TIDAK boleh
    menggagalkan pengiriman pesan.
    """
    import os
    import tempfile
    import time

    path = os.getenv("TELEGRAM_SEND_LOG") or os.path.join(
        tempfile.gettempdir(), "telegram_sends.log")
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {line}\n")
    except Exception:  # noqa: BLE001
        pass


# KENAPA NATIVE (bukan Composio/Pipedream): keputusan FASE 1 — nol biaya, nol
# vendor lock-in, dan backend ini sudah punya registry tool + Brankas. Yang
# ditambahkan di sini hanya provider yang bisa dipanggil LANGSUNG dengan token
# user (Telegram Bot API, Slack webhook/bot, HTTP generik).
#
# ATURAN KEAMANAN YANG DIPAKSA DI MODUL INI:
#   1. token dibaca dari Brankas/DB per user (bukan env global);
#   2. token TIDAK pernah ikut ke hasil tool / pesan model / log;
#   3. HTTP generik tidak boleh menembak alamat internal (SSRF guard).
_BLOCKED_HOST_PREFIXES = ("127.", "0.", "10.", "169.254.", "192.168.",
                          "100.64.", "198.18.")


def _host_blocked(host: str) -> bool:
    """True bila host menunjuk jaringan internal/meta (SSRF)."""
    import ipaddress

    h = (host or "").strip().strip("[]").lower()
    if not h or h in ("localhost", "metadata.google.internal", "169.254.169.254"):
        return True
    if h.startswith(_BLOCKED_HOST_PREFIXES):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        # Nama domain: resolusi dulu, lalu periksa SETIAP alamat (DNS rebinding).
        import socket

        try:
            infos = socket.getaddrinfo(h, None)
        except Exception:
            return True                      # tak bisa dipastikan -> tolak
        for info in infos:
            addr = info[4][0]
            try:
                ip = ipaddress.ip_address(addr)
            except ValueError:
                return True
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return True
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def _get_telegram_token(owner_email: str) -> str:
    """Token Telegram: Brankas user DULU, lalu fallback `.env`.

    KENAPA ADA FALLBACK: di dev/self-hosted hanya ada SATU bot (milik pemilik),
    sehingga memaksa setiap user menempel token manual menghalangi pengujian
    end-to-end. Urutannya sengaja "vault dulu" supaya token user selalu menang
    atas token owner.

    BATASAN PENTING (jangan lupa saat produksi multi-tenant): pada SaaS publik
    fallback ini membuat SEMUA user memakai bot owner — perilaku yang salah untuk
    tenant nyata. Matikan dengan `TELEGRAM_ENV_FALLBACK=0` di produksi.
    """
    import os as _os

    cred = db.get_integration(owner_email, "telegram")
    vault_token = (cred or {}).get("api_token") or ""
    if vault_token:
        return vault_token
    fallback_on = (_os.environ.get("TELEGRAM_ENV_FALLBACK") or "1").strip() != "0"
    env_token = (_os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip() if fallback_on else ""
    if env_token:
        _trace("telegram token dari .env (fallback owner) — JANGAN dipakai di SaaS multi-tenant")
        return env_token
    raise CredentialMissingError("telegram")


def kirim_telegram_message(chat_id: str, pesan: str, email: str) -> str:
    """Kirim pesan Telegram (BOT API nyata). Token dari Brankas user, fallback `.env`.

    Raises:
        CredentialMissingError: tidak ada token di Brankas DAN fallback `.env`
            dimatikan/kosong.
    """
    cred = db.get_integration(email, "telegram")
    token = (cred or {}).get("api_token") or ""
    if not token:
        token = _get_telegram_token(email)
    # Token Telegram WAJIB di path (desain API-nya) — karena itu URL ini tidak
    # pernah dicetak/di-log, dan pesan error di bawah tidak memuat URL.
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    # JEJAK WAJIB (FILE, bukan stdout): stdout ter-buffer saat proses dipipe
    # (uvicorn di dalam test harness), sehingga print bisa hilang saat proses
    # dimatikan. Bukti "1 perintah = 1 pesan" harus bertahan, jadi setiap
    # panggilan API nyata dicatat ke berkas (mis. %TEMP%\telegram_sends.log).
    global _TELEGRAM_SEND_SEQ
    _TELEGRAM_SEND_SEQ += 1
    _seq = _TELEGRAM_SEND_SEQ
    _trace(f"SEND seq={_seq} chat={str(chat_id)[:6]}*** "
           f"text_len={len(str(pesan))} text_sha8={_text_fp(pesan)}")
    print(f"[telegram] SEND seq={_seq} chat={str(chat_id)[:6]}*** "
          f"text_len={len(str(pesan))}")
    try:
        import httpx
        r = httpx.post(url, json={"chat_id": str(chat_id), "text": str(pesan)},
                       timeout=15.0)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Telegram tidak terjangkau ({type(exc).__name__}).")
    if r.status_code >= 400:
        _trace(f"seq={_seq} FAIL http={r.status_code}")
        raise RuntimeError(f"Telegram menolak permintaan (HTTP {r.status_code}).")
    try:
        body = r.json()
    except Exception:  # noqa: BLE001
        body = {}
    mid = (body.get("result") or {}).get("message_id")
    _trace(f"seq={_seq} OK message_id={mid}")
    return f"Pesan Telegram terkirim ke chat {chat_id} (id {mid})."


def kirim_slack_message(channel: str, pesan: str, email: str) -> str:
    """Kirim pesan Slack: webhook URL ATAU bot token (xoxb-)."""
    cred = db.get_integration(email, "slack")
    token = (cred or {}).get("api_token") or ""
    if not cred or not token:
        raise CredentialMissingError("slack")
    import httpx

    if token.startswith("http"):
        if not token.startswith("https://hooks.slack.com/"):
            raise RuntimeError("Webhook Slack harus dari hooks.slack.com.")
        r = httpx.post(token, json={"text": str(pesan)}, timeout=15.0)
    else:
        r = httpx.post("https://slack.com/api/chat.postMessage",
                       headers={"Authorization": f"Bearer {token}"},
                       json={"channel": str(channel), "text": str(pesan)},
                       timeout=15.0)
    if r.status_code >= 400:
        raise RuntimeError(f"Slack menolak permintaan (HTTP {r.status_code}).")
    return f"Pesan Slack terkirim ke {channel}."


def http_request(url: str, method: str = "GET", body: str = "",
                 email: str = "") -> str:
    """HTTP generik ke internet publik (SSRF guard aktif).

    Dipakai untuk API apa pun yang belum punya tool khusus. Token provider
    TIDAK dipakai di sini: kredensial hanya untuk provider bernama.
    """
    from urllib.parse import urlparse

    parsed = urlparse(str(url or ""))
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL harus http/https.")
    verb = (method or "GET").upper()
    if verb not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        raise ValueError(f"Method tidak didukung: {verb}")
    # SSRF guard SETELAH validasi bentuk: pemeriksaan murah dulu, dan pesan
    # "host ditolak" tidak menyamarkan kesalahan method.
    if _host_blocked(parsed.hostname or ""):
        raise ValueError("Host internal/loopback ditolak (SSRF guard).")
    import httpx

    try:
        r = httpx.request(verb, url, content=body or None, timeout=20.0,
                          headers={"Content-Type": "application/json"})
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Permintaan HTTP gagal ({type(exc).__name__}).")
    snippet = (r.text or "")[:400]
    return f"HTTP {r.status_code} dari {parsed.hostname}: {snippet}"


# ---------------------------------------------------------------------------
# FASE 2.1 — TOOL: generate_workflow_json (Discovery Agent -> canvas)
# Tool ini TIDAK menyentuh jaringan: tugasnya memvalidasi bentuk workflow yang
# diusulkan model, lalu mengembalikan status + pesan perbaikan yang bisa dibaca
# model. Kalau valid, `spec` yang dipulangkan SUDAH siap dirender ke canvas.
# ---------------------------------------------------------------------------
def gmail_imap_credential(email: str) -> dict:
    """Baca kredensial Gmail IMAP dari vault (multi-field, terenkripsi Fernet).

    BUG/FITUR 2026-10-03: sekarang satu sumber kebenaran - registry
    `providers.credential_schemas` + helper `credential_forms`. Nilai di
    vault disimpan sebagai JSON terenkripsi dengan key yang PERSIS sama dengan
    nama field di registry (`email`, `app_password`), jadi menambah/mengubah
    field di registry otomatis terbaca di sini.
    """
    from credential_forms import load_vault_credential

    data = load_vault_credential(email, VAULT_PROVIDER)
    if not data or not data.get("app_password"):
        raise CredentialMissingError(VAULT_PROVIDER)
    return data


def save_gmail_imap_credential(email: str, email_address: str,
                               app_password: str) -> bool:
    """Simpan kredensial Gmail IMAP terenkripsi (registry-driven).

    Dipertahankan sebagai pembungkus agar pemanggil lama tidak pecah; logika
    validasi + enkripsi sekarang milik `credential_forms.validate_and_save`.
    """
    from credential_forms import validate_and_save

    validate_and_save(VAULT_PROVIDER, {
        "email": str(email_address or "").strip(),
        "app_password": normalize_app_password(app_password),
    }, email)
    return True


def trigger_gmail_imap_tool(email_address: str, app_password: str = "",
                            subject_filter: str = "", max_messages: int = 10,
                            unread_only: bool = True, email: str = "") -> str:
    """ polls Gmail via IMAP. `app_password` boleh kosong -> diambil dari vault.

    Mengembalikan JSON string berisi daftar email. App password TIDAK PERNAH
    ikut di balasan (keamanan).
    """
    from gmail_imap import GmailImapError, trigger_gmail_imap as _poll

    addr = str(email_address or "").strip()
    pw = str(app_password or "").strip()
    if not pw:
        # Ambil dari vault bila user sudah menyimpannya lewat UI.
        cred = gmail_imap_credential(email)
        addr = addr or cred.get("email_address", "")
        pw = cred.get("app_password", "")
    try:
        res = _poll(
            email_address=addr,
            app_password=pw,
            subject_filter=subject_filter,
            max_messages=max_messages,
            unread_only=bool(unread_only),
        )
    except GmailImapError as exc:
        return _json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
    return _json.dumps(res, ensure_ascii=False, default=str)


def write_sheets_dynamic_tool(spreadsheet_id: str, sheet_name: str,
                              data: dict, email: str) -> str:
    """Bungkus `write_sheets_dynamic` jadi string JSON untuk dispatcher."""
    from sheets_dynamic import write_sheets_dynamic as _write

    res = _write(
        spreadsheet_id=spreadsheet_id,
        sheet_name=sheet_name or "Sheet1",
        data=data,
        email=email,
    )
    return _json.dumps(res, ensure_ascii=False, default=str)


def web_search(query: str, max_results: int = 5) -> str:
    """Pencarian web nyata (DuckDuckGo) untuk dipakai agen chat.

    Mengembalikan JSON string berisi daftar hasil (judul, url, cuplikan).
    Kegagalan DIWAKANAI sebagai JSON `{"results": [], "error": ...}` -
    bukan exception - supaya model bisa menjelaskan ke user daripada
    menjatuhkan seluruh permintaan sebagai 500.

    Batas rigor: `max_results` dibatasi 8 supaya tidak dipakai membanjiri
    konteks, dan query kosong ditolak di awal (DDGS tanpa query bisa
    menggantung).
    """
    q = str(query or "").strip()
    if not q:
        return _json.dumps({"results": [], "error": "query kosong"})
    try:
        n = int(max_results or 5)
    except Exception:
        n = 5
    n = max(1, min(n, 8))
    try:
        from ddgs import DDGS  # lazy import: tidak aktif bila tidak dipakai
    except Exception as exc:  # noqa: BLE001
        return _json.dumps({
            "results": [],
            "error": f"pencarian web tidak tersedia: {type(exc).__name__}: {exc}",
        })
    try:
        hits = list(DDGS().text(q, max_results=n))
    except Exception as exc:  # noqa: BLE001 - jaringan/jitter
        return _json.dumps({
            "results": [],
            "error": f"pencarian gagal: {type(exc).__name__}: {exc}",
        })
    results = [
        {
            "title": str(h.get("title") or "")[:200],
            "url": str(h.get("href") or h.get("url") or ""),
            "snippet": str(h.get("body") or "")[:300],
        }
        for h in hits
        if (h.get("href") or h.get("url"))
    ]
    return _json.dumps({"results": results, "query": q}, ensure_ascii=False)


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
    from workflow_normalizer import normalize_workflow_payload as _norm

    # BUG FIX 2026-10-04: bentuk payload dari model sering berbeda (lihat
    # workflow_normalizer.py). Normalisasi dulu supaya tidak ditolak.
    result = _ws.validate_spec(_json.dumps(_norm(spec_json)) if spec_json else "")
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

_buat_spreadsheet_declaration = types.FunctionDeclaration(
    name="buat_google_spreadsheet",
    description=(
        "Membuat Google Spreadsheet BARU (judul + tab). Gunakan ini saat pengguna "
        "meminta dibuatkan spreadsheet/lembar kerja/tab baru. Memerlukan koneksi "
        "Google Sheets milik user. JANGAN minta pengguna membuat spreadsheet "
        "secara manual."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "title": types.Schema(type=types.Type.STRING,
                description="Judul spreadsheet baru, misal 'Laporan Verdi'."),
            "sheet_name": types.Schema(type=types.Type.STRING,
                description="Nama tab pertama. Default 'Sheet1'."),
            "sheet_names": types.Schema(type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
                description="Nama tab tambahan (opsional), misal ['inventory']."),
        },
        required=["title"],
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

_telegram_declaration = types.FunctionDeclaration(
    name="kirim_telegram_message",
    description=(
        "Mengirim pesan Telegram ke sebuah chat. Memerlukan token bot Telegram "
        "user (provider 'telegram'); bila belum ada, sistem meminta credential."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "chat_id": types.Schema(type=types.Type.STRING,
                description="ID chat/grup Telegram tujuan (mis. -1001234567890)."),
            "pesan": types.Schema(type=types.Type.STRING,
                description="Isi pesan yang dikirim."),
        },
        required=["chat_id", "pesan"],
    ),
)

_slack_declaration = types.FunctionDeclaration(
    name="kirim_slack_message",
    description=(
        "Mengirim pesan ke Slack (webhook URL atau bot token provider 'slack')."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "channel": types.Schema(type=types.Type.STRING,
                description="Nama/ID channel Slack (mis. #umum)."),
            "pesan": types.Schema(type=types.Type.STRING,
                description="Isi pesan yang dikirim."),
        },
        required=["channel", "pesan"],
    ),
)

_http_declaration = types.FunctionDeclaration(
    name="http_request",
    description=(
        "Memanggil API HTTP publik (GET/POST/PUT/PATCH/DELETE). Untuk integrasi "
        "yang belum punya tool khusus. Alamat internal/loopback DITOLAK."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "url": types.Schema(type=types.Type.STRING,
                description="URL lengkap http/https."),
            "method": types.Schema(type=types.Type.STRING,
                description="GET (default), POST, PUT, PATCH, atau DELETE."),
            "body": types.Schema(type=types.Type.STRING,
                description="Body JSON sebagai string (opsional)."),
        },
        required=["url"],
    ),
)


# BUG FIX 2026-10-04: sebelumnya tidak ada tool untuk MENANYAKAN status
# kredensial. Tanpa itu, model tidak pernah tahu mana yang sudah tersimpan,
# dan hanya bisa menebak - sehingga vault form tidak pernah muncul.
# Fungsi `credential_forms.check_credential` sudah lengkap; yang kurang
# hanyalah deklarasi supaya bisa dipanggil model.
_check_credential_declaration = types.FunctionDeclaration(
    name="check_credential",
    description=(
        "Cek apakah kredensial pengguna untuk sebuah provider sudah "
        "tersimpan di vault. PANGGIL INI SEBELUM generate_workflow_json "
        "untuk setiap provider yang akan dipakai workflow "
        "(gmail_imap, google_sheets, telegram, slack, supabase). "
        "Status yang dikembalikan: 'ok' (sudah ada, lanjutkan), "
        "'requires_credential' (sistem akan memunculkan form - BERHENTI, "
        "jangan lanjutkan dan jangan menebak kredensial), "
        "'requires_oauth' (user harus menyambungkan akun - tunjukkan "
        "tombol connect), atau 'unknown_provider'."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "provider": types.Schema(
                type=types.Type.STRING,
                enum=["gmail_imap", "google_sheets", "telegram",
                      "slack", "supabase"],
                description="Provider yang ingin dicek status kredensialnya.",
            ),
        },
        required=["provider"],
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
        "(contoh: telegram, gmail, google_sheets, slack, http) DAN config wajib "
        "per provider: telegram{chat_id,pesan} · slack{channel,pesan} · "
        "http{url,method} · gmail{tujuan,subjek,isi} · "
        "google_sheets{spreadsheet_id,range_data} · whatsapp{nomor_tujuan,pesan} · "
        "google_calendar{nama_acara,waktu}. Bila jawaban ditolak, baca "
        "`errors`/`hint` lalu panggil ulang dengan perbaikan."
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


_web_search_declaration = types.FunctionDeclaration(
    name="web_search",
    description=(
        "Mencari informasi NYATA di internet (DuckDuckGo) dan mengembalikan "
        "judul + URL + cuplikan. WAJIB dipanggil sebelum menjawab pertanyaan "
        "teknis yang bisa berubah cepat (versi library, CVE, error message, "
        "best practice 2026) atau sebelum menebak penyebab bug — jangan "
        "berasumsi. Gunakan kueri singkat dan spesifik."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "query": types.Schema(
                type=types.Type.STRING,
                description="Kata kunci pencarian, mis. 'fastapi starlette CVE 2026'.",
            ),
            "max_results": types.Schema(
                type=types.Type.INTEGER,
                description="Jumlah hasil (default 5, maksimal 8).",
            ),
        },
        required=["query"],
    ),
)


_gmail_imap_declaration = types.FunctionDeclaration(
    name="trigger_gmail_imap",
    description=(
        "Membaca email BARU dari Gmail lewat IMAP (TIDAK OAuth). Cocok untuk "
        "trigger 'email masuk'. Butuh Gmail App Password 16 karakter yang "
        "dibuat user sendiri di myaccount.google.com/apppasswords (2FA aktif) - "
        "sengaja tanpa OAuth karena scope gmail.readonly itu restricted dan "
        "butuh review CASA. Kalau kredensial belum disimpan, tool melempar "
        "credential_missing provider 'gmail_imap' supaya UI menawarkan form."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "email_address": types.Schema(type=types.Type.STRING,
                description="Alamat Gmail yang dipoll (user@domain.com)."),
            "app_password": types.Schema(type=types.Type.STRING,
                description=(
                    "App Password 16 karakter. Kosongkan bila sudah tersimpan "
                    "di vault Katalir.")),
            "subject_filter": types.Schema(type=types.Type.STRING,
                description="Hanya ambil email yang subjeknya mengandung teks ini."),
            "max_messages": types.Schema(type=types.Type.INTEGER,
                description="Maksimal email (default 10, maks 50)."),
            "unread_only": types.Schema(type=types.Type.BOOLEAN,
                description="Hanya email UNREAD (default true)."),
        },
        required=["email_address"],
    ),
)


_sheets_dynamic_declaration = types.FunctionDeclaration(
    name="write_sheets_dynamic",
    description=(
        "Menulis satu baris ke Google Sheets dengan header DINAMIS: sheet "
        "kosong -> header dibuat dari kunci data; kunci baru -> kolom baru "
        "ditambahkan di kanan; kunci yang setara header lama dipetakan ke "
        "kolom itu (lintas bahasa, mis. 'qty' -> 'jumlah'). Menggantikan "
        "append biasa yang gagal saat header berubah."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "spreadsheet_id": types.Schema(type=types.Type.STRING,
                description="ID spreadsheet (bagian URL antara /d/ dan /edit)."),
            "sheet_name": types.Schema(type=types.Type.STRING,
                description="Nama tab/sheet, mis. 'inventory'."),
            "data": types.Schema(type=types.Type.OBJECT,
                description=(
                    "Objek data, mis. {'nama':'Kopi','qty':10,'harga':25000}. "
                    "Nilai boleh string/number/bool.")),
        },
        required=["spreadsheet_id", "data"],
    ),
)


TOOL_DECLARATIONS = [
    types.Tool(function_declarations=[
        _send_whatsapp_declaration,
        _baca_sheets_declaration,
        _buat_spreadsheet_declaration,
        _kirim_email_declaration,
        _agenda_calendar_declaration,
        _generate_workflow_declaration,
        _check_credential_declaration,
        _telegram_declaration,
        _slack_declaration,
        _http_declaration,
        _web_search_declaration,
        _gmail_imap_declaration,
        _sheets_dynamic_declaration,
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
# Provider yang punya alur OAuth sendiri: user TIDAK boleh diminta menempel
# token manual — UI harus menawarkan tombol Connect ke `/oauth/.../authorize`.
# BUG FIX 2026-10-03 (Gmail trigger): `gmail` dan `google_calendar` DIHAPUS dari
# sini. Audit 2026-09-28 sudah menghapuskannya dari `_oauth_providers`
# (api_server.py) karena `/oauth/google/authorize` meng-hardcode scope
# `auth/spreadsheets` - consent screen tidak pernah meminta izin Gmail. Kalau
# gmail tetap di sini, `execute_tool("kirim_email_gmail")` mengembalikan
# `needs_oauth` + tombol Connect yang mengarah ke consent screen yang tidak
# memberi akses Gmail: user menekan Connect, melihat "Connected", lalu tool-nya
# tetap gagal. Persis janji kosong yang harus dihindari.
#
# Konsekuensi yang disengaja: kedua provider itu kini kembali melempar
# `CredentialMissingError` -> `needs_credential`. Itu jujur walau form manual
# belum punya entri gmail.
#
# Cara menghidupkan Gmail dengan benar (SEMUA harus dikerjakan bersama, bukan sebagian):
#   1. oauth_google: tambahkan scope Gmail ke consent screen;
#   2. kirim_email_gmail: baca token dari user_vault (oauth_google.access_token),
#      bukan db.get_integration yang menunjuk user_integrations (plaintext);
#   3. baru masukkan gmail ke dict ini.
# Dilindungi tests/test_gmail_multitenant.py + tests/test_oauth_provider_honesty.py.
OAUTH_CONNECT_URLS = {
    "google_sheets": "/oauth/google/authorize",
    "slack": "/oauth/slack/authorize",
}


def _needs_oauth_result(provider: str) -> dict | None:
    """Hasil tool untuk provider ber-OAuth, atau None bila provider manual."""
    url = OAUTH_CONNECT_URLS.get(str(provider or "").strip().lower())
    if not url:
        return None
    return {
        "status": "needs_oauth",
        "provider": provider,
        "connect_url": url,
        "message": (f"Provider {provider} memakai OAuth. Klik Connect untuk "
                    f"menghubungkan akun Anda, lalu ulangi perintah ini."),
    }


def execute_tool(name: str, args: dict, email: str) -> str | dict:
    """Eksekusi alat by name dengan argumen + konteks user.

    DUA BENTUK HASIL (dan kenapa):
      * `str`  — hasil normal alat;
      * `dict` — `{"status": "needs_oauth", ...}` untuk provider ber-OAuth yang
        belum terhubung (Task 1C). User diberi tombol Connect, BUKAN form token
        manual: Google Sheets/Gmail/Calendar/Slack hanya bisa diakses lewat
        OAuth, jadi menempel token di form tidak akan pernah berhasil.

    `CredentialMissingError` untuk provider MANUAL (whatsapp, telegram, custom)
    tetap dilempar — perilaku itu dipakai UI form kredensial dan sudah dikunci
    tes lama. Provider manual tidak punya jalur OAuth, jadi tidak ada tombol
    Connect yang bisa ditawarkan.

    Raises:
        CredentialMissingError: kredensial provider MANUAL belum tersedia.
        ValueError: alat tidak dikenal.
    """
    try:
        # BUG FIX 2026-10-04: credential TIDAK lagi perlu masuk ke konteks LLM.
        # Model menulis `secret://provider/field`; broker me-resolve-nya di sini,
        # tepat sebelum handler dijalankan, jadi nilai asli tidak pernah menyentuh
        # prompt/respons/log. Argumen tanpa `secret://` tidak tersentuh.
        from vault_broker import (CredentialMissingError as _VaultMissing,
                                  resolve_secrets_in_args)
        try:
            args = resolve_secrets_in_args(args or {}, email)
        except _VaultMissing as exc:
            _trace(f"vault_ref_missing provider={exc.provider}")
            return {"status": "requires_credential", "provider": exc.provider,
                    "message": str(exc)}
        except ValueError as exc:  # SecretRefError juga turunan ValueError
            _trace(f"vault_ref_invalid {str(exc)[:60]}")
            return {"status": "error", "message": f"Referensi secret tidak valid: {exc}"}
        return _execute_tool_inner(name, args, email)
    except CredentialMissingError as exc:
        oauth_out = _needs_oauth_result(exc.provider_name)
        if oauth_out is None:
            raise
        _trace(f"needs_oauth provider={exc.provider_name} url={oauth_out['connect_url']}")
        return oauth_out


def check_credential_tool(provider: str, email: str = "") -> str:
    """Alat `check_credential`: status kredensial satu provider.

    Mengembalikan JSON string berisi `status`:
      * `ok`                 -> sudah tersimpan, proceed.
      * `requires_credential`-> inline form + resume_token (sudah disertakan).
      * `requires_oauth`     -> user harus menyambungkan akun.
      * `unknown_provider`   -> nama provider tidak dikenal.

    Tidak pernah melempar: model perlu bisa membaca status lalu berhenti.
    """
    from credential_forms import check_credential as _check
    try:
        result = _check(provider, email)
    except Exception as exc:  # noqa: BLE001 - kegagalan = "belum tahu", bukan crash
        _trace(f"check_credential_error provider={provider} {type(exc).__name__}")
        return _json.dumps({"status": "error", "provider": provider,
                            "message": "Gagal memeriksa status kredensial."})
    _trace(f"check_credential provider={provider} status={result.get('status')}")
    return _json.dumps(result, ensure_ascii=False)


def _execute_tool_inner(name: str, args: dict, email: str) -> str:
    """Badan dispatcher (dipisah supaya `execute_tool` bisa menangkap kredensial)."""
    if name == "check_credential":
        return check_credential_tool(provider=args.get("provider", ""), email=email)
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
    if name == "buat_google_spreadsheet":
        return buat_google_spreadsheet(
            title=args.get("title", ""),
            sheet_name=args.get("sheet_name", "Sheet1"),
            sheet_names=args.get("sheet_names") or [],
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
        # BUG FIX 2026-10-04: model mengirim payload di bawah kunci `workflow`,
        # bukan `spec_json`. Kalau hanya `spec_json` yang dibaca, nilainya
        # kosong dan validator menolak dengan "spec_json kosong".
        _payload = (args.get("spec_json") or args.get("workflow")
                    or args.get("draft") or args.get("spec")
                    or args.get("workflow_json") or "")
        return generate_workflow_json(spec_json=_payload, email=email)
    if name == "kirim_telegram_message":
        return kirim_telegram_message(
            chat_id=args.get("chat_id", ""),
            pesan=args.get("pesan", ""),
            email=email,
        )
    if name == "kirim_slack_message":
        return kirim_slack_message(
            channel=args.get("channel", ""),
            pesan=args.get("pesan", ""),
            email=email,
        )
    if name == "http_request":
        return http_request(
            url=args.get("url", ""),
            method=args.get("method", "GET"),
            body=args.get("body", ""),
            email=email,
        )
    if name == "web_search":
        return web_search(
            query=args.get("query", ""),
            max_results=args.get("max_results", 5),
        )
    if name == "trigger_gmail_imap":
        return trigger_gmail_imap_tool(
            email_address=args.get("email_address", ""),
            app_password=args.get("app_password", ""),
            subject_filter=args.get("subject_filter", ""),
            max_messages=args.get("max_messages", 10),
            unread_only=args.get("unread_only", True),
            email=email,
        )
    if name == "write_sheets_dynamic":
        return write_sheets_dynamic_tool(
            spreadsheet_id=args.get("spreadsheet_id", ""),
            sheet_name=args.get("sheet_name", "") or "Sheet1",
            data=args.get("data", {}),
            email=email,
        )
    raise ValueError(f"Unknown tool: {name}")