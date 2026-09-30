"""FOLLOWS UP — Uji ulang: apakah `sb_publishable_` lokal masih valid?

Sesi sebelumnya melaporkan HTTP 200 untuk key ini. Sekarang 401. Skrip ini
mengulang tes dengan langkah eksplisit supaya hasilnya bisa diaudit:

  1. Cetak prefix + panjang + fingerprint (nilai tidak pernah dicetak penuh)
  2. Tes header `apikey` saja            (dokumentasi 2026)
  3. Tes header `apikey` + `Bearer`      (cara lama)
  4. Tes skrip urllib vs requests-like UA, untuk menyingkirkan blokir Cloudflare
"""
import hashlib
import json
import pathlib
import re
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / ".env.bak-20260917-014828"


def main() -> int:
    text = SRC.read_text(encoding="utf-8", errors="replace")
    url = re.search(r"^SUPABASE_URL\s*=\s*(\S+)", text, re.M).group(1).strip()
    pub = re.search(r"^SUPABASE_PUBLISHABLE_KEY\s*=\s*(\S+)", text, re.M).group(1).strip()
    sr = re.search(r"^SUPABASE_SERVICE_ROLE_KEY\s*=\s*(\S+)", text, re.M).group(1).strip()

    print(f"  sb_publishable_ : prefix={pub[:20]}... len={len(pub)} "
          f"fp={hashlib.sha256(pub.encode()).hexdigest()[:10]}")
    print(f"  service_role JWT: prefix={sr[:10]}... len={len(sr)} "
          f"fp={hashlib.sha256(sr.encode()).hexdigest()[:10]}")
    print(f"  url host        : {url.split('//')[1].split('/')[0]}")
    print()

    cases = [
        ("sb_publishable_  apikey saja        ", pub, {"apikey": pub}),
        ("sb_publishable_  apikey+Bearer     ", pub, {"apikey": pub, "Authorization": "Bearer " + pub}),
        ("service_role JWT apikey+Bearer     ", sr, {"apikey": sr, "Authorization": "Bearer " + sr}),
    ]
    for label, _k, headers in cases:
        for ua in ("Katalir/1.0", "Python-urllib/3.12"):
            h = dict(headers)
            h["User-Agent"] = ua
            req = urllib.request.Request(
                f"{url}/rest/v1/workflows?select=id&limit=1", headers=h)
            try:
                r = urllib.request.urlopen(req, timeout=25)
                body = r.read().decode()
                res = f"HTTP {r.status}  rows={len(json.loads(body))}"
            except urllib.error.HTTPError as e:
                res = f"HTTP {e.code}  {e.read().decode('utf-8','replace')[:60]}"
            except Exception as e:  # noqa: BLE001
                res = f"ERR {type(e).__name__}"
            print(f"  {label} UA={ua:20s} -> {res}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
