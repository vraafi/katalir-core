"""Verifikasi `.env.template`: HARUS 0 nilai credential.

Sangat ketat: setiap baris `KEY=` di template dibandingkan dengan SETIAP
nilai yang pernah ada di `.env.bak-*` / `.env.example`. Kalau satu pun
cocok, template dianggap bocor dan skrip ini GAGAL (exit 1).
"""
import glob
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
MIN_SECRET_LEN = 8

# Key yang isinya memang BUKAN rahasia (URL publik, enum, identifier).
# Nilainya boleh dan HARUS muncul di template, jadi tidak diperiksa.
NON_SECRET_KEYS = {
    "ALLOWED_HOSTS", "CORS_ORIGIN", "APP_UI_URL", "SUPABASE_URL",
    "DODO_CHECKOUT_URL", "PAYMENT_PORTAL_URL", "CLOUDFLARE_R2_ENDPOINT",
    "CLOUDFLARE_ACCOUNT_ID", "LLM_GATEWAY_URL", "LLM_GATEWAY_MODELS",
    "AGENTGATEWAY_URL", "NINEROUTER_EXTERNAL_URL", "EMAIL_IMAP_HOST",
    "EMAIL_IMP_PORT", "EMAIL_IMAP_PORT", "EMAIL_CHECK_INTERVAL",
    "BRAVE_CDP_URL", "CLOAK_DEBUG_PORT", "VPS_IP", "VPS_USERNAME",
    "VPS_OS", "HOST", "PORT", "RELOAD", "DODO_PAYMENTS_ENVIRONMENT",
    "SUPABASE_JWKS", "PHONE_NUMBER", "IG_USERNAME", "EMAIL_ADDRESS",
    "TELEGRAM_CHAT_ID", "TELEGRAM_APP_API_ID", "SLACK_APP_ID",
    "GOOGLE_CLIENT_ID", "GITHUB_CLIENT_ID", "SLACK_CLIENT_ID",
    "ROBLOX_UNIVERSE_ID", "ROBLOX_PLACE_ID", "WA_BUSINESS_ACCOUNT_ID",
    "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_KEY", "MCP_SDK",
}


def main() -> int:
    tpl_path = ROOT / ".env.template"
    if not tpl_path.is_file():
        print("GAGAL: .env.template tidak ada")
        return 1
    tpl = tpl_path.read_text(encoding="utf-8", errors="replace")

    values: dict[str, str] = {}
    for f in sorted(glob.glob(str(ROOT / ".env.bak-*"))) + [str(ROOT / ".env.example")]:
        p = pathlib.Path(f)
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if "=" not in s or s.startswith("#"):
                continue
            k, _, raw = s.partition("=")
            k = k.strip()
            v = raw.split(" #")[0].strip().strip('"').strip("'")
            if len(v) >= MIN_SECRET_LEN and k not in NON_SECRET_KEYS:
                values.setdefault(v, k)

    leaked = sorted((k, v) for v, k in values.items() if v in tpl)
    print(f"  nilai rahasia diperiksa : {len(values)} (dari key rahasia, len>={MIN_SECRET_LEN})")
    print(f"  NILAI BOCOR KE TEMPLATE : {len(leaked)}")
    for k, v in leaked:
        print(f"    LEAK: key={k} nilai={v[:6]}...(len {len(v)})")

    keys = re.findall(r"^([A-Za-z_][A-Za-z0-9_]*)=", tpl, re.M)
    dupes = {k for k in keys if keys.count(k) > 1}
    pats = [
        "ghp_[A-Za-z0-9]{10,}", "github_pat_[A-Za-z0-9_]{10,}",
        "sk-[A-Za-z0-9]{20,}", "whsec_[A-Za-z0-9]{10,}",
        "AIza[0-9A-Za-z_-]{10,}", "AKIA[0-9A-Z]{16}",
        "eyJ[A-Za-z0-9_-]{10,}", "xox[baprs]-[A-Za-z0-9-]{10,}",
    ]
    pat_hits = sum(len(re.findall(p, tpl)) for p in pats)
    print(f"  key di template         : {len(keys)} (duplikat: {sorted(dupes) or 'tidak ada'})")
    print(f"  pola secret di template : {pat_hits}")

    ok = not leaked and not dupes and pat_hits == 0
    print(f"  HASIL: {'AMAN' if ok else 'GAGAL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
