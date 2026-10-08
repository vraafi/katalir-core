# guardrails.py — Fitur #1: Guardrails Node (8 Okt 2026)
# ======================================================================
# Menutup gap vs n8n "Guardrails" node. Riset Okt 2026 (docs/feature-gap-
# closure-2026-10-08.md §1) menyimpulkan n8n punya 9 tipe guardrail:
#   1. Keywords          5. Secret Keys        9. Custom Regex
#   2. Jailbreak         6. Topical Alignment
#   3. NSFW              7. URLs
#   4. PII               8. Custom (LLM)
# dan DUA operasi: "Check Text for Violations" + "Sanitize Text".
#
# DESAIN (kenapa deterministik):
#   Tipe yang bisa diputuskan tanpa model (keywords, pii, secret_keys, urls,
#   custom_regex) diimplementasikan sebagai regex murni -> cepat (<100ms),
#   tidak butuh jaringan, dan hasilnya BISA DIUJI persis.
#   Tipe yang di n8n berbasis LLM (jailbreak, nsfw, topical_alignment,
#   custom) memakai SKORER HEURISTIK deterministik sebagai default, dan
#   menerima `judge` (callable) yang bisa disuntik untuk memakai LLM nyata.
#   Pola injeksi ini yang membuat guardrail bisa di-hard-test 1000x tanpa
#   memanggil jaringan, lalu dipakai produksi dengan judge LLM.
#
# KONTRAK OUTPUT (dipakai execution_engine._exec_guardrails):
#   check_text(text, config, judge=None) -> dict:
#     {status: "pass"|"block"|"warn",
#      violations: [{type, action, detail, ...}],
#      sanitized: str|None, duration_ms: float}
#   - "block" bila ada violation ber-action block (default action = block).
#   - "warn"  bila hanya ada violation ber-action warn/log.
#   - "pass"  bila tidak ada violation.
#   sanitize_text() menyalin operasi "Sanitize Text": violation DIGANTI
#   placeholder (mis. [EMAIL_ADDRESS_1]) dan TIDAK memblokir.
# ======================================================================

from __future__ import annotations

import re
import time
from typing import Any, Callable, Optional

#: 9 tipe guardrail (paritas n8n, docs resmi Okt 2026).
GUARDRAIL_TYPES = (
    "keywords", "jailbreak", "nsfw", "pii", "secret_keys",
    "topical_alignment", "urls", "custom", "custom_regex",
)

#: Operasi (paritas n8n).
OPERATIONS = ("check", "sanitize")

#: Aksi per guardrail.
ACTIONS = ("block", "warn", "log")

#: Entitas PII yang didukung (subset Microsoft Presidio yang dipakai n8n).
PII_ENTITIES = ("EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "US_SSN",
                "IP_ADDRESS", "IBAN_CODE")

#: Tingkat ketat deteksi secret key (paritas n8n: Strict/Permissive/Balanced).
SECRET_PERMISSIVENESS = ("strict", "balanced", "permissive")

DEFAULT_THRESHOLD = 0.5


# ---------------------------------------------------------------------------
# Tipe 4: PII — regex + validasi (Luhn untuk kartu kredit)
# ---------------------------------------------------------------------------

_PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "EMAIL_ADDRESS": re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
    "PHONE_NUMBER": re.compile(
        r"(?:(?:\+|00)\d{1,3}[\s\-.]?)?(?:\(\d{2,4}\)[\s\-.]?)?\d{3,4}[\s\-.]?\d{3,4}[\s\-.]?\d{0,4}"),
    "CREDIT_CARD": re.compile(r"\b(?:\d[ \-]?){13,19}\b"),
    "US_SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "IP_ADDRESS": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "IBAN_CODE": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"),
}


def _luhn_ok(digits: str) -> bool:
    """Validasi Luhn — menyaring 'nomor kartu' palsu (mis. 1234567890123456)."""
    ds = [int(c) for c in digits if c.isdigit()]
    if len(ds) < 13:
        return False
    total = 0
    for i, d in enumerate(reversed(ds)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


#: Prioritas saat dua entitas menutupi rentang yang sama. Kartu kredit &
#: SSN lebih spesifik daripada nomor telepon (16 digit bisa cocok keduanya).
_PII_PRIORITY = {
    "CREDIT_CARD": 0, "US_SSN": 1, "IBAN_CODE": 2,
    "EMAIL_ADDRESS": 3, "IP_ADDRESS": 4, "PHONE_NUMBER": 5,
}


def _find_pii(text: str, entities: Optional[list[str]] = None) -> list[dict]:
    """Temukan entitas PII. Kartu kredit WAJIB lolos Luhn (kurangi false positive).

    Penyelesaian tumpang-tindih (pola Presidio): bila dua entitas menutupi
    rentang yang sama (mis. '4111111111111111' cocok sebagai kartu DAN telepon),
    yang berprioritas lebih tinggi menang, sehingga placeholder sanitize tepat.
    """
    want = entities or list(PII_ENTITIES)
    cand: list[dict] = []
    for ent in want:
        pat = _PII_PATTERNS.get(ent)
        if not pat:
            continue
        for m in pat.finditer(text):
            val = m.group(0)
            if ent == "CREDIT_CARD" and not _luhn_ok(val):
                continue
            if ent == "IP_ADDRESS":
                octets = val.split(".")
                if any(int(o) > 255 for o in octets):
                    continue
            if ent == "PHONE_NUMBER" and len(re.sub(r"\D", "", val)) < 7:
                continue
            cand.append({"entity": ent, "match": val,
                         "start": m.start(), "end": m.end()})
    # terima dari prioritas tertinggi; tolak yang bertumpang-tindih
    cand.sort(key=lambda c: (_PII_PRIORITY.get(c["entity"], 9),
                             -(c["end"] - c["start"])))
    accepted: list[dict] = []
    for c in cand:
        if any(not (c["end"] <= a["start"] or c["start"] >= a["end"])
               for a in accepted):
            continue
        accepted.append(c)
    accepted.sort(key=lambda c: c["start"])
    return accepted


# ---------------------------------------------------------------------------
# Tipe 5: Secret Keys — pola provider populer + deteksi entropi
# ---------------------------------------------------------------------------

_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9\-._~+/]{20,}=*\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")),
]

#: Kata sandi/rahasia yang jelas di depan nilai (permissive & balanced).
_SECRET_ASSIGN = re.compile(
    r"(?i)\b(api[_-]?key|secret|password|passwd|token|client[_-]?secret)\b"
    r"\s*[:=]\s*['\"]?([A-Za-z0-9\-._~+/]{8,})['\"]?")


def _shannon_entropy(s: str) -> float:
    import math
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def _find_secrets(text: str, permissiveness: str = "balanced") -> list[dict]:
    """Deteksi secret key. Semakin 'strict', semakin agresif (entropi rendah pun kena)."""
    out: list[dict] = []
    seen: set[tuple[int, int]] = set()
    for name, pat in _SECRET_PATTERNS:
        for m in pat.finditer(text):
            seen.add((m.start(), m.end()))
            out.append({"kind": name, "match": m.group(0)[:12] + "…",
                        "start": m.start(), "end": m.end()})
    # heuristik entropi untuk token panjang tanpa prefix dikenal
    min_entropy = {"strict": 3.0, "balanced": 3.6, "permissive": 4.2}.get(
        permissiveness, 3.6)
    for m in re.finditer(r"\b[A-Za-z0-9+/=_\-]{20,}\b", text):
        if any(s <= m.start() and m.end() <= e for s, e in seen):
            continue
        if _shannon_entropy(m.group(0)) >= min_entropy:
            out.append({"kind": "high_entropy_string",
                        "match": m.group(0)[:12] + "…",
                        "start": m.start(), "end": m.end()})
    if permissiveness in ("balanced", "strict"):
        for m in _SECRET_ASSIGN.finditer(text):
            out.append({"kind": "labeled_secret",
                        "match": f"{m.group(1)}=…", "start": m.start(),
                        "end": m.end()})
    return out


# ---------------------------------------------------------------------------
# Tipe 7: URLs
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"\b([a-zA-Z][a-zA-Z0-9+.\-]{1,15}):\/\/([^\s/$.?#].[^\s]*)")
_SCHEME_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):")


def _url_scheme(url: str) -> str:
    m = _SCHEME_RE.match(url)
    return (m.group(1).lower() if m else "")


def _url_host(url: str) -> str:
    body = url.split("://", 1)[-1]
    return body.split("/", 1)[0].split("@")[-1].split(":")[0].lower()


def _find_urls(text: str, allowed: Optional[list[str]] = None,
               schemes: Optional[list[str]] = None,
               block_userinfo: bool = True,
               allow_subdomain: bool = False) -> list[dict]:
    """Deteksi URL pelanggar: scheme tak diizinkan, userinfo, atau host di luar allowlist."""
    allowed = [a.strip().lower() for a in (allowed or []) if a.strip()]
    schemes = [s.strip().lower() for s in (schemes or ["https", "http"]) if s.strip()]
    out: list[dict] = []
    for m in _URL_RE.finditer(text):
        url = m.group(0)
        scheme = _url_scheme(url)
        host = _url_host(url)
        reason = ""
        if scheme not in schemes:
            reason = f"scheme '{scheme}' tidak diizinkan"
        elif block_userinfo and "@" in url.split("://", 1)[-1].split("/", 1)[0]:
            reason = "URL memuat userinfo (kredensial)"
        elif allowed:
            ok = host in allowed
            if not ok and allow_subdomain:
                ok = any(host == a or host.endswith("." + a) for a in allowed)
            if not ok:
                reason = f"host '{host}' tidak ada di allowlist"
        if reason:
            out.append({"url": url, "host": host, "reason": reason,
                        "start": m.start(), "end": m.end()})
    return out


# ---------------------------------------------------------------------------
# Tipe 2/3/6/8: LLM-based -> skorer heuristik deterministik + judge injeksi
# ---------------------------------------------------------------------------

_JAILBREAK_SIGNALS = (
    "ignore previous", "ignore all previous", "ignore the above",
    "disregard previous", "forget your instructions", "abaikan instruksi",
    "abaikan aturan", "lupakan aturan", "system prompt", "reveal your prompt",
    "you are now", "pretend you are", "act as dan", "developer mode",
    "jailbreak", "dan mode", "do anything now", "bypass your",
    "override your", "tanpa batasan", "without restrictions",
)
_TOXIC_SIGNALS = (
    "kill yourself", "kys", "bunuh diri", "idiot", "bodoh sekali",
    "fuck you", "bastard", "bangsat", "anjing kamu", "hate speech",
    "worthless", "subhuman", "go die", "mati saja",
)
_NSFW_SIGNALS = (
    "explicit sex", "porn", "pornografi", "sexual content", "nude",
    "nsfw", "adult content", "xxx", "fetish",
)


def _signal_score(text: str, signals: tuple[str, ...]) -> float:
    """Skor 0..1 dari jumlah sinyal yang cocok (jenuh di 3 sinyal)."""
    low = text.lower()
    hits = sum(1 for s in signals if s in low)
    return min(1.0, hits / 3.0) if hits else 0.0


def _heuristic_judge(kind: str, text: str, prompt: str = "") -> float:
    """Skorer default (tanpa jaringan) untuk guardrail berbasis LLM."""
    if kind == "jailbreak":
        return _signal_score(text, _JAILBREAK_SIGNALS)
    if kind == "nsfw":
        return _signal_score(text, _NSFW_SIGNALS)
    if kind == "toxic":
        return _signal_score(text, _TOXIC_SIGNALS)
    if kind == "topical_alignment":
        # Tanpa prompt topik: anggap selaras. Dengan prompt: skor = kemiripan
        # kata kunci topik vs teks (Jaccard sederhana).
        if not prompt.strip():
            return 0.0
        topic = {w for w in re.findall(r"[a-z]{4,}", prompt.lower())}
        words = {w for w in re.findall(r"[a-z]{4,}", text.lower())}
        if not topic:
            return 0.0
        overlap = len(topic & words) / len(topic)
        return 1.0 - overlap  # off-topic tinggi bila kata topik sedikit muncul
    if kind == "custom":
        return _signal_score(text, (prompt.lower(),)) if prompt.strip() else 0.0
    return 0.0


Judge = Callable[[str, str, str], float]  # (kind, text, prompt) -> score 0..1


# ---------------------------------------------------------------------------
# Orkestrasi: satu guardrail -> violations
# ---------------------------------------------------------------------------

def _as_action(g: dict) -> str:
    a = str(g.get("action") or "block").strip().lower()
    return a if a in ACTIONS else "block"


def _as_threshold(g: dict) -> float:
    try:
        t = float(g.get("threshold", DEFAULT_THRESHOLD))
    except (TypeError, ValueError):
        t = DEFAULT_THRESHOLD
    return max(0.0, min(1.0, t))


def _eval_one(g: dict, text: str, judge: Optional[Judge]) -> list[dict]:
    """Evaluasi SATU guardrail terhadap teks -> daftar violation (bisa kosong)."""
    gtype = str(g.get("type") or "").strip().lower()
    action = _as_action(g)
    if gtype not in GUARDRAIL_TYPES:
        return [{"type": gtype or "(kosong)", "action": "warn",
                 "detail": f"tipe guardrail tak dikenal: {gtype!r}"}]
    v: list[dict] = []

    if gtype == "keywords":
        kws = g.get("keywords") or []
        if isinstance(kws, str):
            kws = [k.strip() for k in kws.split(",") if k.strip()]
        low = text.lower()
        for k in kws:
            if str(k).strip() and str(k).lower() in low:
                v.append({"type": "keywords", "action": action,
                          "keyword": str(k).strip(),
                          "detail": f"kata terlarang muncul: {k}"})

    elif gtype == "custom_regex":
        pats = g.get("patterns") or []
        if isinstance(pats, (str, dict)):
            pats = [pats]
        for p in pats:
            rx = p.get("regex") if isinstance(p, dict) else p
            name = (p.get("name") if isinstance(p, dict) else "") or "custom_regex"
            if not rx:
                continue
            try:
                for m in re.finditer(rx, text):
                    v.append({"type": "custom_regex", "action": action,
                              "name": name, "match": m.group(0)[:40],
                              "start": m.start(), "end": m.end(),
                              "detail": f"cocok pola {name}"})
            except re.error as exc:
                v.append({"type": "custom_regex", "action": "warn",
                          "detail": f"regex tidak valid {name!r}: {exc}"})

    elif gtype == "pii":
        ents = g.get("entities")
        if g.get("type_scope") == "selected" and isinstance(ents, str):
            ents = [e.strip() for e in ents.split(",") if e.strip()]
        for hit in _find_pii(text, ents if isinstance(ents, list) else None):
            v.append({"type": "pii", "action": action,
                      "entity": hit["entity"], "match": hit["match"],
                      "start": hit["start"], "end": hit["end"],
                      "detail": f"PII {hit['entity']} terdeteksi"})

    elif gtype == "secret_keys":
        perm = str(g.get("permissiveness") or "balanced").lower()
        for hit in _find_secrets(text, perm):
            v.append({"type": "secret_keys", "action": action,
                      "kind": hit["kind"], "match": hit["match"],
                      "start": hit["start"], "end": hit["end"],
                      "detail": f"kemungkinan secret: {hit['kind']}"})

    elif gtype == "urls":
        allowed = g.get("block_all_urls_except") or g.get("allowed") or []
        if isinstance(allowed, str):
            allowed = [a.strip() for a in allowed.split(",") if a.strip()]
        schemes = g.get("allowed_schemes") or ["https", "http"]
        if isinstance(schemes, str):
            schemes = [s.strip() for s in schemes.split(",") if s.strip()]
        for hit in _find_urls(
            text, allowed, schemes,
            block_userinfo=bool(g.get("block_userinfo", True)),
            allow_subdomain=bool(g.get("allow_subdomain", False)),
        ):
            v.append({"type": "urls", "action": action,
                      "url": hit["url"], "host": hit["host"],
                      "start": hit["start"], "end": hit["end"],
                      "detail": hit["reason"]})

    elif gtype in ("jailbreak", "nsfw", "topical_alignment", "custom"):
        thr = _as_threshold(g)
        prompt = str(g.get("prompt") or "")
        if gtype == "topical_alignment" and not prompt:
            prompt = str(g.get("topic") or "")
        score = (judge(gtype, text, prompt) if judge
                 else _heuristic_judge(gtype, text, prompt))
        score = max(0.0, min(1.0, float(score)))
        if score >= thr:
            v.append({"type": gtype, "action": action, "score": round(score, 3),
                      "threshold": thr,
                      "detail": f"{gtype} skor {score:.2f} >= ambang {thr:.2f}"})

    return v


def _worst(violations: list[dict]) -> str:
    """Status agregat: block menang atas warn menang atas pass."""
    if any(x.get("action") == "block" for x in violations):
        return "block"
    if any(x.get("action") in ("warn", "log") for x in violations):
        return "warn"
    return "pass"


def _label(v: dict) -> str:
    """Label placeholder: pakai nama PALING spesifik yang tersedia.

    n8n memakai nama entitas sebagai placeholder (mis. [EMAIL_ADDRESS_1]),
    bukan nama guardrail. Urutan preferensi: entity -> kind -> name -> type.
    """
    for key in ("entity", "kind", "name"):
        val = v.get(key)
        if val and str(val).strip():
            return str(val).strip().upper()
    return str(v.get("type") or "REDACTED").upper()


def _sanitize(text: str, violations: list[dict]) -> str:
    """Ganti tiap violation dengan placeholder [LABEL_n] (operasi Sanitize Text)."""
    spans = [(x.get("start"), x.get("end"), _label(x))
             for x in violations
             if isinstance(x.get("start"), int) and isinstance(x.get("end"), int)
             and x["end"] > x["start"]]
    if not spans:
        return text
    spans.sort(key=lambda t: t[0])
    merged: list[list] = []
    for s, e, t in spans:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e, t])
    counters: dict[str, int] = {}
    out: list[str] = []
    prev = 0
    for s, e, t in merged:
        out.append(text[prev:s])
        counters[t] = counters.get(t, 0) + 1
        out.append(f"[{t}_{counters[t]}]")
        prev = e
    out.append(text[prev:])
    return "".join(out)


# ---------------------------------------------------------------------------
# API publik
# ---------------------------------------------------------------------------

def check_text(text: str, config: dict, judge: Optional[Judge] = None) -> dict:
    """Operasi "Check Text for Violations".

    config.guardrails : list[dict]  (tiap item: {type, action, threshold, ...})
    Mengembalikan {status, violations, sanitized, duration_ms, checked_types}.
    """
    t0 = time.perf_counter()
    text = "" if text is None else str(text)
    guards = config.get("guardrails")
    if guards is None:
        guards = config.get("guardrails_json") or config.get("checks") or []
    if isinstance(guards, str):
        # Builder menyimpan config sebagai string -> coba JSON, lalu CSV tipe.
        import json
        try:
            parsed = json.loads(guards)
            guards = parsed if isinstance(parsed, list) else [parsed]
        except (ValueError, TypeError):
            guards = [{"type": t.strip()} for t in guards.split(",") if t.strip()]
    if isinstance(guards, dict):
        guards = [guards]
    operation = str(config.get("operation") or "check").strip().lower()

    violations: list[dict] = []
    for g in guards:
        if isinstance(g, str):
            g = {"type": g}
        if not isinstance(g, dict):
            continue
        violations.extend(_eval_one(g, text, judge))

    status = _worst(violations) if operation == "check" else "pass"
    sanitized = None
    if operation == "sanitize" or config.get("sanitize"):
        sanitized = _sanitize(text, violations)
        status = "pass" if config.get("sanitize_never_blocks", True) else status

    return {
        "status": status,
        "operation": operation,
        "violations": violations,
        "violation_count": len(violations),
        "sanitized": sanitized,
        "checked_types": [str(g.get("type")) for g in guards if isinstance(g, dict)],
        "duration_ms": round((time.perf_counter() - t0) * 1000, 3),
    }


def sanitize_text(text: str, config: dict, judge: Optional[Judge] = None) -> str:
    """Operasi "Sanitize Text": kembalikan teks yang sudah dibersihkan."""
    cfg = dict(config or {})
    cfg["operation"] = "sanitize"
    return check_text(text, cfg, judge=judge)["sanitized"] or ""


def run_config(text: str, config: dict, judge: Optional[Judge] = None) -> dict:
    """Entry point yang dipakai execution_engine: pilih operasi dari config."""
    op = str((config or {}).get("operation") or "check").strip().lower()
    if op not in OPERATIONS:
        op = "check"
    cfg = dict(config or {})
    cfg["operation"] = op
    return check_text(text, cfg, judge=judge)


__all__ = [
    "GUARDRAIL_TYPES", "OPERATIONS", "ACTIONS", "PII_ENTITIES",
    "SECRET_PERMISSIVENESS", "DEFAULT_THRESHOLD",
    "check_text", "sanitize_text", "run_config",
]
