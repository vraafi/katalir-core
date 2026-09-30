"""Bangun `.env.template` dari NAMA KEY saja (tanpa nilai) + komentar per grup.

Nilai TIDAK PERNAH ditulis ke template. Sumber: union key dari seluruh
`.env.bak-*` + `.env.example` supaya tidak ada key yang terlewat.
"""
import glob
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]

# Key yang bukan credential (URL / identifier / config publik)
NOT_SECRET = {
    "SUPABASE_URL", "CORS_ORIGIN", "PERSIST_REQUIRED", "DODO_PAYMENTS_ENVIRONMENT",
    "DODO_CHECKOUT_URL", "PAYMENT_PORTAL_URL", "CLOUDFLARE_R2_ENDPOINT",
    "EMAIL_IMAP_HOST", "EMAIL_IMAP_PORT", "EMAIL_CHECK_INTERVAL", "BRAVE_CDP_URL",
    "BRAVE_PATH", "CLOAK_DEBUG_PORT", "VPS_IP", "VPS_USERNAME", "VPS_OS",
    "LLM_GATEWAY_URL", "LLM_GATEWAY_MODELS", "AGENTGATEWAY_URL",
    "NINEROUTER_EXTERNAL_URL", "SUPABASE_JWKS", "CLOUDFLARE_ACCOUNT_ID",
    "SLACK_APP_ID", "TELEGRAM_APP_API_ID", "TELEGRAM_CHAT_ID",
    "ROBLOX_UNIVERSE_ID", "ROBLOX_PLACE_ID", "WA_BUSINESS_ACCOUNT_ID",
    "PHONE_NUMBER", "IG_USERNAME", "EMAIL_ADDRESS", "GOOGLE_CLIENT_ID",
    "GITHUB_CLIENT_ID", "SLACK_CLIENT_ID", "HOST", "PORT", "RELOAD",
    "APP_UI_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_KEY", "MCP_SDK",
}

GROUPS: list[tuple[str, str, list[str]]] = [
    ("Supabase", "WAJIB. service_role = bypass penuh RLS; rotasi via Dashboard.",
     ["SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_SERVICE_KEY",
      "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_PUBLISHABLE_KEY",
      "SUPABASE_DB_PASSWORD", "SUPABASE_JWKS"]),
    ("VPS", "Password root. JANGAN pernah masuk git.",
     ["VPS_IP", "VPS_USERNAME", "VPS_PASSWORD", "VPS_OS"]),
    ("Vault", "VAULT_SECRET_KEY = kunci master Fernet. Rotasi butuh re-encrypt.",
     ["VAULT_PASSWORD", "VAULT_SECRET_KEY"]),
    ("Billing - Dodo", "Webhook secret wajib atau billing mati (fail-closed 401).",
     ["DODO_API_KEY", "DODO_WEBHOOK_SECRET", "DODO_PAYMENTS_ENVIRONMENT",
      "DODO_CHECKOUT_URL", "PAYMENT_PORTAL_URL"]),
    ("Payment - lain", "HYRVE / NineRouter.",
     ["HYRVE_API_KEY", "NINEROUTER_KEY", "NINEROUTER_EXTERNAL_URL"]),
    ("LLM Provider", "Isi yang dipakai saja.",
     ["GEMINI_API_KEY", "GEMINI_KEY_1", "GEMINI_KEY_2", "GEMINI_KEY_3",
      "GEMINI_KEY_4", "GEMINI_KEY_5", "GEMINI_KEY_6", "GEMINI_KEY_7",
      "GEMINI_KEY_8", "GEMINI_KEY_9", "GEMINI_KEY_10", "GEMINI_KEY_11",
      "GEMINI_KEY_12", "GEMINI_KEY_13", "GROQ_API_KEY", "DEEPSEEK_API_KEY",
      "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "NVIDIA_API_KEY",
      "LLM_GATEWAY_URL", "LLM_GATEWAY_KEY", "LLM_GATEWAY_MODELS"]),
    ("MCP Gateway", "Token integrasi pihak ketiga.",
     ["AGENTGATEWAY_URL", "COMPOSIO_API_KEY", "COMPOSIO_API_KEY_consumer",
      "GLAMA_API_KEY", "NANGO_API_KEY", "METORIAL_API_KEY", "mptpilot_mcp"]),
    ("OAuth", "CLIENT_ID boleh publik; SECRET tidak.",
     ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GITHUB_CLIENT_ID",
      "GITHUB_CLIENT_SECRET", "SLACK_APP_ID", "SLACK_CLIENT_ID",
      "SLACK_CLIENT_SECRET", "SLACK_SIGNING_SECRET", "SLACK_VERIFICATION_TOKEN"]),
    ("Cloud / Deploy", "Railway & Cloudflare.",
     ["RAILWAY_TOKEN", "RAILWAY_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID",
      "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_R2_ACCESS_KEY_ID",
      "CLOUDFLARE_R2_SECRET_ACCESS_KEY", "CLOUDFLARE_R2_ENDPOINT"]),
    ("Messaging", "Telegram / WhatsApp / Email.",
     ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_APP_API_ID",
      "TELEGRAM_APP_API_HASH", "WA_TOKEN", "WA_PHONE_ID",
      "WA_BUSINESS_ACCOUNT_ID", "EMAIL_ADDRESS", "EMAIL_APP_PASSWORD",
      "EMAIL_IMAP_HOST", "EMAIL_IMAP_PORT", "EMAIL_CHECK_INTERVAL"]),
    ("DNS", "Registrar DNS.", ["DNSHE_API_KEY", "DNSHE_API_SECRET"]),
    ("Lain-lain", "Media / data / gaming / sosial.",
     ["PEXELS_API_KEY", "KAGGLE_API_TOKEN", "ROBLOX_UNIVERSE_ID",
      "ROBLOX_PLACE_ID", "ROBLOX_OPEN_CLOUD_API_KEY", "IG_USERNAME",
      "IG_PASSWORD", "PHONE_NUMBER"]),
    ("App config", "WAJIB: ALLOWED_HOSTS = mitigasi CVE-2026-48710.",
     ["ALLOWED_HOSTS", "CORS_ORIGIN", "APP_UI_URL", "PERSIST_REQUIRED",
      "CLOAK_DEBUG_PORT", "BRAVE_CDP_URL", "BRAVE_PATH", "HOST", "PORT",
      "RELOAD", "GITHUB_TOKEN"]),
]

PLACEHOLDER = {
    "SUPABASE_URL": "https://<project-ref>.supabase.co",
    "CORS_ORIGIN": "https://katalir.de5.net",
    "APP_UI_URL": "https://katalir.de5.net",
    "ALLOWED_HOSTS": "katalir.de5.net,web-production-dc90b.up.railway.app,localhost,127.0.0.1,testserver",
    "SUPABASE_JWKS": "di Railway saja - jangan diisi lokal",
    "LLM_GATEWAY_URL": "https://<host>/v1",
    "AGENTGATEWAY_URL": "https://<host>",
    "BRAVE_CDP_URL": "http://127.0.0.1:9222",
    "EMAIL_IMAP_PORT": "993",
    "EMAIL_CHECK_INTERVAL": "300",
    "CLOAK_DEBUG_PORT": "8765",
    "HOST": "0.0.0.0",
    "PORT": "8000",
    "RELOAD": "0",
    "CLOUDFLARE_R2_ENDPOINT": "https://<account>.r2.cloudflarestorage.com",
    "VPS_OS": "Ubuntu 24.04 LTS",
    "DODO_PAYMENTS_ENVIRONMENT": "live_mode",
}



def collect_keys() -> set[str]:
    """Union semua nama key yang pernah dipakai (tanpa membaca nilainya)."""
    keys: set[str] = set()
    sources = sorted(glob.glob(str(ROOT / ".env.bak-*"))) + [str(ROOT / ".env.example")]
    for f in sources:
        p = pathlib.Path(f)
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=", text, re.M):
            keys.add(m.group(1))
    return keys


HEADER = """# .env.template - DAFTAR KEY SAJA, TIDAK ADA SATU PUN NILAI DI SINI.
#
# Cara pakai:
#     cp .env.template .env
# lalu isi nilainya satu per satu.
#
# PENTING:
#   * File ini AMAN di-commit karena tidak memuat credential apa pun.
#   * `.env` (hasil cp) WAJIB tetap di-gitignore. Jangan pernah di-commit.
#   * Credential di daftar ini pernah bocor ke backup lama. SEMUA wajib
#     di-rotasi ulang - jangan dipakai apa adanya dari `.env.bak-*`.
#   * Nilai bertanda `# publik` bukan rahasia (URL / identifier), boleh diisi
#     nilai sebenarnya.
"""


def main() -> int:
    found = collect_keys()
    out: list[str] = [HEADER]
    used: set[str] = set()

    for title, note, keys in GROUPS:
        present = [k for k in keys if k in found and k not in used]
        if not present:
            continue
        used.update(present)
        out.append(f"# {'-' * 72}")
        out.append(f"# {title} - {note}")
        out.append(f"# {'-' * 72}")
        for k in present:
            if k in PLACEHOLDER:
                out.append(f"{k}={PLACEHOLDER[k]}")
            elif k in NOT_SECRET:
                out.append(f"{k}=   # publik/bukan rahasia")
            else:
                out.append(f"{k}=")
        out.append("")

    leftovers = sorted(found - used)
    if leftovers:
        out.append(f"# {'-' * 72}")
        out.append("# LAINNYA - ditemukan di backup, belum dikelompokkan")
        out.append(f"# {'-' * 72}")
        for k in leftovers:
            out.append(f"{k}=")
        out.append("")

    path = ROOT / ".env.template"
    path.write_text("\n".join(out), encoding="utf-8", newline="")
    total = sum(1 for l in out if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", l))
    print(f"  .env.template ditulis: {total} key, {len(out)} baris")
    print(f"  grouped={len(used)} leftovers={len(leftovers)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
