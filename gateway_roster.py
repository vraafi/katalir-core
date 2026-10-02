# gateway_roster.py — Roster model LIVE dari free-llm-gateway (empiris).
"""Katalog gateway TIDAK bisa dipercaya begitu saja.

Provider gratis sering mencabut model: entri katalog masih ada dan
`has_key:true` (alias gateway masih mengarah ke id upstream lama), tetapi
upstream menjawab 410 Gone / 404 / 500. Karena itu roster di sini dibangun
dengan PROBE empiris: satu request chat pendek per kandidat, lalu hasilnya
(PASS/FAIL + latensi) di-cache selama `CACHE_TTL_S`.

Tiga lapis penjaga kepercayaan (anti false-positive):
  1. CACHE-BUSTED   : prompt berisi nonce unik -> response_cache gateway MISS,
                      jadi latensi & isi benar-benar dari upstream.
  2. NO SUBSTITUSI  : header `X-Routed-Via` ("provider/model") harus melaporkan
                      MODEL YANG SAMA dengan yang diminta. Gateway jujur
                      melaporkan substitusi (alias mati -> nemotron), jadi
                      model yang menjawab != yang diminta = bukan bukti hidup.
                      (Catatan: `X-Fallback-Attempts` SELALU bernilai 1 di
                      build ini sehingga tidak bisa dipakai sebagai gerbang.)
  3. ISI NYATA      : content harus non-kosong (bukan reasoning-token habis).

Hanya model PASS yang boleh disajikan ke frontend.
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import logging
import os
import random
import re
import threading
import time

import httpx

log = logging.getLogger("gateway_roster")

CACHE_TTL_S = int(os.getenv("LLM_GATEWAY_ROSTER_TTL", "21600"))   # 6 jam
CACHE_PATH = os.getenv("LLM_GATEWAY_ROSTER_CACHE", ".gw_roster_cache.json")
PROBE_TIMEOUT_S = float(os.getenv("LLM_GATEWAY_PROBE_TIMEOUT", "90"))
PROBE_WORKERS = int(os.getenv("LLM_GATEWAY_PROBE_WORKERS", "8"))
MAX_ROSTER = int(os.getenv("LLM_GATEWAY_MAX_MODELS", "40"))

# RETRY (2026-09-19, temuan: roster kosong -> fallback Gemini SENYAP):
# satu kegagalan HTTP di `/v1/models` (mis. saat Railway baru restart dan
# gateway sedang sibuk) langsung membuat seluruh roster kosong. Pola AWS
# "timeouts, retries and backoff": ulang beberapa kali dengan exponential
# backoff + jitter supaya kegagalan sesaat tidak berubah jadi degradasi.
LIST_ATTEMPTS = int(os.getenv("LLM_GATEWAY_LIST_ATTEMPTS", "3"))
BACKOFF_BASE_S = float(os.getenv("LLM_GATEWAY_BACKOFF_BASE", "1.0"))

# STATUS ROSTER (untuk flag `degraded` di /models). Bukan cache — hanya
# metadata: dari MANA roster terakhir berasal dan apa yang gagal.
_state: dict = {"source": "unknown", "reason": "", "ts": 0.0, "cache_age_s": None}

# Non-chat / media / special-purpose: bukan model percakapan teks.
_NON_CHAT = re.compile(
    r"embed|whisper|audio|tts|speech|image|vision|guard|parse|moderat|rerank|"
    r"diffus|clip|stable|sd[-_]|flux|screen|video|ocr|bbox|inpaint|upscal|face|"
    r"background|translate|code-?scan|safety|detector|reward|arctic|neva|vila|"
    r"kosmos|deplot|fuyu|recurrent|aqa|imagen|veo|native-audio|lyria|"
    r"nano-?banana|transcribe|robotic|computer-use|antigravity|calibration|"
    r"ising|glimmer|sora|dall|recraft|kandinsky|playground|nv-|isaac|cu-?opt|"
    r"research",
    re.I,
)

_cache: dict = {"ts": 0.0, "models": []}

# ---------------------------------------------------------------------------
# GATE PAID-ONLY (3-gate, pola OmniRoute #6495)
#
# Kenapa perlu: probe empiris kita hanya mengirim SATU pesan pendek (64 token).
# Model paid-only tetap PASS karena 1 pesan tidak menembus kuota harian yang
# tidak diketahui, dan Google sudah menarik tabel RPM/RPD dari dokumentasi.
# Akibatnya model seperti `gemini-3.1-pro-preview` (RPD 0 sejak 1 Apr 2026)
# bisa dipilih user, lalu request-nya diam-diam DIALIHKAN ke model lain oleh
# gateway -> user melihat jawaban dari model yang bukan pilihannya.
#
# CATATAN PENTING (hasil verifikasi empiris, bukan asumsi):
#   - Provider roster kita adalah `google_gemini` / `groq` / `nvidia`, sedangkan
#     provider discovery Gemini langsung adalah `Google (Gemini)`. Karena itu
#     `provider == "google"` TIDAK pemah cocok -> dipakai `_provider_family()`.
#   - Gate 2 (allowlist) hanya diterapkan ke keluarga google. Provider lain
#     (groq/nvidia) sudah diverifikasi `X-Routed-Via` di probe, dan model
#     seperti `nvidia/nemotron-3-nano-omni-...` mengandung "omni" tetapi
#     TERBUKTI menjawab chat: pola "omni" sengaja TIDAK dipakai agar model
#     hidup tidak ikut terhapus.
#   - Non-chat/media TIDAK diduplikasi di sini; sudah ditangani `_NON_CHAT`
#     lewat `chat_capable()`. `filter_free_models()` menggabungkan keduanya.
# ---------------------------------------------------------------------------

# Gate 1 — pola id paid-only. Sengaja sempit (hanya yang terbukti paid-only)
# agar tidak menyerempet model gratis: "-pro" mengenai `gemini-2.5-pro`,
# `gemini-3.1-pro-preview`, `gemini-pro-latest`; "advanced" untuk varian
# berbayar bergaya lama. "preview"/"compound" TIDAK terpengaruh.
_PAID_ONLY_PATTERNS = ("-pro", "pro-latest", "advanced")

# Gate 2 — allowlist free-tier Gemini.
# Basis: pengukuran Sep 2026 (semua model Pro = RPD 0; Flash 20 RPD;
# Flash-Lite 500 RPD) + id yang TERBUKTI hidup lewat probe roster kita
# sendiri (gemini-2.5-flash 1128ms & gemini-2.5-flash-lite 602ms, PASS di
# cache roster) dan dipakai `GEMINI_FALLBACK`/`AGENT_FALLBACK_MODEL`.
# Tanpa tambahan itu Gate 2 akan MENGHAPUS model valid.
FREE_TIER_MODEL_IDS = frozenset({
    # Gemini Flash
    "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash",
    "gemini-3.5-flash", "gemini-3-flash-preview",
    # Gemini Flash-Lite (500 RPD) — recommended
    "gemini-3.5-flash-lite", "gemini-3.1-flash-lite",
    # Varian PREVIEW dari Flash-Lite juga free tier (pola sama dengan
    # `gemini-3-flash-preview` yang sudah diizinkan di atas). Sempat terbuang
    # oleh gerbang allowlist ini sampai ditemukan di audit before/after
    # (41 -> 13 model): keluarga flash-lite TIDAK boleh hilang — lihat
    # constraint tugas "jangan hapus model valid (flash, flash-lite, gemma)".
    "gemini-3.1-flash-lite-preview",
    # Gemma
    "gemma-4-31b-it", "gemma-4-26b-a4b-it", "gemma-3-27b-it",
    # Terbukti hidup via probe roster kita (jangan dihapus — lihat catatan).
    "gemini-2.5-flash", "gemini-2.5-flash-lite",
    # Alias resmi ke model Flash (bukan Pro).
    "gemini-flash-latest", "gemini-flash-lite-latest",
})


ALLOWED_MODELS = {
    "free": frozenset(FREE_TIER_MODEL_IDS),
    "plus": frozenset({"*"}),
}


def is_allowed(model: str, tier: str) -> bool:
    """Allowlist ketat per tier; unknown/empty tier selalu deny."""
    allowed = ALLOWED_MODELS.get((tier or "").strip().lower(), frozenset())
    if not allowed:
        return False
    return "*" in allowed or model in allowed


def _log_blocked_model(model: str, tier: str, reason: str) -> None:
    log.info("model_blocked model=%s tier=%s reason=%s", model, tier, reason)


def _model_allowed_for_tier(model: str, tier: str = "free", provider: str = "") -> bool:
    """Gate 2 (allowlist) - HANYA untuk keluarga google.

    BUG FIX 2026-10-02: allowlist `FREE_TIER_MODEL_IDS` hanya berisi id Gemini,
    tapi fungsi ini dipanggil untuk SEMUA model termasuk roster gateway yang
    serves llama/gemma/qwen/deepseek/... Akibatnya 259 model gateway terbuang
    dan `/models` hanya mengembalikan 3 (Gemini yang kebetulan ada di allowlist).

    Komentar di atas blok GATE PAID-ONLY sebenarnya sudah menyatakan niat yang
    benar: "Gate 2 (allowlist) hanya diterapkan ke keluarga google. Provider lain
    (groq/nvidia) sudah diverifikasi X-Routed-Via di probe." Implementasinya
    belum pernah diterapkan - itu bug ini.

    Model non-google tidak dibiarkan tanpa filter: Gate 1 (pola paid-only) dan
    `_NON_CHAT` (chat_capable) tetap diterapkan, jadi gambar/embedding/robotics
    tetap dibuang.
    """
    if is_allowed(model, tier):
        return True
    family = _provider_family(provider)
    # Hanya family yang DIKETAHUI non-google yang boleh lolos Gate 2.
    #
    # Provider kosong ("") = tidak diketahui -> tetap DENY. Ini menjaga
    # `test_blocked_model_is_logged` yang memanggil fungsi ini tanpa provider
    # dan mengharapkan model tak dikenal ditolak.
    if family and family != "google":
        # Bukan Gemini -> lolos Gate 2 (masih harus lolos Gate 1 + chat_capable).
        return True
    _log_blocked_model(model, tier, "tier_allowlist")
    return False


def _provider_family(provider: str) -> str:
    """Normalisasi nama provider lintas sumber (roster vs discovery)."""
    p = (provider or "").strip().lower()
    if not p:
        return ""
    if "google" in p or "gemini" in p:
        return "google"
    if "openrouter" in p:
        return "openrouter"
    return p


def is_paid_only(model_id: str, provider: str = "") -> bool:
    """True bila model tergolong paid-only (3 gerbang).

    Gerbang:
      1. pola id paid-only (`-pro`, `pro-latest`, `advanced`);
      2. model keluarga Google di luar `FREE_TIER_MODEL_IDS`;
      3. keluarga OpenRouter yang id-nya tidak berakhiran `:free`.

    Gerbang 3 saat ini INERT: roster gateway tidak memuat provider openrouter
    (id yang ada: google_gemini, groq, nvidia). Dipertahankan agar perilaku
    tetap benar bila provider itu ditambahkan ke gateway.

    `provider` kosong (belum diketahui, mis. saat pra-filter kandidat) hanya
    menjalankan gerbang 1 — gerbang 2 butuh tahu provider-nya.
    """
    mid = (model_id or "").strip().lower()
    if not mid:
        return True
    if any(pat in mid for pat in _PAID_ONLY_PATTERNS):
        return True
    fam = _provider_family(provider)
    if fam == "google":
        return model_id not in FREE_TIER_MODEL_IDS
    if fam == "openrouter":
        return not mid.endswith(":free")
    return False


def filter_free_models(models: list[dict]) -> list[dict]:
    """Buang model non-chat/media (`_NON_CHAT`) DAN paid-only.

    Dipakai pada katalog mentah (mis. discovery Gemini langsung yang berisi
    model image/tts/lyria/robotics/pro) sebelum disajikan ke frontend.
    """
    out: list[dict] = []
    for m in models or []:
        # Entri non-dict (mis. `null` di dalam array JSON dari upstream) harus
        # dilewati, BUKAN membuat seluruh endpoint /models 500. Data ini datang
        # dari jaringan (`/v1/models`, discovery Gemini) sehingga bentuknya di
        # luar kendali kita — dibuktikan `test_filter_tahan_input_kotor`.
        if not isinstance(m, dict):
            continue
        mid = str(m.get("id") or "")
        if not mid or not chat_capable(mid):
            continue
        if is_paid_only(mid, str(m.get("provider") or "")) or not _model_allowed_for_tier(mid, "free", str(m.get("provider") or "")):
            continue
        out.append(m)
    return out


# Alias nama env gateway.
#
# Kode ini menetapkan `LLM_GATEWAY_URL`/`LLM_GATEWAY_KEY`, tetapi dokumentasi
# deploy (brief/Tailscale) memakai `FREELM_GATEWAY_URL`. Tanpa alias, salah
# tulis nama = gateway TIDAK terpakai sama sekali dan trafik diam-diam jatuh
# ke Gemini direct — kegagalan senyap yang sulit dilacak.
#
# Nama polos (`GATEWAY_URL`/`GATEWAY_KEY`) ada di prioritas TERAKHIR karena
# berisiko bentrok dengan layanan lain (mis. open-connector di agent_engine.py
# punya gateway sendiri). Urutan prioritas dipakai hanya bila yang lebih
# spesifik kosong.
GATEWAY_URL_ENVS = ("LLM_GATEWAY_URL", "FREELM_GATEWAY_URL", "GATEWAY_URL")
GATEWAY_KEY_ENVS = ("LLM_GATEWAY_KEY", "FREELM_GATEWAY_KEY", "GATEWAY_KEY")


def _env_first(names: tuple[str, ...]) -> tuple[str, str] | None:
    """(nilai, nama_env) pertama yang terisi dari `names`; None bila kosong."""
    for name in names:
        val = (os.getenv(name) or "").strip()
        if val:
            return val, name
    return None


def gateway_config() -> tuple[str | None, str | None]:
    """(base_url, master_key) gateway; (None, None) bila belum dikonfigurasi."""
    url_hit = _env_first(GATEWAY_URL_ENVS)
    key_hit = _env_first(GATEWAY_KEY_ENVS)
    if not url_hit or not key_hit:
        return None, None
    url = url_hit[0].rstrip("/")
    key = key_hit[0]
    # Jejak sekali agar alias yang terpakai terlihat di log deploy (membantu
    # melacak env mana yang benar-benar terbaca).
    if url_hit[1] != GATEWAY_URL_ENVS[0] or key_hit[1] != GATEWAY_KEY_ENVS[0]:
        log.info("Gateway env alias dipakai: %s + %s", url_hit[1], key_hit[1])
    return url, key


def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def chat_capable(model_id: str) -> bool:
    """True bila id tampak seperti model percakapan teks biasa."""
    return bool(model_id) and not _NON_CHAT.search(model_id)


def _get_json_retry(client: httpx.Client, url: str, hdr: dict,
                    attempts: int = LIST_ATTEMPTS) -> dict:
    """GET + retry (exponential backoff + jitter). Melempar bila semua gagal.

    Kenapa penting: kegagalan sesaat di sini membuat SELURUH roster kosong,
    dan sebelumnya itu berujung fallback Gemini tanpa sinyal apa pun.
    """
    last: Exception | None = None
    for i in range(max(1, attempts)):
        try:
            r = client.get(url, headers=hdr)
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001 - dicoba ulang
            last = exc
            if i < attempts - 1:
                wait = (BACKOFF_BASE_S * (2 ** i)) + random.uniform(0, 0.5)
                log.info("Retry %s/%s untuk %s setelah %.1fs (%s)",
                         i + 1, attempts, url, wait, type(exc).__name__)
                time.sleep(wait)
    raise last if last else RuntimeError("GET gagal tanpa exception")


def _list_candidates(client: httpx.Client, url: str, key: str) -> list[dict]:
    """Kandidat dari gateway: /v1/models + /api/status (provider ber-key)."""
    hdr = _headers(key)
    have: set[str] = set()
    try:
        data = _get_json_retry(client, f"{url}/v1/models", hdr)
        for m in (data.get("data") or []):
            mid = m.get("id") if isinstance(m, dict) else str(m)
            if mid:
                have.add(mid)
    except Exception as exc:  # noqa: BLE001 - gateway belum siap
        _state.update({"source": "empty", "reason": f"list_models_failed:{type(exc).__name__}",
                       "ts": time.time(), "cache_age_s": None})
        log.warning("Gateway /v1/models gagal setelah %d percobaan (%s).",
                    LIST_ATTEMPTS, exc)
        return []

    expected: dict[str, set[str]] = {}
    try:
        r = client.get(f"{url}/api/status", headers=hdr)
        r.raise_for_status()
        for m in (r.json().get("models") or []):
            name = m.get("name")
            if not name:
                continue
            provs = {p.get("name") or p.get("provider") or ""
                     for p in (m.get("providers") or []) if p.get("has_key")}
            provs.discard("")
            if provs:
                expected[name] = provs
    except Exception as exc:  # noqa: BLE001 - opsional, hanya untuk ekspektasi
        log.info("Gateway /api/status tidak tersedia (%s).", exc)

    out = []
    for mid in sorted(have):
        if not chat_capable(mid):
            continue
        # Gate 1 (pola) bisa dijalankan sekarang walau provider belum diketahui;
        # Gate 2 (allowlist provider) menunggu hasil probe.
        if is_paid_only(mid):
            continue
        out.append({"id": mid, "providers": expected.get(mid, set())})
    return out


def _probe_one(client: httpx.Client, url: str, key: str, cand: dict,
               nonce: str, ix: int) -> dict:
    """Satu request chat pendek; PASS hanya bila ketiga gerbang lolos."""
    mid = cand["id"]
    payload = {
        "model": mid,
        "max_tokens": 64,
        "temperature": 0.0,
        "messages": [{"role": "user",
                      "content": f"[nonce-{nonce}-{ix}] Balas hanya: OK"}],
    }
    rec = {"model": mid, "status": "FAIL", "ms": 0, "routed": "",
           "fallbacks": "", "cache": "", "sample": "", "error": "",
           "provider": (sorted(cand["providers"])[0] if cand["providers"] else "")}
    t0 = time.time()
    try:
        r = client.post(f"{url}/v1/chat/completions", headers=_headers(key),
                        json=payload)
        rec["ms"] = int((time.time() - t0) * 1000)
        if r.status_code != 200:
            rec["error"] = f"HTTP{r.status_code}: {r.text[:110]}"
            return rec
        data = r.json()
    except Exception as exc:  # noqa: BLE001 - timeout/conn
        rec["ms"] = int((time.time() - t0) * 1000)
        rec["error"] = f"{type(exc).__name__}: {str(exc)[:100]}"
        return rec

    rec["routed"] = r.headers.get("x-routed-via", "")
    rec["fallbacks"] = r.headers.get("x-fallback-attempts", "")
    rec["cache"] = r.headers.get("x-cache", "")
    ch = (data.get("choices") or [{}])[0]
    txt = (ch.get("message") or {}).get("content") or ""
    rec["sample"] = (txt or "").strip()[:48]

    if rec["cache"] == "HIT":
        rec["error"] = "cache HIT (probe tidak valid)"
        return rec
    if not rec["routed"]:
        rec["error"] = "header X-Routed-Via tidak ada"
        return rec
    rprov, _, _rpath = rec["routed"].partition("/")
    # BUG FIX 2026-10-01: `X-Routed-Via` bisa BerNAMA BERLAPIS, misalnya
    # "nvidia/google/gemma-4-31b-it" (provider = nvidia, upstream = google).
    # `partition("/")` memecah HANYA di slash pertama, jadi `rmodel` berisi
    # "google/gemma-4-31b-it" dan tidak pernah sama dengan mid
    # "gemma-4-31b-it". Akibatnya model yang BENAR-BENAR hidup ditolak sebagai
    # "disubstitusi", roster jadi kosong, dan UI jatuh ke GEMINI_FALLBACK.
    # Yang relevan hanya NAMA model = segmen TERAKHIR.
    rmodel = _rpath.rsplit("/", 1)[-1]
    # BUG FIX 2026-10-02: perbaikan 10-01 di atas hanya separuh masalah, dan
    # justru MEMECAH kasus lain yang justru paling umum. Provider modern
    # menamespace id model-nya, jadi `mid` yang benar pun mengandung "/":
    #
    #   mid = "z-ai/glm-5.3"     -> routed "nvidia/z-ai/glm-5.3"
    #   mid = "qwen/qwen3.8-27b" -> routed "groq/qwen/qwen3.8-27b"
    #
    # Di kedua kasus `rmodel` (segmen TERAKHIR) tidak pernah sama dengan `mid`,
    # sehingga model yang hidup ditolak sebagai "disubstitusi". Akibatnya probe
    # menolak hampir semua model dan roster hanya berisi 1 model gateway
    # (allam-2-7b) sehingga UI hanya menampilkan 3-4 model.
    #
    # Bukti (72 model hidup diuji langsung ke gateway): 19 model HTTP 200, tapi
    # hanya 1 yang lolos perbandingan ini. 18 sisanya terbuang padahal header
    # routed-nya BENAR.
    #
    # Perbaikan: terima bila SALAH SATU cocok - path LENGKAP (`_rpath`, untuk mid
    # ber-namespace) ATAU segmen terakhir (`rmodel`, untuk mid polos seperti
    # kasus 10-01). Keduanya menunjuk model yang sama, jadi deteksi substitusi
    # tetap utuh: substitusi sejati mengubah segmen terakhir sehingga kedua
    # perbandingan sama-sama gagal dan model tetap ditolak.
    if _rpath != mid and rmodel != mid:
        rec["error"] = f"disubstitusi ke '{rec['routed']}'"
        return rec
    if not txt.strip():
        rec["error"] = "content kosong"
        return rec
    rec["status"] = "PASS"
    rec["provider"] = rprov
    return rec


# ---------------------------------------------------------------------------
# CACHE PERSISTENT (Supabase) — A3
#
# Filesystem Railway bersifat EPHEMERAL: `.gw_roster_cache.json` hilang setiap
# deploy/restart, sehingga instance baru hanya bergantung pada SATU probe
# gateway. Bila probe itu meleset, roster kosong dan (sebelum perbaikan ini)
# discovery diam-diam jatuh ke daftar Gemini-only. Tabel `roster_cache`
# (migrations/2026_roster_cache.sql) menyimpan roster terakhir agar restart
# tidak pernah kehilangan daftar provider.
# ---------------------------------------------------------------------------
def _iso(ts: float | None) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ts or time.time(), tz=timezone.utc).isoformat()


def _parse_ts(value: object) -> float:
    from datetime import datetime

    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:  # noqa: BLE001 - format tak terduga -> anggap sekarang
        return time.time()


def _sb_creds() -> tuple[str, str] | None:
    url = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
    key = (os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY") or "").strip()
    return (url, key) if url and key else None


def _load_cache_supabase() -> dict | None:
    creds = _sb_creds()
    if not creds:
        return None
    url, key = creds
    try:
        r = httpx.get(
            f"{url}/rest/v1/roster_cache",
            params={"id": "eq.current", "select": "models,created_at"},
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=12,
        )
        r.raise_for_status()
        rows = r.json() or []
        if rows and isinstance(rows[0].get("models"), list) and rows[0]["models"]:
            return {"ts": _parse_ts(rows[0].get("created_at")), "models": rows[0]["models"]}
    except Exception as exc:  # noqa: BLE001 - cache opsional
        log.info("Cache roster Supabase tidak terbaca (%s).", type(exc).__name__)
    return None


def _save_cache_supabase(ts: float, models: list[dict]) -> bool:
    creds = _sb_creds()
    if not creds:
        return False
    url, key = creds
    try:
        r = httpx.post(
            f"{url}/rest/v1/roster_cache",
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates,return=minimal",
            },
            json=[{"id": "current", "models": models, "created_at": _iso(ts)}],
            timeout=12,
        )
        r.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001 - cache opsional
        log.info("Cache roster Supabase gagal ditulis (%s).", type(exc).__name__)
        return False


def _load_cache() -> dict:
    sb = _load_cache_supabase()
    if sb and sb["models"]:
        # PENTING: `ts` sengaja di-nol-kan untuk cache Supabase. Tujuannya
        # bukan menggantikan probe, melainkan JARING PENYELAMAT saat gateway
        # tidak terjangkau. Dengan ts=0 baris ini selalu dianggap BASI, jadi:
        #   - probe gateway tetap dijalankan (menyegarkan di latar belakang),
        #   - penyajian dari cache ditandai degraded=True (jujur ke user).
        # Tanpa ini, satu baris cache lama bisa disajikan seolah sehat selama TTL.
        _state.update({"cache_age_s": max(0.0, time.time() - sb["ts"])})
        return {"ts": 0.0, "models": sb["models"]}
    try:
        with open(CACHE_PATH, encoding="utf-8") as fh:
            d = json.load(fh)
        if isinstance(d, dict) and isinstance(d.get("models"), list):
            return {"ts": float(d.get("ts") or 0.0), "models": d["models"]}
    except FileNotFoundError:
        pass
    except Exception as exc:  # noqa: BLE001 - cache rusak -> abaikan
        log.warning("Cache roster tidak terbaca (%s).", exc)
    return {"ts": 0.0, "models": []}


def _save_cache(ts: float, models: list[dict]) -> None:
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as fh:
            json.dump({"ts": ts, "models": models}, fh, indent=1)
    except Exception as exc:  # noqa: BLE001 - cache opsional
        log.warning("Cache roster gagal ditulis (%s).", exc)
    if models:
        _save_cache_supabase(ts, models)


def roster_health() -> dict:
    """Dari mana roster terakhir berasal (untuk flag `degraded` di /models)."""
    source = _state.get("source") or "unknown"
    reason = _state.get("reason") or ""
    age = _state.get("cache_age_s")
    degraded = source in ("cache", "empty")
    if source == "not_configured":
        degraded = False   # gateway memang tidak dipakai: bukan degradasi
    return {"source": source, "degraded": degraded, "reason": reason,
            "cache_age_seconds": round(age, 1) if isinstance(age, (int, float)) else None}


_refreshing = threading.Event()


def _refresh_async() -> None:
    """Segarkan roster di latar belakang (maksimal satu thread sekaligus)."""
    if _refreshing.is_set():
        return
    _refreshing.set()

    def _job() -> None:
        try:
            probe_roster(force=True, blocking=True)
        except Exception as exc:  # noqa: BLE001 - latar belakang
            log.warning("Segarkan roster gagal: %s", exc)
        finally:
            _refreshing.clear()

    threading.Thread(target=_job, name="gw-roster-refresh", daemon=True).start()


def cached_roster(ttl: float | None = None) -> list[dict]:
    """Roster dari CACHE saja — tidak pernah memicu probe/HTTP.

    Dipakai warm-up startup: pemanggil ingin tahu "apakah cache sudah segar?"
    tanpa efek samping memblokir. `ttl=None` = abaikan umur cache.
    Mengembalikan [] bila cache kosong atau lebih tua dari `ttl` detik.
    """
    global _cache
    if not _cache["models"]:
        _cache = _load_cache()
    if not _cache["models"]:
        return []
    if ttl is not None and (time.time() - _cache["ts"]) >= ttl:
        return []
    return list(_cache["models"])


def probe_roster(force: bool = False, blocking: bool = False) -> list[dict]:
    """Probe empiris seluruh kandidat; hasil PASS di-cache selama TTL.

    Tanpa `force`, fungsi ini TIDAK pernah menahan request frontend:
    - cache masih segar  -> kembalikan cache.
    - cache kedaluwarsa  -> kembalikan cache lama sambil menyegarkan di
                            latar belakang (thread daemon).
    - belum ada cache    -> probe sinkron (sekali saja) karena tidak ada
                            apa pun untuk disajikan.
    """
    global _cache
    url, key = gateway_config()
    if not url:
        # Gateway memang tidak dikonfigurasi: Gemini-only itu SAH, bukan degradasi.
        _state.update({"source": "not_configured",
                       "reason": "LLM_GATEWAY_URL tidak di-set",
                       "ts": time.time(), "cache_age_s": None})
        return []
    now = time.time()
    if not _cache["models"]:
        _cache = _load_cache()
    if _cache["models"] and (now - _cache["ts"]) < CACHE_TTL_S and not force:
        # Cache masih dalam TTL = data gateway yang belum kedaluwarsa: BUKAN degradasi.
        _state.update({"source": "gateway", "reason": "", "ts": now,
                       "cache_age_s": max(0.0, now - _cache["ts"])})
        return list(_cache["models"])
    if _cache["models"] and not blocking:
        # Sajikan cache sambil menyegarkan di latar belakang. Datanya mungkin
        # BASI -> tandai degraded supaya tidak lagi diam-diam (keluhan user).
        _state.update({"source": "cache", "reason": "cache_stale_refresh_async",
                       "ts": now, "cache_age_s": max(0.0, now - _cache["ts"])})
        _refresh_async()
        return list(_cache["models"])

    with httpx.Client(timeout=PROBE_TIMEOUT_S) as client:
        cands = _list_candidates(client, url, key)
        if not cands:
            # Gagal ambil kandidat (setelah retry): pakai cache apa pun, sekalipun
            # basi — lebih baik daripada kehilangan seluruh daftar provider.
            if _cache["models"]:
                _state.update({"source": "cache",
                               "reason": _state.get("reason") or "list_models_failed",
                               "ts": now, "cache_age_s": max(0.0, now - _cache["ts"])})
                return list(_cache["models"])
            _state.update({"source": "empty",
                           "reason": _state.get("reason") or "no_cache",
                           "ts": now, "cache_age_s": None})
            return []
        nonce = str(int(now))
        passed: list[dict] = []
        with cf.ThreadPoolExecutor(max_workers=PROBE_WORKERS) as ex:
            futs = [ex.submit(_probe_one, client, url, key, c, nonce, i)
                    for i, c in enumerate(cands)]
            for f in cf.as_completed(futs):
                try:
                    rec = f.result()
                except Exception as exc:  # noqa: BLE001
                    log.warning("Probe gagal: %s", exc)
                    continue
                if rec["status"] != "PASS":
                    continue
                # Gate 2: provider asli (hasil X-Routed-Via) baru diketahui di
                # sini. Model paid-only yang lolos probe 64-token (mis.
                # gemini-*pro*) DAN model di luar allowlist free-tier dibuang
                # sebelum pernah sampai ke frontend.
                if is_paid_only(rec["model"], rec.get("provider", "")):
                    log.info("SKIP paid-only %s (%s)", rec["model"], rec["provider"])
                    continue
                passed.append(rec)
                log.info("PASS %s (%s, %dms)", rec["model"],
                         rec["provider"], rec["ms"])

    passed.sort(key=lambda r: (r["provider"], r["model"]))
    passed = passed[:MAX_ROSTER]
    log.info("Roster gateway: %d/%d kandidat PASS (TTL %ds).",
             len(passed), len(cands), CACHE_TTL_S)
    _cache = {"ts": now, "models": passed}
    _save_cache(now, passed)
    if passed:
        _state.update({"source": "gateway", "reason": "", "ts": now, "cache_age_s": 0.0})
    else:
        # Semua kandidat gagal probe: roster kosong -> pemanggil akan memakai
        # fallback, dan itu HARUS terlihat sebagai degraded (bukan senyap).
        _state.update({"source": "empty", "reason": "probe_all_failed",
                       "ts": now, "cache_age_s": None})
    return list(passed)


def gw_models(force: bool = False, blocking: bool = False) -> list[str]:
    """ID model yang lolos probe (urutan stabil: provider, lalu id)."""
    return [r["model"] for r in probe_roster(force=force, blocking=blocking)]


def roster_catalog(force: bool = False, blocking: bool = False) -> list[dict]:
    """Bentuk katalog UI: {id,name,provider,tier,hint} — siap kirim frontend."""
    out = []
    for r in probe_roster(force=force, blocking=blocking):
        name = r["model"].split("/")[-1].replace("-", " ").replace("_", " ").title()
        out.append({
            "id": r["model"],
            "name": name,
            "provider": f"Gateway · {r['provider']}",
            "tier": "free",
            "hint": f"{r.get('ms') or 0}ms",
        })
    return out
