"""Self-healing: reflection + search-augmented retry untuk workflow failure.

KBbb: apa yang sebenarnya dicoba sebelum menyerah.

DESIGN YANG BERBEDA DARI DRAF AWAL, DAN SEBABNYA:
draft meng centralised seluruh keputusan ke LLM. Itu membuat dua hal
buruk: (1) tidak ada yang bisa diuji tanpa memanggil model, jadi
"retry sukses >30%" jadi klaim yang tidak bisa diverifikasi; (2) satu
hallucination LLM bisa membuat loop berjalan terus pada error yang
sebenarnya butuh intervensi manusia.

Di sini klasifikasi error DETERMINISTIK dulu (rules, cepat, bisa
diuji), lalu LLM hanya dipakai sebagai pengayaan opsional. Kalau LLM
tidak tersedia atau gagal, jalur ini tetap bekerja penuh pada rules.

Tiga aksi, dan hanya tiga:
  retry     - dicoba lagi dengan perubahan yang sempit dan spesifik
  credential- perlu user; retry sendiri tidak akan pernah berhasil
  abort     - tidak ada yang bisa dilakukan; berhenti dengan jujur

`MAX_ATTEMPTS` dihitung per node, bukan per eksekusi, supaya satu node
yang bandel tidak menyeret node lain ikut gagal.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Optional

__all__ = [
    "SelfHealingAgent",
    "HealingPlan",
    "Rule",
    "CATEGORIES",
    "classify_error",
    "MAX_ATTEMPTS",
    "RATE_LIMIT_DELAYS_MS",
    "TRANSIENT_DELAYS_MS",
]

# Batas maksimum per KATEGORI, bukan satu angka global. Versi lama memakai
# MAX_ATTEMPTS=3 untuk semua kategori, termasuk kategori yang paling layak
# dicoba berulang (network, 5xx, rate limit).
MAX_ATTEMPTS = 5

# Backoff eksponensial untuk rate limit. Indeks = attempt-1, di-clamp ke
# panjang daftar, jadi attempt 6+ tidak keluar dari rentang.
RATE_LIMIT_DELAYS_MS = (1000, 2000, 4000, 8000, 16000)

# Backoff untuk kategori transient (network / 5xx). Lebih pendek supaya
# 5 percobaan tidak memakan ~15 detik wall-clock.
TRANSIENT_DELAYS_MS = (0, 1000, 2000, 4000, 8000)


# ─── Kategori error + perilaku healingnya ───────────────────────────────────
# Tabel ini adalah satu-satunya sumber kebenaran soal "berapa kali dicoba"
# dan "kapan mencari di forum". Versi lama memakai satu MAX_ATTEMPTS global
# untuk semua jenis error; itu terlalu kecil untuk kategori yang
# bisa saja pulih sendiri (network, 5xx, rate limit).
#
# credential  -> 0 percobaan. Butuh manusia; retry dijamin gagal.
# network/5xx -> 5 percobaan, backoff pendek, cari forum tiap percobaan.
# rate_limit  -> 5 percobaan, backoff eksponensial agresif.
# unknown     -> 2 percobaan. Dulu abort seketika; sekarang dicoba dulu
#                karena sebagian error tak dikenal memang transien, tapi
#                tetap pendek supaya bug asli tidak tertutup terlalu lama.
@dataclass(frozen=True)
class Rule:
    name: str
    pattern: "re.Pattern | None"
    action: str
    provider: str = ""
    max_attempts: int = 0
    search: bool = False
    # Kunci koreksi yang dibaca executor. Sengaja sempit: tidak menebak
    # parameter yang tidak ada di error.
    fix: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


# Urutan itu penting: pola yang lebih spesifik diperiksa lebih dulu.
# `credential` berada di depan `rate_limit` karena beberapa penyedia
# membalas "429 quota exceeded" yang sebenarnya soal kuota akun, bukan
# rate limit sesaat -- keduanya tidak boleh tertukar.
RULES: tuple[Rule, ...] = (
    # ── Placeholder tak teresolusi (adversarial BUG-3) ────────────────────
    # Error deterministik dari execution_engine.PlaceholderResolutionError:
    # payload identik tidak akan pernah valid - retry hanya membakar kuota
    # LLM user, jadi langsung abort tanpa pencarian forum.
    Rule(
        "placeholder_invalid",
        re.compile(r"PlaceholderResolutionError"),
        "abort", max_attempts=0, search=False,
        reason="Referensi {{...}} tidak dapat diresolv; mengulang dengan "
               "payload sama tidak akan mengubah hasil - perbaiki config node.",
    ),
    # ── Credential: escalate, tidak pernah retry ─────────────────────────
    Rule(
        "oauth_token_expired",
        re.compile(r"\b(401|invalid_grant|token[ _-]?expired|"
                   r"unauthorized|jwt[ _-]?expired|auth failed|"
                   r"could not refresh access token)\b", re.I),
        "credential", max_attempts=0, search=False,
        fix={"refresh_token": True},
        reason="Token autentikasi ditolak; retry tanpa refresh akan gagal lagi.",
    ),
    Rule(
        "credential_missing",
        re.compile(r"\b(403|forbidden|permission[ _-]?denied|"
                   r"missing[ _-]?(api[ _-]?key|credential|token))\b", re.I),
        "credential", max_attempts=0, search=False,
        reason="Akses ditolak oleh penyedia; butuh kredensial atau izin baru.",
    ),
    # ── Rate limit: backoff eksponensial ──────────────────────────────────
    Rule(
        "rate_limited",
        re.compile(r"\b(429|rate[ _-]?limit|too many requests|"
                   r"quota exceeded|resource[ _-]?exhausted)\b", re.I),
        "retry", max_attempts=5, search=True,
        fix={"backoff_seconds": 1},
        reason="Penyedia meminta perlambatan; retry dengan backoff eksponensial.",
    ),
    # ── Transient: 5xx ────────────────────────────────────────────────────
    Rule(
        "server_5xx",
        re.compile(r"\b(500|502|503|504|bad gateway|"
                   r"service unavailable|gateway timeout|"
                   r"internal server error|server error)\b", re.I),
        "retry", max_attempts=5, search=True,
        fix={"backoff_seconds": 1},
        reason="Kegagalan sisi server, umumnya sementara.",
    ),
    # ── Transient: jaringan ───────────────────────────────────────────────
    Rule(
        "network",
        re.compile(r"\b(ETIMEDOUT|ECONNRESET|ECONNREFUSED|EAI_AGAIN|"
                   r"connect(ion)? (reset|refused|timed? ?out)|"
                   r"timeout|temporary failure in name resolution|"
                   r"\bdns\b|\bssl\b|network|"
                   # Nama exception httpx/requests berbentuk CamelCase
                   # (ConnectTimeout, ReadTimeout, ConnectError, ...). Tanpa
                   # alternatif ini, pesan `[RuntimeError] Permintaan HTTP
                   # gagal (ConnectTimeout).` TIDAK cocok `\btimeout\b` (tidak
                   # ada batas kata di dalam "ConnectTimeout") sehingga jatuh
                   # ke `unknown`: hanya 2 percobaan padahal jelas transien.
                   r"connect(?:timeout|error)|read(?:timeout|error)|"
                   r"write(?:timeout|error)|pooltimeout|"
                   r"remoteprotocolerror)\b", re.I),
        "retry", max_attempts=5, search=True,
        fix={"backoff_seconds": 1},
        reason="Masalah jaringan; sering pulih sendiri.",
    ),
    # ── Tidak akan pernah berhasil dengan payload yang sama ─────────────
    Rule(
        "not_found",
        re.compile(r"\b(404|not found|no such (host|table|column)|"
                   r"unknown (tool|node|field)|does not exist)\b", re.I),
        "abort", max_attempts=0, search=False,
        reason="Target tidak ada; mengulang tidak akan menemukannya.",
    ),
    Rule(
        "bad_request",
        re.compile(r"\b(400|422|validation|invalid (argument|parameter|request)|"
                   r"schema)\b", re.I),
        "abort", max_attempts=0, search=False,
        reason="Permintaan tidak valid; mengulang dengan payload sama tidak akan berhasil.",
    ),
    # ── Fallback: tidak dikenal pola mana pun ───────────────────────────
    # Dicoba DUA kali, lalu escalate dengan saran dari forum. Batasnya
    # pendek dengan sengaja: error yang tidak kita kenali bisa jadi bug
    # kita sendiri, dan menutupinya dengan retry terlalu lama membuat
    # penyebab aslinya tidak terlihat.
    Rule(
        "unknown", None, "retry",
        max_attempts=2, search=True,
        reason="Error tidak dikenali; mencoba singkat sebelum menyerah.",
    ),
)

# Peta kategori -> batas, dipakai oleh `handle_failure` tanpa harus tahu
# nama rule. Diisi ulang dari RULES supaya ada satu sumber kebenaran.
CATEGORIES: dict[str, int] = {
    "credential": 0, "rate_limit": 5, "api_5xx": 5,
    "network": 5, "unknown": 2,
}


def classify_error(message: str) -> Optional[Rule]:
    """Kembalikan rule pertama yang cocok; selalu mengembalikan rule.

    Tidak pernah None lagi. Versi lama mengembalikan None untuk error tak
    dikenal dan memperlakukannya sebagai abort seketika; sekarang error
    tak dikenal jatuh ke rule `unknown` dengan batas 2 percobaan.
    """
    text = message or ""
    for r in RULES:
        if r.pattern is None:      # sentinel `unknown`, selalu terakhir
            continue
        if r.pattern.search(text):
            return r
    return RULES[-1]


@dataclass
class HealingPlan:
    """Rencana hasil satu percobaan healing.

    `action` hanya mungkin empat nilai:
      retry      - coba lagi dengan `delay_ms`/`changes`
      credential - perlu kredensial baru; escalate ke user
      abort      - mustahil berhasil dengan payload yang sama
      escalate   - sudah kehabisan percobaan; bawa `suggestions`
    """
    action: str
    node_id: str
    attempt: int
    category: str = "unknown"
    reason: str = ""
    changes: dict[str, Any] = field(default_factory=dict)
    provider: str = ""
    delay_ms: int = 0
    max_attempts: int = 0
    # Riwayat diagnosis disimpan di step output supaya report ke user
    # bisa menunjukkan APA yang dicoba -- bukan cuma "gagal".
    trace: list[dict[str, Any]] = field(default_factory=list)
    search_hits: int = 0
    suggestions: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action, "node_id": self.node_id, "attempt": self.attempt,
            "category": self.category, "reason": self.reason, "changes": self.changes,
            "provider": self.provider, "delay_ms": self.delay_ms,
            "max_attempts": self.max_attempts, "trace": self.trace,
            "search_hits": self.search_hits, "suggestions": self.suggestions,
        }


def _error_message(error: Any) -> str:
    """Ratakan error apa pun jadi string yang bisa di-pattern-match."""
    if isinstance(error, str):
        return error
    if isinstance(error, dict):
        parts = [str(error[k]) for k in ("type", "status", "code", "message", "detail", "error")
                 if error.get(k) is not None]
        if parts:
            return " ".join(parts)
    return str(error)


# Provider yang sering muncul di pesan error, supaya escalate punya
# sesuatu yang konkret untuk ditampilkan ("hubungkan ulang Gmail").
_PROVIDER_HINTS = (
    ("gmail", "gmail"), ("google.sheet", "google_sheets"), ("sheets", "google_sheets"),
    ("slack", "slack"), ("notion", "notion"), ("stripe", "stripe"),
    ("discord", "discord"), ("telegram", "telegram"), ("openai", "openai"),
    ("anthropic", "anthropic"), ("gemini", "gemini"), ("github", "github"),
    ("supabase", "supabase"), ("vercel", "vercel"), ("cloudflare", "cloudflare"),
    ("linear", "linear"),
)


def _detect_provider(error: Any) -> str:
    msg = _error_message(error).casefold()
    for needle, provider in _PROVIDER_HINTS:
        if needle in msg:
            return provider
    return ""


class SelfHealingAgent:
    """Reflection + search-retry, dengan batas per kategori error.

    Yang berubah dari versi konservatif, dan alasannya:
      * batas global 3 -> batas per kategori. Network/5xx/rate-limit
        memang bisa pulih sendiri; 3 percobaan terlalu sedikit.
      * pencarian forum hanya dari attempt ke-2 -> SETIAP percobaan
        untuk kategori non-credential. Kalau ternyata perlu intervensi
        manusia, saran forum sudah tersedia sejak percobaan pertama.
      * error tak dikenal: abort seketika -> 2 percobaan lalu escalate.
        Pelonggaran yang disengaja; batasnya pendek supaya bug asli
        tidak tertutup terlalu lama.
      * aksi `credential` -> `escalate` dengan `provider` dan saran,
        biar UI bisa menampilkan "hubungkan ulang", bukan teks pasif.

    Yang TIDAK berubah: credential tidak pernah di-retry. Retry dengan
    token kedaluwarsa dijamin gagal dan hanya membakar kuota user.
    """

    def __init__(self, *, search_enabled: bool = True, llm_reflect=None,
                 http_timeout: float = 8.0):
        self.search_enabled = search_enabled
        self.llm_reflect = llm_reflect
        self.http_timeout = http_timeout

    async def handle_failure(self, *, node_id: str, error: Any,
                             attempt: int = 1) -> HealingPlan:
        message = _error_message(error)
        rule = classify_error(message)
        trace: list[dict[str, Any]] = [
            {"step": "classify", "matched": rule.name, "action": rule.action,
             "max_attempts": rule.max_attempts}
        ]

        # Reflection opsional. Gagal TIDAK boleh menggagalkan healing.
        if self.llm_reflect is not None:
            try:
                ref = await self.llm_reflect(message, attempt)
                if ref:
                    trace.append({"step": "reflection", "text": str(ref)[:500]})
            except Exception as exc:  # noqa: BLE001
                trace.append({"step": "reflect", "error": str(exc), "impact": "ignored"})

        # Credential: escalate sekarang, tanpa retry.
        if rule.action == "credential":
            return HealingPlan(
                action="escalate", node_id=node_id, attempt=attempt, category=rule.name,
                reason=rule.reason, provider=_detect_provider(error) or rule.provider,
                changes=rule.fix, max_attempts=0,
                suggestions=[{"kind": "reconnect",
                              "text": "Hubungkan ulang kredensial, lalu jalankan ulang workflow."}],
                trace=trace,
            )

        # Mustahil berhasil dengan payload yang sama.
        if rule.action == "abort":
            return HealingPlan(
                action="abort", node_id=node_id, attempt=attempt, category=rule.name,
                reason=rule.reason, max_attempts=0,
                suggestions=[{"kind": "review",
                              "text": "Periksa konfigurasi node: permintaan ini tidak valid dan mengulang tidak akan mengubah hasil."}],
                trace=trace,
            )

        # Kehabisan percobaan -> escalate dengan saran dari forum.
        if attempt > rule.max_attempts:
            suggestions: list[dict[str, str]] = []
            hits = 0
            if self.search_enabled and rule.search:
                try:
                    found = await self.search_forum(message)
                    hits = len(found)
                    suggestions = [{"kind": f["source"], "text": str(f.get("title") or "")[:160],
                                    "link": str(f.get("link") or "")} for f in found]
                    trace.append({"step": "search", "hits": hits,
                                  "sources": sorted({f["source"] for f in found})})
                except Exception as exc:  # noqa: BLE001
                    trace.append({"step": "search", "error": str(exc), "impact": "ignored"})
            return HealingPlan(
                action="escalate", node_id=node_id, attempt=attempt, category=rule.name,
                reason=f"Gagal setelah {rule.max_attempts} percobaan ({rule.reason})",
                max_attempts=rule.max_attempts, search_hits=hits,
                suggestions=suggestions or [{"kind": "manual",
                                             "text": "Tidak ada saran otomatis; periksa log penyedia."}],
                trace=trace,
            )

        # Masih ada percobaan: cari forum, lalu retry.
        hits = 0
        suggestions = []
        if self.search_enabled and rule.search:
            try:
                found = await self.search_forum(message)
                hits = len(found)
                suggestions = [{"kind": f["source"], "text": str(f.get("title") or "")[:160],
                                "link": str(f.get("link") or "")} for f in found]
                trace.append({"step": "search", "hits": hits,
                              "sources": sorted({f["source"] for f in found})})
            except Exception as exc:  # noqa: BLE001
                trace.append({"step": "search", "error": str(exc), "impact": "ignored"})

        # Backoff. Rate limit eksponensial agresif; transient lebih pendek.
        table = RATE_LIMIT_DELAYS_MS if rule.name == "rate_limited" else TRANSIENT_DELAYS_MS
        delay = table[min(max(attempt - 1, 0), len(table) - 1)]

        return HealingPlan(
            action="retry", node_id=node_id, attempt=attempt, category=rule.name,
            reason=rule.reason, changes=rule.fix, delay_ms=delay,
            max_attempts=rule.max_attempts, search_hits=hits, suggestions=suggestions,
            trace=trace,
        )

    async def search_forum(self, message: str, *, per_source: int = 3) -> list[dict]:
        """Cari pola error yang sama di Stack Overflow + GitHub Issues.

        Fail-soft: kedua API publik dan bisa rate-limit atau mati, dan
        pencarian tidak boleh pernah jadi alasan workflow gagal. Semua
        error ditelan; pemanggil hanya melihat `[]`.
        """
        q = (message or "")[:120].strip()
        if not q:
            return []
        out: list[dict] = []
        try:
            import httpx
        except Exception:
            return []

        async with httpx.AsyncClient(timeout=self.http_timeout) as client:
            try:
                r = await client.get(
                    "https://api.stackexchange.com/2.3/search/advanced",
                    params={"order": "desc", "sort": "relevance", "q": q,
                            "site": "stackoverflow", "pagesize": per_source},
                )
                if r.status_code == 200:
                    for it in (r.json().get("items") or [])[:per_source]:
                        out.append({"source": "stackoverflow", "title": it.get("title"),
                                    "link": it.get("link")})
            except Exception:
                pass

            # GitHub Issues anonim: 10 req/menit. Tidak ada token di
            # lingkungan ini, jadi volumenya dijaga tetap kecil.
            try:
                r = await client.get(
                    "https://api.github.com/search/issues",
                    params={"q": q, "per_page": per_source},
                    headers={"Accept": "application/vnd.github+json"},
                )
                if r.status_code == 200:
                    for it in (r.json().get("items") or [])[:per_source]:
                        out.append({"source": "github", "title": it.get("title"),
                                    "link": it.get("html_url")})
            except Exception:
                pass
        return out


