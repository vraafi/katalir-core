"""providers/credential_schemas.py — registry skema credential GENERIK.

KENAPA FILE INI ADA
------------------
Credential Katalir dulu tersebar: `tools.py` punya daftar per-tool, `api_server`
punya daftar per-endpoint, dan tiap credential baru berarti menyentuh beberapa
file. Itu tidak skala dan rawan tidak sinkron.

File ini adalah SATU-SUMBER-KEBENARAN untuk "credential apa yang dibutuhkan
provider X, dan bagaimana cara providernya memperolehnya". Backend, AI, dan
frontend semua membaca definisi yang sama:

  * `get_schema(provider)`  -> definisi lengkap (untuk build form).
  * `get_all_schemas()`     -> ringkasan (untuk konteks AI).
  * menambah provider baru = menambah satu entri di `CREDENTIAL_SCHEMAS`.

Dua MODE (penting)
------------------
`form`           - user mengetik sendiri di form INLINE di dalam chat.
`oauth_redirect` - user diarahkan ke consent screen provider.

Kenapa Google Sheets TIDAK boleh `form`: token OAuth Google tidak bisa
ditempel manual dengan benar oleh user (access token singkat, refresh token
di server). Menampilkan form token untuk provider OAuth = janji palsu - itu
persis bug yang sudah pernah terjadi di repo ini
(`docs/oauth/provider-status.md`).

CATATAN KEAMANAN (MCP Elicitation)
-----------------------------------
Spesifikasi MCP menyatakan server "MUST NOT use elicitation to request
sensitive information". Jalur `form` di sini tidak melanggar maksud itu karena
kredensial TIDAK PERNAH melewati model:

    browser -> POST /chat/resume -> vault_security (Fernet) -> user_vault
              (tidak pernah masuk prompt / tool-result / log)

Nilai rahasianya hanya pernah menyentuh (a) input user di browsernya sendiri,
(b) request HTTPS ke backend kita, (c) ciphertext di database. Model tidak
pernah melihatnya, tidak bisa membocorkannya lewat prompt, dan tidak bisa
menulisnya ke chat. Field `secret: true` ditandai ke frontend agar
dirender `type=password` dengan tombol reveal opsional (pola FieldRenderer
n8n / OpenCompany) supaya user bisa memverifikasi ketikkannya tanpa nilai itu
ditampilkan sebagai teks biasa.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
# `vault_provider` = kunci baris di `user_vault`. `mode` menentukan apakah form
# inline dirender atau user diarahkan ke OAuth.
CREDENTIAL_SCHEMAS: dict[str, dict[str, Any]] = {
    # --- Google Sheets: OAuth, TIDAK boleh form manual ---------------------
    "google_sheets": {
        "display_name": "Google Sheets",
        "mode": "oauth_redirect",
        "icon": "📊",
        "oauth_provider": "google",
        "authorize_path": "/oauth/google/authorize",
        "scopes": ["https://www.googleapis.com/auth/spreadsheets"],
        "test_tool": "baca_google_sheets",
        "vault_provider": "google_sheets",
    },

    # --- Gmail: IMAP + App Password, tanpa OAuth sama sekali --------------
    "gmail_imap": {
        "display_name": "Gmail (via App Password)",
        "mode": "form",
        "icon": "📧",
        "fields": [
            {
                "name": "email",
                "label": "Alamat Gmail",
                "type": "email",
                "placeholder": "nama@gmail.com",
                "required": True,
                "secret": False,
            },
            {
                "name": "app_password",
                "label": "App Password (16 karakter)",
                "type": "password",
                "placeholder": "xxxx xxxx xxxx xxxx",
                "required": True,
                "secret": True,
                "min_length": 16,
                # Google menampilkannya bergROUP; IMAP butuh tanpa spasi.
                "transform": "strip_spaces",
                "help_url": "https://myaccount.google.com/apppasswords",
                "help_text": "Buat App Password di Google Account (butuh 2FA aktif).",
            },
        ],
        "test_tool": "trigger_gmail_imap",
        "vault_provider": "gmail_imap",
    },

    # --- Slack: OAuth ------------------------------------------------------
    "slack": {
        "display_name": "Slack",
        "mode": "oauth_redirect",
        "icon": "💼",
        "oauth_provider": "slack",
        "authorize_path": "/oauth/slack/authorize",
        "scopes": ["chat:write", "channels:read"],
        "test_tool": "kirim_slack_message",
        "vault_provider": "slack",
    },
    # --- Telegram: bot token + chat id -------------------------------------
    "telegram": {
        "display_name": "Telegram Bot",
        "mode": "form",
        "icon": "💬",
        "fields": [
            {
                "name": "bot_token",
                "label": "Bot Token",
                "type": "password",
                "placeholder": "123456:ABC-DEF...",
                "required": True,
                "secret": True,
                "help_url": "https://t.me/BotFather",
                "help_text": "Buat bot baru lewat @BotFather.",
            },
            {
                "name": "chat_id",
                "label": "Chat ID tujuan",
                "type": "text",
                "placeholder": "2109751369",
                "required": True,
                "secret": False,
                "help_url": "https://t.me/userinfobot",
                "help_text": "Dapatkan Chat ID kamu dari @userinfobot.",
            },
        ],
        "test_tool": "kirim_telegram_message",
        "vault_provider": "telegram",
    },

    # --- Supabase: project URL + service role key (+ anon opsional) ---------
    "supabase": {
        "display_name": "Supabase",
        "mode": "form",
        "icon": "🗄️",
        "fields": [
            {
                "name": "project_url",
                "label": "Supabase Project URL",
                "type": "url",
                "placeholder": "https://xxxx.supabase.co",
                "required": True,
                "secret": False,
            },
            {
                "name": "service_role_key",
                "label": "Service Role Key",
                "type": "password",
                "placeholder": "eyJhbGciOiJIUzI1NiIs...",
                "required": True,
                "secret": True,
                "help_url": "https://supabase.com/dashboard/project/_/settings/api",
                "help_text": "Settings -> API -> Service Role Key (bukan anon key).",
            },
            {
                "name": "anon_key",
                "label": "Anon Key (opsional)",
                "type": "password",
                "placeholder": "eyJhbGciOiJIUzI1NiIs...",
                "required": False,
                "secret": True,
            },
        ],
        "test_tool": None,
        "vault_provider": "supabase",
    },
}


# ---------------------------------------------------------------------------
# Akses
# ---------------------------------------------------------------------------
def get_schema(provider: str) -> dict[str, Any] | None:
    """Definisi lengkap satu provider, atau None bila tidak dikenal."""
    return CREDENTIAL_SCHEMAS.get(str(provider or "").strip().lower())


def get_all_schemas() -> dict[str, dict[str, Any]]:
    """Ringkasan semua provider (dipakai untuk konteks AI + validasi)."""
    out: dict[str, dict[str, Any]] = {}
    for key, spec in CREDENTIAL_SCHEMAS.items():
        out[key] = {
            "display_name": spec["display_name"],
            "mode": spec["mode"],
            "fields": [f["name"] for f in spec.get("fields", [])],
        }
    return out


def providers_using_form() -> list[str]:
    """Provider yang credential-nya diisi lewat form inline di chat."""
    return [k for k, v in CREDENTIAL_SCHEMAS.items() if v.get("mode") == "form"]


def providers_using_oauth() -> list[str]:
    """Provider yang harus lewat redirect OAuth."""
    return [k for k, v in CREDENTIAL_SCHEMAS.items() if v.get("mode") == "oauth_redirect"]
