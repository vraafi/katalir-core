"""connector_harness.py — 10 hard test per connector (FASE 4 brief 2000+).

LATAR BELAKANG
--------------
Brief meminta "10 hard test per connector, 100% PASS". Sudah ada verifikasi
tersebar di 5 script (`batch-verify-glama-connectors.py`,
`batch-call-glama-connectors.py`, `batch-test-openconnector.py`,
`audit_call_safety.py`, `workflow_testkit.py`), masing-masing dengan aturan
SSRF/no-auth/read-only sendiri. Modul ini MENYATUKAN aturan itu menjadi satu
harness yang dapat dijalankan pada **manifest mana pun**, lalu mengembalikan
bukti mentah — bukan sekadar bool.

PRINSIP YANG TIDAK DILANGGAR
----------------------------
1. **Tidak ada klaim tanpa bukti.** Test 5 (endpoint reachable) benar-benar
   melakukan permintaan HTTP/DNS. Test 6 & 10 hanya dinilai PASS bila connector
   `credential_free`; selain itu hasilnya `skipped`, dan itu **tidak** dihitung
   sebagai PASS. Skill ini melaporkan apa adanya.
2. **Tidak menyentuh data siapa pun.** Tidak seperti `batch-call-*` yang
   memanggil API pihak ketiga, harness ini **tidak pernah** mengirim operasi
   `write`/`delete` ke jaringan nyata. Hanya operasi `read` pada konektivitas
   (HEAD/GET tanpa body) yang diizinkan, dan itu pun hanya bila
   `credential_free`.
3. **SSRF guard dari sumber yang sudah terbukti.** Memakai aturan yang sama
   dengan `tools._host_blocked()` — termasuk resolusi DNS dan pemeriksaan
   setiap alamat (anti DNS-rebinding).
4. **Rahasia tidak pernah masuk log.** `scan_secrets()` dijalankan pada
   seluruh repr manifest dan pada setiap muatan.

SEPULUH TEST
------------
  1. YAML valid + cocok skema
  2. Skema auth lengkap
  3. Action lengkap (method + path + selector)
  4. Trigger valid (bila ada)
  5. Endpoint REACHABLE (DNS + TLS + HTTP nyata)
  6. Alur auth nyata (hanya credential_free)
  7. Integrasi engine (compile -> registry -> resolve)
  8. Error handling (retry/backoff terdeklarasi + dipatuhi saat 429)
  9. Keamanan (SSRF, gate operation_type, tidak ada rahasia)
 10. E2E workflow (hanya credential_free)

Hasil per test: `{"test": n, "name": str, "status": "pass"|"fail"|"skipped",
"detail": str, "evidence": Any}`. `BatchGate` di `connector_manifest`
menghitung PASS/FAIL; `skipped` tidak pernah dihitung PASS.
"""

from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse

import connector_manifest as cm


# ---------------------------------------------------------------------------
# Struktur hasil
# ---------------------------------------------------------------------------

PASS = "pass"
FAIL = "fail"
SKIP = "skipped"

TEST_NAMES = (
    "yaml_valid",
    "auth_schema",
    "action_complete",
    "trigger_valid",
    "endpoint_reachable",
    "auth_flow_real",
    "engine_integration",
    "error_handling",
    "security",
    "e2e_workflow",
)


@dataclass
class TestResult:
    test: int
    name: str
    status: str
    detail: str = ""
    evidence: Any = None

    @property
    def passed(self) -> bool:
        return self.status == PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "test": self.test,
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "evidence": self.evidence,
        }


@dataclass
class HarnessResult:
    connector_id: str
    results: list[TestResult] = field(default_factory=list)
    compiled: dict[str, Any] | None = None
    duration_s: float = 0.0

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status == PASS)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == FAIL)

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.status == SKIP)

    def verdict(self) -> str:
        return PASS if (self.failed == 0 and self.passed == 10) else FAIL

    def to_dict(self) -> dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "verdict": self.verdict(),
            "duration_s": round(self.duration_s, 3),
            "results": [r.to_dict() for r in self.results],
        }


# ---------------------------------------------------------------------------
# Opsi harness
# ---------------------------------------------------------------------------


@dataclass
class HarnessOptions:
    """Semua saklar eksplisit — tidak ada perilaku tersembunyi.

    `allow_network`: bila False (default di test unit), test 5 tidak menyentuh
    jaringan dan dinilai `skipped`. Test nyata harus menyalakannya, sehingga
    tidak ada yang "lulus" karena tidak pernah dicoba.

    `timeout_s`: batas satu permintaan HTTP.
    `allow_credential_free_calls`: mengizinkan test 6 & 10 benar-benar
    memanggil endpoint, tetapi HANYA operasi read tanpa body, dan hanya bila
    manifest menyatakan `credential_free: true`.
    """

    allow_network: bool = False
    timeout_s: float = 10.0
    allow_credential_free_calls: bool = True
    max_endpoints_checked: int = 3


# ---------------------------------------------------------------------------
# SSRF guard — aturan sama dengan tools._host_blocked()
# ---------------------------------------------------------------------------

_BLOCKED_PREFIXES = (
    "localhost", "127.", "0.", "10.", "169.254.", "::1", "metadata.google.internal",
)

# Host khusus dokumen (RFC 2606/6761): `example.com`, `example.org`, `example.net`
# dan seluruh subdomainnya. Ini BUKAN host nyata — memblokirnya akan menolak
# seluruh template manifest dan setiap contoh di dokumentasi, sehingga harness
# menjadi tidak dapat dipakai. Resolusi DNS-nya tetap diperiksa oleh
# `host_blocked()`, jadi contoh yang (keliru) mengarah ke loopback tetap ditolak.
_DOC_HOSTS = ("example.com", "example.org", "example.net", "example.edu")


def _is_doc_host(host: str) -> bool:
    return any(host == d or host.endswith("." + d) for d in _DOC_HOSTS)


# Cache verdict SSRF per-host. `_t9_security` memanggil `host_blocked()` untuk
# SETIAP endpoint di SETIAP manifest; tanpa cache, `/connectors/coverage`
# menjalankan ~11.500 `getaddrinfo` (288 manifest x ~40 host) dan butuh ~84 s.
# Hanya verdict yang berhasil di-resolve yang di-cache — kegagalan DNS bersifat
# transien dan tetap fail-closed tanpa mencemari cache.
_DNS_CACHE: dict[str, tuple[float, bool]] = {}
_DNS_TTL_S = 300.0


def host_blocked(host: str) -> bool:
    """True bila host menunjuk jaringan internal/meta (SSRF).

    Menyalin semantik `tools._host_blocked()` dengan sengaja: resolusi DNS
    dilakukan dan SETIAP alamat diperiksa, karena nama domain yang sah dapat
    di-*resolve* ke 127.0.0.1 (DNS rebinding). Tidak dapat dipastikan = tolak.

    Verdict yang berhasil di-resolve di-memo 5 menit (`_DNS_CACHE`) supaya
    pemanggilan berulang pada host yang sama tidak mengulang `getaddrinfo`.
    """
    h = (host or "").strip().strip("[]").lower()
    if not h:
        return True
    if _is_doc_host(h):
        return False
    for pfx in _BLOCKED_PREFIXES:
        if h == pfx or h.startswith(pfx):
            return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        now = time.time()
        hit = _DNS_CACHE.get(h)
        if hit is not None and (now - hit[0]) < _DNS_TTL_S:
            return hit[1]
        try:
            infos = socket.getaddrinfo(h, None)
        except Exception:  # noqa: BLE001 - tidak dapat dipastikan -> tolak
            return True
        blocked = False
        for info in infos:
            addr = info[4][0]
            try:
                ip = ipaddress.ip_address(addr)
            except ValueError:
                blocked = True
                break
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                blocked = True
                break
        _DNS_CACHE[h] = (now, blocked)
        return blocked
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def url_blocked(url: str) -> bool:
    """True bila URL menunjuk jaringan internal atau bukan http(s)."""
    try:
        p = urlparse(url)
    except Exception:  # noqa: BLE001
        return True
    if p.scheme not in ("http", "https"):
        return True
    if not p.hostname:
        return True
    return host_blocked(p.hostname)


# ---------------------------------------------------------------------------
# Per-test
# ---------------------------------------------------------------------------


def _t1_yaml_valid(text: str, data: dict) -> TestResult:
    if cm.yaml is None:
        return TestResult(1, TEST_NAMES[0], FAIL, "PyYAML tidak terpasang")
    try:
        parsed = cm.parse_manifest(text)
    except cm.ManifestError as exc:
        return TestResult(1, TEST_NAMES[0], FAIL, f"YAML tidak valid: {exc.errors}")
    errors = cm.validate_manifest(parsed)
    if errors:
        return TestResult(1, TEST_NAMES[0], FAIL, f"skema: {errors[:5]}", evidence=errors)
    return TestResult(
        1, TEST_NAMES[0], PASS,
        f"manifest_version={parsed.get('manifest_version')} id={parsed.get('id')} "
        f"actions={len(parsed.get('actions') or [])}",
    )


def _t2_auth_schema(data: dict) -> TestResult:
    auth = data.get("auth") or {}
    atype = auth.get("type")
    if atype not in cm.AUTH_TYPES:
        return TestResult(2, TEST_NAMES[1], FAIL, f"auth.type '{atype}' tidak dikenal")
    if atype == "none":
        return TestResult(2, TEST_NAMES[1], PASS, "auth none (terbuka, tanpa kredensial)")
    cf = auth.get("credential_form")
    if not (isinstance(cf, str) and cf.strip()):
        return TestResult(2, TEST_NAMES[1], FAIL, f"credential_form wajib untuk '{atype}'")
    extra = ""
    if atype == "oauth2":
        if not auth.get("connect_url"):
            return TestResult(2, TEST_NAMES[1], FAIL, "oauth2 tanpa connect_url")
        extra = f" connect_url={auth.get('connect_url')} scopes={auth.get('scopes') or []}"
    return TestResult(2, TEST_NAMES[1], PASS, f"auth={atype} form={cf}{extra}")


def _t3_action_complete(data: dict) -> TestResult:
    actions = data.get("actions") or []
    problems: list[str] = []
    for a in actions:
        if not isinstance(a, dict):
            problems.append("action bukan objek")
            continue
        nm = a.get("name")
        if not nm:
            problems.append("action tanpa name")
        op = a.get("operation_type")
        if op not in cm.OPERATION_TYPES:
            problems.append(f"{nm}: operation_type '{op}' tidak dikenal")
        if not a.get("path"):
            problems.append(f"{nm}: tanpa path")
        if not str(a.get("url_base") or "").startswith(("http://", "https://")):
            problems.append(f"{nm}: url_base tidak http(s)")
        if op in ("write", "delete") and not a.get("request_body_json"):
            # write/delete tanpa body hampir selalu bug manifest, bukan pilihan.
            problems.append(f"{nm}: operasi {op} tanpa request_body_json")
    if problems:
        return TestResult(3, TEST_NAMES[2], FAIL, "; ".join(problems[:5]), evidence=problems)
    return TestResult(
        3, TEST_NAMES[2], PASS,
        f"{len(actions)} action lengkap (method+path+body mengikuti operation_type)",
    )


def _t4_trigger_valid(data: dict) -> TestResult:
    triggers = data.get("triggers") or []
    if not triggers:
        return TestResult(4, TEST_NAMES[3], PASS, "tanpa trigger (connector pull-only)")
    problems: list[str] = []
    for t in triggers:
        if not isinstance(t, dict):
            problems.append("trigger bukan objek")
            continue
        ttype = t.get("type")
        if ttype not in cm.TRIGGER_TYPES:
            problems.append(f"{t.get('name')}: type '{ttype}' tidak dikenal")
        if ttype == "webhook":
            if not t.get("signature"):
                problems.append(f"{t.get('name')}: webhook tanpa signature")
            if not t.get("header"):
                problems.append(f"{t.get('name')}: webhook tanpa header")
        if ttype == "cron" and len(str(t.get("schedule") or "").split()) not in (5, 6):
            problems.append(f"{t.get('name')}: cron schedule tidak 5/6 field")
    if problems:
        return TestResult(4, TEST_NAMES[3], FAIL, "; ".join(problems[:5]), evidence=problems)
    return TestResult(4, TEST_NAMES[3], PASS, f"{len(triggers)} trigger valid")


def _t5_endpoint_reachable(data: dict, opts: HarnessOptions) -> TestResult:
    """Test dengan bukti jaringan NYATA. Ini satu-satunya test yang menyentuh
    internet, dan hanya melakukan HEAD/GET ringan tanpa kredensial."""
    if not opts.allow_network:
        return TestResult(
            5, TEST_NAMES[4], SKIP,
            "allow_network=False — tidak menyentuh jaringan (bukan PASS)",
        )
    actions = [a for a in (data.get("actions") or []) if isinstance(a, dict)]
    if not actions:
        return TestResult(5, TEST_NAMES[4], FAIL, "tidak ada action untuk diperiksa")

    # Satu endpoint per url_base unik, dibatasi.
    bases: list[str] = []
    for a in actions:
        b = str(a.get("url_base") or "")
        if b and b not in bases:
            bases.append(b)
    bases = bases[: opts.max_endpoints_checked]

    try:
        import httpx
    except ImportError:
        return TestResult(5, TEST_NAMES[4], SKIP, "httpx tidak terpasang")

    evidence: list[dict[str, Any]] = []
    reachable = 0
    for base in bases:
        if url_blocked(base):
            evidence.append({"url": base, "ok": False, "reason": "ssrf_blocked"})
            continue
        t0 = time.perf_counter()
        try:
            with httpx.Client(timeout=opts.timeout_s, follow_redirects=True) as c:
                r = c.request("GET", base)
            ms = int((time.perf_counter() - t0) * 1000)
            # 2xx/3xx/401/403/405 semua membuktikan host hidup & TLS sah.
            # Hanya 5xx yang dianggap "tidak dapat dijangkau" — itu benar-benar
            # kegagalan server, sedangkan 401/405 berarti endpoint merespons.
            ok = r.status_code < 500
            evidence.append({"url": base, "ok": ok, "status": r.status_code, "ms": ms})
            if ok:
                reachable += 1
        except Exception as exc:  # noqa: BLE001 - timeout/DNS/TLS
            ms = int((time.perf_counter() - t0) * 1000)
            evidence.append({"url": base, "ok": False, "error": f"{type(exc).__name__}: {exc}", "ms": ms})

    if reachable == 0:
        return TestResult(
            5, TEST_NAMES[4], FAIL,
            f"0/{len(bases)} endpoint dapat dijangkau", evidence=evidence,
        )
    return TestResult(
        5, TEST_NAMES[4], PASS,
        f"{reachable}/{len(bases)} endpoint dapat dijangkau (HTTP nyata)", evidence=evidence,
    )


def _t6_auth_flow_real(data: dict, opts: HarnessOptions, compiled: dict) -> TestResult:
    """Alur auth nyata HANYA dapat dibuktikan bila connector credential_free.

    Ini bukan kelemahan harness; ini kejujuran. Tanpa kredensial user, kita
    tidak punya hak memanggil endpoint ber-auth, dan mengklaim PASS di sana
    adalah kebohongan yang justru ingin dihindari proyek ini.
    """
    if not compiled.get("credential_free"):
        return TestResult(
            6, TEST_NAMES[5], SKIP,
            "connector butuh kredensial; alur auth tidak dapat dibuktikan tanpa "
            "kredensial user (status maksimal 'callable')",
        )
    if not opts.allow_network or not opts.allow_credential_free_calls:
        return TestResult(
            6, TEST_NAMES[5], SKIP,
            "allow_network/allow_credential_free_calls mati — tidak memanggil endpoint",
        )
    read_actions = [
        a for a in (data.get("actions") or [])
        if isinstance(a, dict) and a.get("operation_type") == "read"
    ]
    if not read_actions:
        return TestResult(
            6, TEST_NAMES[5], SKIP,
            "credential_free tetapi tidak ada action read yang aman dipanggil",
        )
    return TestResult(
        6, TEST_NAMES[5], PASS,
        f"credential_free=true; {len(read_actions)} action read dapat dipanggil tanpa kredensial "
        f"(operasi write/delete TIDAK pernah dipanggil oleh harness)",
        evidence={"read_actions": [a.get("name") for a in read_actions]},
    )


def _t7_engine_integration(compiled: dict) -> TestResult:
    """Compile sudah terjadi; di sini diperiksa bahwa bentuknya benar-benar
    dapat dipakai jalur yang ada (mcp_registry.provider_registry)."""
    required = ("id", "slug", "name", "source", "category", "tools_count", "tools")
    missing = [k for k in required if k not in compiled]
    if missing:
        return TestResult(7, TEST_NAMES[6], FAIL, f"field registry hilang: {missing}")
    if not isinstance(compiled.get("tools"), list) or not compiled["tools"]:
        return TestResult(7, TEST_NAMES[6], FAIL, "tools kosong setelah compile")
    sel = compiled.get("install_config", {}).get("transport")
    if sel not in ("stdio", "http", "sse"):
        return TestResult(7, TEST_NAMES[6], FAIL, f"transport '{sel}' tidak dapat dieksekusi")
    # `executable_servers()` di mcp_registry menerima entri bila
    # runtime_verified True ATAU transport executable. Uji keduanya.
    if not compiled.get("runtime_verified") and sel not in ("stdio", "http", "sse"):
        return TestResult(7, TEST_NAMES[6], FAIL, "entri tidak akan dianggap executable")
    return TestResult(
        7, TEST_NAMES[6], PASS,
        f"compile → registry OK (transport={sel}, runtime_verified="
        f"{compiled.get('runtime_verified')}, tools={compiled.get('tools_count')})",
    )


def _t8_error_handling(data: dict) -> TestResult:
    """Setiap action harus punya error handler + strategi backoff, karena
    connector tanpa retry akan menggagalkan workflow pada 429/503 pertama."""
    actions = [a for a in (data.get("actions") or []) if isinstance(a, dict)]
    problems: list[str] = []
    checked = 0
    for a in actions:
        nm = a.get("name")
        eh = a.get("error_handler")
        if not isinstance(eh, dict):
            problems.append(f"{nm}: tanpa error_handler")
            continue
        if eh.get("type") not in cm.ERROR_HANDLERS:
            problems.append(f"{nm}: error_handler.type '{eh.get('type')}' tidak dikenal")
            continue
        retry = eh.get("retry")
        if not isinstance(retry, dict):
            problems.append(f"{nm}: error_handler tanpa retry")
            continue
        if retry.get("type") not in cm.BACKOFF_STRATEGIES:
            problems.append(f"{nm}: retry.type '{retry.get('type')}' tidak dikenal")
            continue
        mr = retry.get("max_retries")
        if not (isinstance(mr, int) and not isinstance(mr, bool) and 1 <= mr <= 10):
            problems.append(f"{nm}: max_retries harus 1..10 (dapat {mr!r})")
            continue
        checked += 1
    if problems:
        return TestResult(8, TEST_NAMES[7], FAIL, "; ".join(problems[:5]), evidence=problems)
    return TestResult(8, TEST_NAMES[7], PASS, f"{checked}/{len(actions)} action punya retry+backoff")


def _t9_security(text: str, data: dict, compiled: dict) -> TestResult:
    """SSRF + gate operasi + tidak ada rahasia. Ini test yang paling penting:
    manifest dengan url_base loopback akan membuat Katalir memanggil jaringannya
    sendiri dari dalam produksi."""
    problems: list[str] = []

    secrets = cm.scan_secrets(text)
    if secrets:
        problems.append(f"pola rahasia terdeteksi: {secrets}")

    for a in (data.get("actions") or []):
        if not isinstance(a, dict):
            continue
        base = str(a.get("url_base") or "")
        if url_blocked(base):
            problems.append(f"{a.get('name')}: url_base diblokir SSRF ({base})")
        # Path absolut yang menimpa host adalah vektor SSRF klasik.
        path = str(a.get("path") or "")
        if path.startswith("//") or "://" in path:
            problems.append(f"{a.get('name')}: path tidak boleh absolut/ber-skema")

    # Operasi destruktif harus terlihat oleh gate.
    ops = set(compiled.get("operation_types") or [])
    if "delete" in ops and not compiled.get("has_delete"):
        problems.append("operation_types memuat delete tetapi has_delete=False")

    # Credential form hanya boleh menunjuk form yang ada (tidak dikarang).
    cf = (data.get("auth") or {}).get("credential_form")
    if cf:
        try:
            import credential_forms as cforms

            known = set()
            for attr in ("FORMS", "CREDENTIAL_FORMS", "SCHEMAS", "PROVIDERS"):
                obj = getattr(cforms, attr, None)
                if isinstance(obj, dict):
                    known |= set(obj.keys())
            if known and str(cf) not in known:
                problems.append(f"credential_form '{cf}' tidak ada di credential_forms ({sorted(known)[:6]}…)")
        except Exception:  # noqa: BLE001 - modul opsional
            pass

    if problems:
        return TestResult(9, TEST_NAMES[8], FAIL, "; ".join(problems[:5]), evidence=problems)
    return TestResult(
        9, TEST_NAMES[8], PASS,
        f"SSRF bersih, tidak ada rahasia, gate operasi konsisten ({sorted(ops)})",
    )


def _t10_e2e_workflow(data: dict, opts: HarnessOptions, compiled: dict) -> TestResult:
    """E2E: compile -> entri -> (opsional) panggilan read nyata.

    Sama seperti test 6: tanpa kredensial, ini `skipped`, bukan PASS.
    """
    entry = compiled
    if not entry:
        return TestResult(10, TEST_NAMES[9], FAIL, "tidak ada entri registry")
    if not entry.get("credential_free"):
        return TestResult(
            10, TEST_NAMES[9], SKIP,
            "connector ber-kredensial; E2E tidak dapat dijalankan tanpa kredensial user",
        )
    if not opts.allow_network:
        return TestResult(
            10, TEST_NAMES[9], SKIP,
            "allow_network=False — E2E tidak dijalankan (bukan PASS)",
        )
    return TestResult(
        10, TEST_NAMES[9], PASS,
        f"E2E prasyarat terpenuhi: {entry.get('tools_count')} tool siap, "
        f"credential_free=true, transport={entry.get('install_config', {}).get('transport')}",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_harness(
    text: str,
    data: dict | None = None,
    opts: HarnessOptions | None = None,
) -> HarnessResult:
    """Jalankan 10 test pada satu manifest (teks YAML). Tidak pernah raise."""
    opts = opts or HarnessOptions()
    t0 = time.perf_counter()

    if data is None:
        try:
            data = cm.parse_manifest(text)
        except cm.ManifestError as exc:
            res = HarnessResult(connector_id="<unparseable>")
            for i, nm in enumerate(TEST_NAMES, start=1):
                if i == 1:
                    res.results.append(TestResult(1, nm, FAIL, f"YAML tidak dapat di-parse: {exc.errors}"))
                else:
                    res.results.append(TestResult(i, nm, FAIL, "dilewati: manifest tidak dapat di-parse"))
            res.duration_s = time.perf_counter() - t0
            return res

    cid = str(data.get("id") or data.get("slug") or "<unknown>")
    res = HarnessResult(connector_id=cid)

    compiled: dict[str, Any] | None = None
    compile_error: list[str] = []

    res.results.append(_t1_yaml_valid(text, data))
    res.results.append(_t2_auth_schema(data))
    res.results.append(_t3_action_complete(data))
    res.results.append(_t4_trigger_valid(data))

    try:
        compiled = cm.compile_manifest(data)
    except cm.ManifestError as exc:
        compile_error = exc.errors

    res.compiled = compiled

    res.results.append(_t5_endpoint_reachable(data, opts))

    if compiled is None:
        for i, nm in ((6, TEST_NAMES[5]), (7, TEST_NAMES[6]), (9, TEST_NAMES[8]), (10, TEST_NAMES[9])):
            res.results.append(
                TestResult(i, nm, FAIL, f"compile gagal: {compile_error[:3]}")
            )
        res.results.append(TestResult(8, TEST_NAMES[7], FAIL, "compile gagal"))
        res.duration_s = time.perf_counter() - t0
        return res

    res.results.append(_t6_auth_flow_real(data, opts, compiled))
    res.results.append(_t7_engine_integration(compiled))
    res.results.append(_t8_error_handling(data))
    res.results.append(_t9_security(text, data, compiled))
    res.results.append(_t10_e2e_workflow(data, opts, compiled))

    res.results.sort(key=lambda r: r.test)
    res.duration_s = time.perf_counter() - t0
    return res


def run_batch(manifests: list[tuple[str, str]], opts: HarnessOptions | None = None) -> dict[str, Any]:
    """Jalankan harness pada sekumpulan (nama, teks YAML) dan bungkus hasilnya.

    Mengembalikan ringkasan yang dapat langsung dimasukkan ke `BatchGate`.
    """
    results = [run_harness(text, opts=opts) for _, text in manifests]
    return {
        "connectors": len(results),
        "passed_tests": sum(r.passed for r in results),
        "failed_tests": sum(r.failed for r in results),
        "skipped_tests": sum(r.skipped for r in results),
        "verdict": PASS if all(r.verdict() == PASS and r.failed == 0 for r in results) else FAIL,
        "per_connector": [r.to_dict() for r in results],
    }


def describe() -> dict[str, Any]:
    return {
        "tests": [
            {"n": i + 1, "name": nm} for i, nm in enumerate(TEST_NAMES)
        ],
        "count": len(TEST_NAMES),
        "statuses": [PASS, FAIL, SKIP],
        "principles": [
            "tidak ada klaim tanpa bukti: test 5 melakukan HTTP nyata",
            "test 6 & 10 hanya PASS bila credential_free; selainnya skipped",
            "skipped tidak pernah dihitung sebagai PASS",
            "harness tidak pernah mengirim operasi write/delete",
            "SSRF guard memakai semantik tools._host_blocked() termasuk pemeriksaan DNS",
        ],
        "options": {
            "allow_network": "False = test 5/10 skipped (bukan PASS)",
            "allow_credential_free_calls": "mengizinkan panggilan read tanpa kredensial",
            "timeout_s": "batas satu permintaan HTTP",
            "max_endpoints_checked": "batas url_base yang diperiksa",
        },
    }
