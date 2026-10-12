"""gemini_llm.py - Jalur LLM GEMINI-FIRST (migrasi gateway -> Gemini, Okt 2026).

Mengapa modul ini ada
---------------------
Gateway lama (`nexus-gateway-vps.tail7f0d5a.ts.net`) terbukti TIDAK LAYAK untuk
beban produksi: burst -> HTTP 500 massal, seri berkepanjangan -> menggantung,
dan hanya `qwen/qwen3.8-27b` yang benar-benar mendiskriminasi (`allam-2-7b`
memberi skor 1.0 untuk kasus BENAR maupun SALAH = cap karet). Keputusan FASE 1:
**Opsi A - rotasi kunci langsung ke Gemini** (`gemini-api-rotator` 2.0.0 dipasang
sebagai referensi; mesin rotasi runtime memakai `gemini_key_pool.KeyPool` yang
sudah teruji terhadap payload 429 ASLI proyek ini).

Bukti empiris yang mengunci desain (semua diukur 2026-10-12, lihat
`tests/_gem_keys_report.json` + `tests/_gem_matrix.json`):
  * 13 kunci unik; 10/13 melayani generasi pada percobaan pertama, 1 kena 429,
    2 kena 503 sementara. Kunci #1 kena 429 pada model X sementara kunci #2
    SUKSES pada model X detik berikutnya -> kunci berada di PROJECT berbeda,
    jadi rotasi benar-benar menambah kapasitas (bukan mengganti nama slot).
  * `gemini-2.5-flash` & `gemini-2.5-flash-lite` kini 404
    "no longer available to new users" untuk sebagian project -> tetap ada di
    rantai utama (project lama masih boleh) tetapi TIDAK boleh jadi andalan.
  * `thinking_config` bersifat PER MODEL:
      - `thinking_budget=0` diterima 3.8/3.7/3.6/3.5-flash, 2.5-flash(-lite),
        3.1-flash-lite; DITOLAK (400) oleh `gemini-3.5-flash-lite` & semua
        `gemma-*`.
      - tanpa `thinking_config`, model thinking membakar anggaran token untuk
        berpikir -> konten KOSONG (terukur pada 3.6-flash & 3.5-flash).
    Maka konfigurasi berpikir harus (a) sadar-model, dan (b) punya jaring
    pengaman: 400 INVALID_ARGUMENT -> ulangi TANPA blok berpikir.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field, asdict

import gemini_key_pool as gkp

log = logging.getLogger("gemini_llm")

# --------------------------------------------------------------------------
# Rantai model
# --------------------------------------------------------------------------
# Rantai UTAMA = daftar yang diwajibkan brief (urutan dipertahankan apa adanya).
MODEL_CHAIN: list[str] = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemma-4-31b-it",
]

# Cadangan TERVERIFIKASI-HIDUP (matriks FASE 2.1b) - dipakai setelah rantai
# utama habis. Ini yang menyelamatkan permintaan saat 2.5-* kena 404
# entitlement atau 3.8-flash sedang 503.
MODEL_CHAIN_RESERVE: list[str] = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemma-4-26b-a4b-it",
]

FULL_CHAIN: list[str] = MODEL_CHAIN + MODEL_CHAIN_RESERVE

# Model yang MENOLAK `thinking_budget` tetapi MENERIMA `thinking_level`.
THINKING_LEVEL_ONLY = {"gemini-3.5-flash-lite", "gemini-3.7-flash"}
# Model yang menolak SELURUH blok berpikir (400) -> konfigurasi dihilangkan.
NO_THINKING = {"gemma-4-31b-it", "gemma-4-26b-a4b-it"}

# Pemetaan tingkat berpikir -> anggaran token. `-1` = biarkan model memutuskan.
THINKING_BUDGET: dict[str, int] = {
    "minimal": 0,
    "low": 512,
    "medium": 4096,
    "high": 16384,
    "dynamic": -1,
}


# --------------------------------------------------------------------------
# Konfigurasi rotator (nilai WAJIB dari brief; default paket berbeda)
# --------------------------------------------------------------------------
@dataclass
class RotatorConfig:
    """Parameter rotasi. Nilai default = yang diwajibkan brief.

    Catatan: default paket `gemini-api-rotator` 2.0.0 adalah
    rpm=15, concurrent=5, retries=3, delay=0.5 - brief meminta nilai yang LEBIH
    KONSERVATIF karena kuota nyata proyek ini hanya 5 RPM/model/project
    (`quotaId=GenerateRequestsPerMinutePerProjectPerModel-FreeTier`).
    """

    rpm_per_key: int = 10
    cooldown_base_seconds: float = 60.0
    cooldown_max_seconds: float = 1800.0
    max_concurrent_per_key: int = 3
    max_retries: int = 4
    retry_delay_seconds: float = 1.0

    def backoff(self, attempt: int) -> float:
        """Backoff eksponensial dengan cap `cooldown_max_seconds`."""
        return min(self.retry_delay_seconds * (2 ** max(0, attempt)), 30.0)


CONFIG = RotatorConfig()


def ensure_env() -> int:
    """Pastikan `.env` sudah masuk `os.environ`; bangun ulang pool bila perlu.

    Kenapa perlu: `judge_harness.load_env()` mengembalikan DICT tanpa menulis ke
    `os.environ`, sedangkan `gemini_key_pool.discover_keys()` membaca
    `os.environ`. Akibatnya skrip mandiri (mis. `tests/brief7_toolbench.py`)
    melihat pool KOSONG walau `.env` berisi 13 kunci ("TIDAK ADA KUNCI GEMINI").
    Pemuatan sebenarnya kini ada di `gemini_key_pool.load_env_file()` (lapisan
    pool, self-healing); fungsi ini tinggal membangun ulang pool global supaya
    kunci yang baru terlihat langsung dipakai.

    Returns: jumlah kunci unik yang terlihat setelah bootstrap.
    """
    gkp.load_env_file()
    gkp.reset()
    return gkp.pool().size

# Pelindung laju per kunci (RPM) - di luar cooldown 429, murni proaktif.
_rate_lock = threading.Lock()
_rate_hist: dict[str, list[float]] = {}


def _rpm_ok(fp: str, model: str = "", cfg: RotatorConfig = CONFIG) -> bool:
    """True bila `(kunci, model)` masih di bawah `rpm_per_key` per 60 detik.

    Kunci bucket per (KUNCI, MODEL) - bukan per kunci saja - karena kuota
    Google memang bercakupan PER (PROJECT, MODEL)
    (`quotaId=GenerateRequestsPerMinutePerProjectPerModel-FreeTier`). Bucket
    per-kunci akan membatasi 10x lebih ketat dari kenyataan.
    """
    now = time.time()
    bucket = f"{fp}|{model}"
    with _rate_lock:
        hist = [t for t in _rate_hist.get(bucket, []) if now - t < 60.0]
        _rate_hist[bucket] = hist
        return len(hist) < cfg.rpm_per_key


def _rpm_note(fp: str, model: str = "") -> None:
    with _rate_lock:
        _rate_hist.setdefault(f"{fp}|{model}", []).append(time.time())


def _rpm_retry_after(fp: str, model: str = "", cfg: RotatorConfig = CONFIG) -> float:
    """Detik sampai bucket `(kunci, model)` punya ruang lagi (0.0 bila sudah).

    KENAPA INI PENTING (bug nyata, terukur 2026-10-12): versi pertama memakai
    `pool.mark(..., kind="rate_limited", ttl=cfg.cooldown_base_seconds)` di jalur
    `rpm_precheck`. `mark()` menaruh `rate_limited` ke `pool._cool[fp]` =
    **membekukan SELURUH KUNCI 60 detik**. Karena precheck ini murni proaktif
    (belum ada 429 dari Google), burst >= 32 menembak >10 permintaan/(kunci,model)
    per menit -> 13 kunci terbekukan dalam hitungan detik -> `acquire()`
    mengembalikan `None` untuk SEMUA model -> `no_key_available` beruntun sampai
    deadline habis. Terlihat di `tests/_gemini_hard_results.json`: C8 7/32,
    C9 0/64, C10 0/100 dengan `sample_fail` penuh `no_key_available` +
    `rpm_precheck` - dan TIDAK ADA satu pun 429 asli. Jadi itu lockout buatan
    sendiri, bukan tembok kuota Google.

    Perbaikan: (a) pembekuan di-scope ke PASANGAN (kunci, model) - sesuai cakupan
    kuota Google yang memang per (project, model) - dan (b) TTL-nya PRESISI
    (sampai entri tertua keluar dari jendela 60 s), bukan 60 s buta.
    """
    now = time.time()
    with _rate_lock:
        hist = [t for t in _rate_hist.get(f"{fp}|{model}", []) if now - t < 60.0]
        if len(hist) < cfg.rpm_per_key:
            return 0.0
        # Berapa entri harus gugur supaya ada 1 slot bebas.
        drop = len(hist) - cfg.rpm_per_key + 1
        return max(0.5, (hist[drop - 1] + 60.0) - now)


# --------------------------------------------------------------------------
# Konfigurasi berpikir (sadar-model + jaring pengaman)
# --------------------------------------------------------------------------
def thinking_config_for(model: str, level: str):
    """Kembalikan `ThinkingConfig` yang tepat untuk `model`, atau None.

    `None` berarti blok berpikir HARUS dihilangkan (model menolaknya).
    """
    from google.genai import types

    # Sentinel: buang blok berpikir sepenuhnya (dipakai jaring pengaman 400).
    if level in (None, "__none__") or model in NO_THINKING:
        return None
    lvl = (level or "low").lower()
    if model in THINKING_LEVEL_ONLY:
        # Hanya menerima `thinking_level`, bukan `thinking_budget`.
        allowed = {"minimal", "low", "medium", "high"}
        return types.ThinkingConfig(thinking_level=lvl if lvl in allowed else "low")
    budget = THINKING_BUDGET.get(lvl, THINKING_BUDGET["low"])
    return types.ThinkingConfig(thinking_budget=budget)


def build_config(model: str, *, level: str = "low", temperature: float = 0.1,
                 system_instruction: str | None = None, tools=None,
                 max_output_tokens: int | None = None):
    """`GenerateContentConfig` untuk `model` (blok berpikir sadar-model)."""
    from google.genai import types

    kw: dict = {"temperature": temperature}
    if system_instruction:
        kw["system_instruction"] = system_instruction
    if tools:
        kw["tools"] = tools
        kw["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)
    if max_output_tokens:
        kw["max_output_tokens"] = max_output_tokens
    tc = thinking_config_for(model, level)
    if tc is not None:
        kw["thinking_config"] = tc
    return types.GenerateContentConfig(**kw)


def _looks_like_thinking_reject(exc) -> bool:
    t = str(exc).lower()
    return ("invalid_argument" in t or "400" in t) and (
        "thinking" in t or "budget" in t or "invalid argument" in t)


# --------------------------------------------------------------------------
# Inti: panggilan chat dengan rotasi kunci + fallback rantai model
# --------------------------------------------------------------------------
def chat_with_fallback(
    prompt: str,
    *,
    model_chain: list[str] | None = None,
    level: str = "low",
    temperature: float = 0.1,
    system_instruction: str | None = None,
    tools=None,
    max_output_tokens: int | None = None,
    cfg: RotatorConfig | None = None,
    deadline_s: float | None = None,
) -> dict:
    """Kirim `prompt` ke Gemini; rotasi kunci + jatuh ke model berikutnya.

    STRATEGI LATENSI (diukur, bukan tebakan): percobaan pertama modul ini
    menghabiskan **123 s** untuk satu prompt karena mengulang KUNCI YANG SAMA
    4x dengan `sleep` (1+2+4+8 s) setiap kali 503 sebelum berpindah kunci.
    Dengan 13 kunci, ROTASI jauh lebih murah daripada menunggu: setiap
    (model, kunci) dicoba SEKALI, lalu lanjut. `max_retries` hanya menentukan
    berapa SAPUAN penuh (sweep) yang boleh dilakukan, dan setiap sapuan dibatasi
    `deadline_s` (default 45 s = anggaran `/chat`).

    Mengembalikan dict (tidak pernah melempar selama masih ada kandidat):
        {ok, text, model, key, attempts[], elapsed_s, error}
    """
    cfg = cfg or CONFIG
    pool = gkp.pool()
    if not pool.size:
        # Self-healing: `.env` ada tetapi belum masuk `os.environ` (lihat
        # `ensure_env`) -> muat lalu bangun ulang pool.
        ensure_env()
        pool = gkp.pool()
    chain = model_chain or MODEL_CHAIN
    attempts: list[dict] = []
    t0 = time.time()
    budget = deadline_s if deadline_s is not None else float(
        os.getenv("GEMINI_LLM_BUDGET_S", "45"))
    deadline = t0 + budget

    if not pool.size:
        return {"ok": False, "text": "", "function_calls": [], "model": None, "key": None,
                "attempts": [], "elapsed_s": 0.0,
                "error": "pool kosong: tidak ada GEMINI_KEY_* di env"}

    def _left() -> float:
        return deadline - time.time()

    def _try(model: str, fp: str, lvl: str):
        """Satu percobaan. -> (text, function_calls).

        PENTING: balasan tool-calling SAH tidak punya teks (`response.text`
        kosong) - hanya `function_calls`. Versi awal fungsi ini hanya membaca
        `text`, sehingga jawaban function-call dianggap "konten kosong" lalu
        membuang model yang sebenarnya BERHASIL (tertangkap di E2E A4).
        """
        client = pool.client(fp)
        _rpm_note(fp, model)
        resp = client.models.generate_content(
            model=model, contents=prompt,
            config=build_config(model, level=lvl, temperature=temperature,
                                system_instruction=system_instruction, tools=tools,
                                max_output_tokens=max_output_tokens))
        return ((getattr(resp, "text", None) or "").strip(),
                list(getattr(resp, "function_calls", None) or []))

    def _pack(model: str, fp: str, text: str, fcs: list, kind: str) -> dict:
        return {"ok": True, "text": text, "model": model, "key": pool.label(fp),
                "function_calls": [getattr(fc, "name", None) for fc in fcs],
                "attempts": attempts + [{"model": model, "key": pool.label(fp),
                                         "kind": kind}],
                "elapsed_s": round(time.time() - t0, 2), "error": None}

    for sweep in range(max(1, cfg.max_retries)):
        got_any = False
        for model in chain:
            if _left() <= 1.0:
                attempts.append({"model": model, "kind": "deadline"})
                break
            tried: set[str] = set()
            while True:
                if _left() <= 1.0:
                    break
                acq = pool.acquire(model)
                if acq is None:
                    attempts.append({"model": model, "kind": "no_key_available"})
                    break
                fp, _key = acq
                if fp in tried:
                    break  # semua kunci siap untuk model ini sudah dicoba
                tried.add(fp)
                got_any = True
                if not _rpm_ok(fp, model, cfg):
                    # Guard proaktif: JANGAN bekukan seluruh kunci (lihat
                    # `_rpm_retry_after`). Bekukan HANYA pasangan (kunci, model)
                    # selama tepat waktu tunggu yang dibutuhkan -> model lain pada
                    # kunci yang sama tetap melayani, dan kunci kembali cepat.
                    wait = _rpm_retry_after(fp, model, cfg)
                    attempts.append({"model": model, "key": pool.label(fp),
                                     "kind": "rpm_precheck",
                                     "retry_in_s": round(wait, 1)})
                    pool.mark(fp, model, kind="rate_limited_pair",
                              ttl=max(0.5, wait))
                    continue
                try:
                    text, fcs = _try(model, fp, level)
                    if text or fcs:
                        return _pack(model, fp, text, fcs, "ok")
                    attempts.append({"model": model, "key": pool.label(fp),
                                     "kind": "empty_content"})
                    break
                except Exception as exc:  # noqa: BLE001
                    kind, ttl = gkp.classify_error(exc)
                    # Jaring pengaman: 400 karena blok berpikir -> ulangi sekali
                    # TANPA blok berpikir (bukan masalah kuota).
                    if kind == "unknown" and _looks_like_thinking_reject(exc):
                        try:
                            text, fcs = _try(model, fp, "__none__")
                            if text or fcs:
                                return _pack(model, fp, text, fcs, "ok_no_thinking")
                        except Exception as exc2:  # noqa: BLE001
                            kind, ttl = gkp.classify_error(exc2)
                            exc = exc2
                    attempts.append({"model": model, "key": pool.label(fp),
                                     "kind": kind, "err": str(exc)[:180]})
                    if kind in ("rate_limited", "key_dead", "entitlement",
                                "overloaded"):
                        pool.mark(fp, model, kind=kind, ttl=ttl)
                    # SELALU rotasi kunci/model berikutnya (tanpa sleep) -
                    # menunggu kunci yang sedang dihukum hanya membuang anggaran.
                    break
        if _left() <= 2.0:
            break
        # Hitung lama tidur dari KEADAAN POOL, bukan tebakan. Tiga sumber, ambil
        # yang paling relevan: (1) tidak ada kandidat sama sekali -> tunggu
        # pasangan bebas terdekat; (2) hanya tertahan guard RPM proaktif ->
        # tunggu penahanan TERPENDEK; (3) sisanya -> backoff eksponensial.
        if not got_any:
            pool_wait = pool.next_ready_in(chain)
            nap = min(pool_wait, cfg.cooldown_base_seconds) if pool_wait else \
                min(cfg.cooldown_base_seconds, max(0.0, _left() - 1.0), 20.0)
        else:
            waits = [a["retry_in_s"] for a in attempts[-60:]
                     if a.get("kind") == "rpm_precheck" and a.get("retry_in_s")]
            nap = min(waits) if waits else cfg.backoff(sweep)
        nap = min(max(0.5, nap), max(0.0, _left() - 1.0), 20.0)
        if nap <= 0.5:
            break
        attempts.append({"kind": "wait_before_sweep", "nap_s": round(nap, 1)})
        time.sleep(nap)

    return {"ok": False, "text": "", "function_calls": [], "model": None, "key": None,
            "attempts": attempts, "elapsed_s": round(time.time() - t0, 2),
            "error": "semua model & kunci pada rantai gagal"}


# --------------------------------------------------------------------------
# Kesehatan kunci (FASE 4)
# --------------------------------------------------------------------------
def health_check(deep: bool = False, *, model: str = "gemini-3.5-flash-lite") -> dict:
    """Status kesehatan pool kunci Gemini.

    `deep=False` (murah, tanpa I/O): hitung kunci siap dari state cooldown.
    `deep=True`: probe SETIAP kunci dengan satu panggilan nyata (biaya kuota).

    Struktur: {healthy, total, cooling, blocked_pairs, threshold, alert, keys[]}
    """
    pool = gkp.pool()
    if not pool.size:
        ensure_env()
        pool = gkp.pool()
    now = time.time()
    with pool._lock:  # noqa: SLF001 - introspeksi status, hanya baca
        entries = list(pool._entries)
        cool = dict(pool._cool)
        blocked = dict(pool._blocked)
    rows = []
    for name, _key, fp in entries:
        cooling_until = cool.get(fp, 0.0)
        if cooling_until > now:
            state = "cooling"
        else:
            # Kuota bercakupan (kunci, model), jadi kunci hanya benar-benar
            # "tidak sehat" bila SELURUH rantai model terblokir untuknya -
            # bukan saat satu model kena 429. Tanpa ini, `/health/llm` akan
            # selalu melaporkan 13/13 walau pool sedang tersendat total.
            usable = [m for m in MODEL_CHAIN if blocked.get((fp, m), 0.0) <= now]
            state = "active" if usable else "throttled"
        rows.append({
            "name": name,
            "fp": fp,
            "state": state,
            "cooldown_remaining_s": round(max(0.0, cooling_until - now), 1),
        })

    if deep:
        for row in rows:
            if row["state"] == "cooling":
                row["probe"] = "skipped(cooling)"
                continue
            try:
                client = pool.client(row["fp"])
                r = client.models.generate_content(
                    model=model, contents="ping",
                    config=build_config(model, level="minimal",
                                        max_output_tokens=16))
                ok = bool((getattr(r, "text", None) or "").strip())
                row["probe"] = "ok" if ok else "empty"
                if not ok:
                    row["state"] = "degraded"
            except Exception as exc:  # noqa: BLE001
                kind, _ = gkp.classify_error(exc)
                row["probe"] = kind
                row["state"] = "failing"

    healthy = sum(1 for r in rows if r["state"] == "active")
    threshold = int(os.getenv("GEMINI_HEALTHY_MIN_KEYS", "3"))
    return {
        "healthy": healthy,
        "total": len(rows),
        "cooling": sum(1 for r in rows if r["state"] == "cooling"),
        "throttled": sum(1 for r in rows if r["state"] == "throttled"),
        "blocked_pairs": sum(1 for t in blocked.values() if t > now),
        "threshold": threshold,
        "alert": healthy < threshold,
        "deep": deep,
        "probe_model": model if deep else None,
        "chain": MODEL_CHAIN,
        "keys": rows,
    }


def healthy_count() -> int:
    """Jumlah kunci yang siap dipakai (dipakai pemicu alert)."""
    return health_check(deep=False)["healthy"]


# --------------------------------------------------------------------------
# Alert Telegram (FASE 4): healthy < threshold
# --------------------------------------------------------------------------
_alert_lock = threading.Lock()
_last_alert_at = 0.0
_ALERT_COOLDOWN_S = 900.0  # jangan spam: maksimal 1 alert / 15 menit


def maybe_alert_telegram(status: dict | None = None) -> dict:
    """Kirim peringatan Telegram bila kunci sehat < ambang. Anti-spam 15 menit."""
    global _last_alert_at
    status = status or health_check()
    if not status["alert"]:
        return {"sent": False, "reason": "healthy >= threshold"}
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_ADMIN_CHAT_ID") or "").strip()
    if not token or not chat:
        return {"sent": False, "reason": "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID kosong"}
    now = time.time()
    with _alert_lock:
        if now - _last_alert_at < _ALERT_COOLDOWN_S:
            return {"sent": False, "reason": "anti-spam cooldown"}
        _last_alert_at = now
    msg = (f"\u26a0\ufe0f Katalir LLM: kunci Gemini sehat tinggal "
           f"{status['healthy']}/{status['total']} (ambang {status['threshold']}).\n"
           f"cooling={status['cooling']} blocked_pairs={status['blocked_pairs']}")
    try:
        import httpx
        r = httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",
                       json={"chat_id": chat, "text": msg}, timeout=6.0)
        return {"sent": r.status_code == 200, "status_code": r.status_code}
    except Exception as exc:  # noqa: BLE001
        return {"sent": False, "reason": str(exc)[:160]}


if __name__ == "__main__":
    import sys
    deep = "--deep" in sys.argv
    print(json.dumps(health_check(deep=deep), indent=2, ensure_ascii=False))
