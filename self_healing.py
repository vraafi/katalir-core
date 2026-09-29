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
    "classify_error",
    "MAX_ATTEMPTS",
]

MAX_ATTEMPTS = 3


# ─── Klasifikasi deterministik ──────────────────────────────────────────────
# Pola diuji terhadap pesan error nyata (401/403 OAuth, 429 rate limit,
# 5xx, DNS/timeout), bukan tebakan. Setiap pola punya `action` dan,
# kalau relevan, `provider` untuk credential.
@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern
    action: str
    provider: str = ""
    # Kunci koreksi yang nanti dibaca executor. Sengaja sempit:we don't
    # menebak-nebak parameter yang tidak ada di error.
    fix: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


RULES: tuple[Rule, ...] = (
    # ── Credential ──────────────────────────────────────────────────────
    # Token OAuth kedaluwarsa. Retry tanpa refresh PASTI gagal lagi, jadi
    # ini harus `credential`, bukan `retry` — inilah kasus yang jadi contoh
    # di brief (Gmail 401).
    Rule(
        "oauth_token_expired", re.compile(r"\b(401|invalid_grant|token[ _-]?expired|"
                                         r"unauthorized|jwt[ _-]?expired|"
                                         r"could not refresh access token)\b", re.I),
        "credential",
        fix={"refresh_token": True},
        reason="Token autentikasi ditolak; retry tanpa refresh akan gagal lagi.",
    ),
    Rule(
        "credential_missing", re.compile(r"\b(403|forbidden|permission[ _-]?denied|"
                                         r"missing[ _-]?(api[ _-]?key|credential|token)|"
                                         r"not[ _-]?authorized)\b", re.I),
        "credential",
        reason="Akses ditolak oleh penyedia; butuh kredensial atau izin baru.",
    ),
    # ── Retryable ───────────────────────────────────────────────────────
    Rule(
        "rate_limited", re.compile(r"\b(429|rate[ _-]?limit|too many requests|"
                                   r"quota exceeded|resource[ _-]?exhausted)\b", re.I),
        "retry",
        fix={"backoff_seconds": 30},
        reason="Penyedia meminta perlambatan; retry dengan backoff wajar.",
    ),
    Rule(
        "transient_server", re.compile(r"\b(500|502|503|504|bad gateway|"
                                       r"service unavailable|gateway timeout|"
                                       r"internal server error)\b", re.I),
        "retry",
        fix={"backoff_seconds": 5},
        reason="Kegagalan sisi server, umumnya sementara.",
    ),
    Rule(
        "network", re.compile(r"\b(ETIMEDOUT|ECONNRESET|ECONNREFUSED|EAI_AGAIN|"
                               r"connect(ion)? (reset|refused|timed? ?out)|"
                               r"temporary failure in name resolution|"
                               r"dns|ssl|network)\b", re.I),
        "retry",
        fix={"backoff_seconds": 3},
        reason="Masalah jaringan; sering pulih sendiri.",
    ),
    # ── Tidak bisa Saying-fix ───────────────────────────────────────────
    Rule(
        "not_found", re.compile(r"\b(404|not found|no such (host|table|column)|"
                                r"unknown (tool|node|field)|"
                                r"does not exist)\b", re.I),
        "abort",
        reason="Target tidak ada; mengulang tidak akan menemukannya.",
    ),
    Rule(
        "bad_request", re.compile(r"\b(400|422|validation|invalid (argument|parameter|"
                                  r"request)|schema)\b", re.I),
        "abort",
        reason="Permintaan tidak valid; lenderan dengan payload sama tidak akan berhasil.",
    ),
)


def classify_error(message: str) -> Optional[Rule]:
    """Kembalikan rule pertama yang cocok, atau None kalau tak dikenal.

    None berarti TIDAK ada aturan yang cocok — itu bukan izin untuk
    mencoba-coba. `handle_failure` memperlakukannya sebagai abort.
    """
    if not message:
        return None
    for r in RULES:
        if r.pattern.search(message):
            return r
    return None


@dataclass
class HealingPlan:
    action: str                      # retry | credential | abort
    node_id: str
    attempt: int
    reason: str
    changes: dict[str, Any] = field(default_factory=dict)
    provider: str = ""
    # Riwayat diagnosis, disimpan di step output supaya report ke user
    # bisa menunjukki APA yang dicoba — bukan cuma "gagal".
    trace: list[dict[str, Any]] = field(default_factory=list)
    search_hits: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "node_id": self.node_id,
            "attempt": self.attempt,
            "reason": self.reason,
            "changes": self.changes,
            "provider": self.provider,
            "trace": self.trace,
            "search_hits": self.search_hits,
        }


def _error_message(error: Any) -> str:
    """Ratakan error apa pun jadi string yang bisa di-pattern-match."""
    if isinstance(error, str):
        return error
    if isinstance(error, dict):
        parts = [str(error.get(k)) for k in ("type", "status", "code", "message", "detail")
                 if error.get(k) is not None]
        if parts:
            return " ".join(parts)
    return str(error)


class SelfHealingAgent:
    """Reflection + search-retry loop.

    Berhenti pada tiga kondisi, dan ketiganya disengaja:
      * `attempt > MAX_ATTEMPTS` -> None. Retry tanpa batas membakar kuota
        user untuk hal yang tidak akan pernah berhasil.
      * rule `credential` -> tidak di-retry. Butuh manusia.
      * tidak ada rule yang cocok -> abort. Error tak dikenal yang dicoba
        dengan perubahan tak teruji berisiko menutupi bug asli di balik
        "sementara gagal".
    """

    def __init__(self, *, max_attempts: int = MAX_ATTEMPTS,
                 search_enabled: bool = True,
                 llm_reflect=None,
                 http_timeout: float = 8.0):
        self.max_attempts = max_attempts
        self.search_enabled = search_enabled
        self.llm_reflect = llm_reflect
        self.http_timeout = http_timeout

    async def handle_failure(self, *, node_id: str, error: Any,
                             attempt: int = 1) -> Optional[HealingPlan]:
        if attempt > self.max_attempts:
            return None

        message = _error_message(error)
        rule = classify_error(message)
        trace: list[dict[str, Any]] = []

        # Reflection opsional. Gagal TIDAK boleh menggagalkan healing.
        reflection = None
        if self.llm_reflect is not None:
            try:
                reflection = await self.llm_reflect(message, attempt)
            except Exception as exc:  # noqa: BLE001
                reflection = None
                trace.append({"step": "reflect", "error": str(exc), "impact": "ignored"})

        if rule is None:
            return HealingPlan(
                action="abort", node_id=node_id, attempt=attempt,
                reason=("Error tidak dikenali pola mana pun; berhenti daripada "
                        "mencoba perubahan yang tak teruji."),
                trace=trace + [{"step": "classify", "matched": None}],
            )

        trace.append({"step": "classify", "matched": rule.name, "action": rule.action})
        if reflection:
            trace.append({"step": "reflection", "text": str(reflection)[:500]})

        # Credential tidak pernah di-retry: perlu manusia.
        if rule.action == "credential":
            return HealingPlan(
                action="credential", node_id=node_id, attempt=attempt,
                reason=rule.reason, provider=rule.provider, changes=rule.fix, trace=trace,
            )

        if rule.action == "abort":
            return HealingPlan(action="abort", node_id=node_id, attempt=attempt,
                               reason=rule.reason, trace=trace)

        # Retryable. Pencarian forum hanya dari percobaan ke-2: percobaan
        # pertama cukup untuk aturan, pencarian itu pengayaan bukan fondasi.
        hits = 0
        if self.search_enabled and attempt >= 2:
            try:
                found = await self.search_forum(message)
                hits = len(found)
                trace.append({"step": "search", "hits": hits,
                              "sources": sorted({f["source"] for f in found})})
            except Exception as exc:  # noqa: BLE001
                trace.append({"step": "search", "error": str(exc), "impact": "ignored"})

        return HealingPlan(
            action="retry", node_id=node_id, attempt=attempt,
            reason=rule.reason, changes=rule.fix, trace=trace, search_hits=hits,
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
