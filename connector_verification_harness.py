#!/usr/bin/env python3
"""connector_verification_harness.py — 8-layer REAL/FAKE verification.

Latar belakang
--------------
Katalog Katalir berisi puluhan ribu entri, tetapi "ada di katalog" != "benar-
benar bekerja". Studi CSA (7 Okt 2026) menemukan 9,57% MCP server terekspos
tanpa auth, 51,1% silent drift, dan hanya 3% tools punya output contract yang
valid. Jadi HTTP 200 saja BUKAN bukti.

Harness ini memverifikasi setiap konektor dengan 8 layer + 3 supply-chain audit,
lalu memberi satu klasifikasi final. Yang penting: ia memakai TOOL NYATA
(Oktober 2026), bukan heuristik yang diklaim:

  Layer 1  reachable        -> native httpx (TLS/redirect dicatat)
  Layer 2  handshake MCP    -> native JSON-RPC initialize
  Layer 3  tools/list       -> native JSON-RPC tools/list
  Layer 4  reality check    -> mcp-reality-check (pip, nyata)
  Layer 5  contract/schema  -> mcp-contract-check --fuzz (npm, nyata)
  Layer 6  conformance      -> @hasmcp/mcp-spec-test --spec-version 2026-07-28
  Layer 7  grading A-F      -> mcpdoctor test (parallelromb, dibangun dari git)
  Layer 8  mock vs real     -> detektor false-green LOKAL (skillsmp 404 ->
                               diimplementasikan sendiri, TIDAK diklaim sebagai
                               paket bernama "mock-vs-real-detector")

  Audit A  MCPJacking       -> DNS resolve + RDAP expiry (domain takeover)
  Audit B  silent drift     -> redirect chain max 3 hop + bandingkan host
  Audit C  unauth exposure  -> tools/list tanpa auth

Klasifikasi final (urutan menang):
  DEAD -> JACKABLE -> DRIFT -> NOT_MCP -> UNAUTH_EXPOSED -> FAKE ->
  NON_CONFORMANT -> REAL_GRADE_A/B/C

Mode:
  native  : layer 1-3, 8 + audit dijalankan in-process (cepat, semua konektor).
  deep    : TAMBAHAN layer 4-7 dijalankan lewat tool eksternal nyata.
            Klaim REAL_GRADE_*/FAKE/NON_CONFORMANT hanya sah di mode deep.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
TOOLS = ROOT / "_verify_tools"
NODE = Path(r"C:\Program Files\nodejs\node.exe")
PY312 = Path(r"C:\Users\user\AppData\Local\Programs\Python\Python312\python.exe")
PYLIBS = TOOLS / "pylibs"
NPM = TOOLS / "node_modules"

# entry point JS tiap tool node (bin field dari package.json)
NODE_ENTRIES = {
    "mcp-probe": NPM / "@beeeeen" / "mcp-probe" / "dist" / "cli.js",
    "mcp-contract-check": NPM / "mcp-contract-check" / "dist" / "cli.js",
    "mcp-spec-test": NPM / "@hasmcp" / "mcp-spec-test" / "bin" / "mcp-spec-test.mjs",
    "mcpdoctor": TOOLS / "mcpdoctor" / "cli" / "dist" / "index.js",
}
REALITY_LAUNCHER = TOOLS / "run_reality.py"
RIG_LAUNCHER = TOOLS / "run_rig.py"

INIT_PARAMS = {
    "protocolVersion": "2025-06-18",
    "capabilities": {"roots": {"listChanged": True}, "sampling": {}},
    "clientInfo": {"name": "katalir-verify", "version": "1.0.0"},
}
MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def mcp_headers(session_id: str | None = None) -> dict:
    """Header MCP + Mcp-Session-Id bila server memberikannya di initialize.

    Banyak server streamable-HTTP menolak tools/list atau tools/call tanpa
    header sesi ini ("Server not initialized", "Missing session ID"). Tanpa ini
    kita salah menuduh server 'FAKE' padahal protokolnya benar.
    """
    h = dict(MCP_HEADERS)
    if session_id:
        h["Mcp-Session-Id"] = session_id
    return h

# frasa yang menandakan "sukses palsu": 200 tapi isinya penolakan/kosong
REFUSAL_MARKERS = (
    "not configured", "not connected", "please configure",
    "not implemented", "todo", "placeholder", "lorem ipsum",
    "example.com", "sample data", "dummy", "mock data", "not available",
)
# frasa yang menandakan tool BUTUH kredensial/bayar -> bukan FAKE, tapi AUTH.
AUTH_MARKERS = (
    "unauthor", "authentication", "api key", "apikey", "invalid_api_key",
    "bearer", "credential", "missing token", "access token", "payment required",
    "payment_required", "subscription", "quota", "insufficient",
    "invalid or disabled token", "no key", "authorization header", "autorizzato",
    "personal link", "requires a key", "api token", "token required",
    "needs a personal", "missing api", "not authenticated", "login required",
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def extract_json(text: str) -> dict | None:
    """Ambil objek JSON dari body polos ATAU dari SSE (`event: message\\ndata: {...}`)."""
    if not text:
        return None
    t = text.strip()
    if t.startswith("{"):
        try:
            return json.loads(t)
        except ValueError:
            pass
    for line in t.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload and payload != "[DONE]":
                try:
                    return json.loads(payload)
                except ValueError:
                    continue
    m = re.search(r"\{.*\}", t, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except ValueError:
            return None
    return None


def domain_of(url: str) -> str:
    m = re.match(r"https?://([^/:]+)", url or "")
    return (m.group(1) if m else "").lower()


def _run(cmd: list[str], timeout: float, env: dict | None = None) -> tuple[int, str, str]:
    """Jalankan subprocess, kembalikan (rc, stdout, stderr). Tidak pernah melempar."""
    e = dict(os.environ)
    if env:
        e.update(env)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           env=e, encoding="utf-8", errors="replace")
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired as exc:
        return 124, (exc.stdout or ""), f"timeout after {timeout}s"
    except Exception as exc:  # noqa: BLE001
        return 1, "", f"{type(exc).__name__}: {exc}"


# --------------------------------------------------------------------------
# harness
# --------------------------------------------------------------------------

class ConnectorVerificationHarness:
    def __init__(self, *, concurrency: int = 12, deep: bool = False,
                 tool_timeout: float = 60.0, verify_tls: bool = True,
                 rdap: bool = False, connector_timeout: float = 45.0):
        self.concurrency = concurrency
        self.deep = deep
        self.tool_timeout = tool_timeout
        self.verify_tls = verify_tls
        self.rdap = rdap
        self.connector_timeout = connector_timeout
        self.results: list[dict] = []

    # ---------------- layer 1: reachable ----------------
    async def _layer1_reachable(self, client: httpx.AsyncClient, url: str) -> dict:
        out: dict = {"ok": False, "status": None, "ms": None, "tls_issuer": None,
                     "error": None, "final_url": None, "session_id": None}
        t0 = time.time()
        try:
            r = await client.post(url, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": INIT_PARAMS,
            }, headers=MCP_HEADERS)
            out["status"] = r.status_code
            out["ms"] = int((time.time() - t0) * 1000)
            out["final_url"] = str(r.url)
            out["session_id"] = r.headers.get("mcp-session-id")
            # reachable = server menjawab sesuatu (bukan 5xx / bukan connection error)
            out["ok"] = r.status_code < 500
            body = extract_json(r.text)
            out["_body"] = body
            out["_text"] = r.text[:400]
            # TLS issuer (kalau https & koneksi berhasil)
            if url.startswith("https://"):
                out["tls_issuer"] = self._tls_issuer(domain_of(url))
        except Exception as exc:  # noqa: BLE001
            out["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
            out["ms"] = int((time.time() - t0) * 1000)
        return out

    @staticmethod
    def _tls_issuer(host: str) -> str | None:
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((host, 443), timeout=8) as s:
                with ctx.wrap_socket(s, server_hostname=host) as ss:
                    cert = ss.getpeercert()
            issuer = dict(x[0] for x in cert.get("issuer", []))
            return issuer.get("organizationName") or issuer.get("commonName")
        except Exception:  # noqa: BLE001
            return None

    # ---------------- layer 2: handshake ----------------
    async def _layer2_handshake(self, client: httpx.AsyncClient, url: str,
                                body: dict | None, status: int | None) -> dict:
        out = {"ok": False, "mcp_shaped": False, "auth_required": False,
               "protocol_version": None, "server_info": None,
               "capabilities": None, "error": None}
        if not isinstance(body, dict):
            return out
        result = body.get("result") if "result" in body else None
        if isinstance(result, dict):
            out["mcp_shaped"] = True
            out["protocol_version"] = result.get("protocolVersion")
            si = result.get("serverInfo") or {}
            out["server_info"] = f"{si.get('name')} v{si.get('version')}" if si else None
            out["capabilities"] = sorted((result.get("capabilities") or {}).keys())
            out["ok"] = bool(result.get("protocolVersion"))
        elif "error" in body:
            err = body.get("error") or {}
            out["error"] = json.dumps(err)[:200]
            # server ini BICARA MCP (jsonrpc error) walau menolak tanpa kredensial:
            # itu AUTH_REQUIRED, bukan NOT_MCP.
            out["mcp_shaped"] = ("jsonrpc" in body) or status in (401, 403)
            msg = json.dumps(err).lower()
            out["auth_required"] = status in (401, 403) or any(
                k in msg for k in ("auth", "token", "unauthor", "api key",
                                   "credential", "bearer", "key required"))
        return out

    async def _notify_initialized(self, client: httpx.AsyncClient, url: str,
                                  session_id: str | None) -> None:
        """Kirim notifications/initialized — wajib sebelum tools/list di spec."""
        try:
            await client.post(url, json={
                "jsonrpc": "2.0", "method": "notifications/initialized", "params": {},
            }, headers=mcp_headers(session_id))
        except Exception:  # noqa: BLE001
            pass

    # ---------------- layer 3: tools/list ----------------
    async def _layer3_tools(self, client: httpx.AsyncClient, url: str,
                            session_id: str | None = None) -> dict:
        out = {"ok": False, "count": 0, "tools": [], "schemas_valid": 0,
               "error": None, "status": None}
        try:
            r = await client.post(url, json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
            }, headers=mcp_headers(session_id))
            out["status"] = r.status_code
            data = extract_json(r.text)
            if isinstance(data, dict):
                if "error" in data:
                    out["error"] = json.dumps(data["error"])[:200]
                    return out
                tools = ((data.get("result") or {}).get("tools")) or []
                out["count"] = len(tools)
                out["tools"] = [t.get("name") for t in tools if isinstance(t, dict)][:50]
                valid = 0
                for t in tools:
                    if not isinstance(t, dict):
                        continue
                    if t.get("name") and isinstance(t.get("inputSchema"), dict):
                        valid += 1
                out["schemas_valid"] = valid
                out["ok"] = out["count"] > 0
                out["_raw_tools"] = tools
        except Exception as exc:  # noqa: BLE001
            out["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        return out

    # ---------------- layer 4: reality check ----------------
    async def _layer4_reality(self, client: httpx.AsyncClient, url: str,
                              tools: list[dict],
                              session_id: str | None = None) -> dict:
        """Native reality check: panggil tool read-only, nilai apakah jawabannya
        nyata (bukan refusal / kosong). Cerminan mcp-reality-check; di mode deep
        tool pip yang asli juga dijalankan."""
        out = {"ok": False, "is_fake": False, "auth_gated": False, "called": None,
               "real": None, "reason": None, "probe_status": None, "tried": []}
        safe = [t for t in tools if isinstance(t, dict)
                and (t.get("annotations") or {}).get("readOnlyHint") is not False]
        safe = safe or [t for t in tools if isinstance(t, dict)]
        if not safe:
            out["reason"] = "no tools to call"
            return out

        for tool in safe[:3]:
            name = tool.get("name")
            out["tried"].append(name)
            try:
                r = await client.post(url, json={
                    "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": name, "arguments": {}},
                }, headers=mcp_headers(session_id))
                out["probe_status"] = r.status_code
                data = extract_json(r.text)
                if not isinstance(data, dict):
                    out["reason"] = "unparseable response"
                    continue
                if "error" in data:
                    err = data["error"] or {}
                    code = err.get("code")
                    msg = json.dumps(err).lower()
                    # -32602 / 'arguments' = tool butuh argumen -> tidak bisa
                    # diprobe dengan {}, TAPI bukan fake. Coba tool berikutnya.
                    if code == -32602 or "argument" in msg or "invalid param" in msg \
                            or "requires '" in msg or "invalid_input" in msg \
                            or "bad request" in msg:
                        out["reason"] = f"{name}: needs arguments (unprobeable)"
                        continue
                    # masalah sesi/protokol (-32600, 'session', 'not initialized')
                    # = artefak probe, bukan bukti data palsu.
                    if code == -32600 or "session" in msg or "not initialized" in msg:
                        out["reason"] = f"{name}: protocol/session issue ({json.dumps(err)[:80]})"
                        continue
                    # auth/payment gate -> AUTH_REQUIRED, bukan FAKE
                    if any(k in msg for k in AUTH_MARKERS):
                        out["called"] = name
                        out["auth_gated"] = True
                        out["reason"] = f"{name}: auth/payment gate ({json.dumps(err)[:90]})"
                        continue
                    out["called"] = name
                    out["reason"] = f"tool error: {json.dumps(err)[:120]}"
                    out["is_fake"] = True
                    return out
                content = ((data.get("result") or {}).get("content")) or []
                text = " ".join(
                    (c.get("text") or "") for c in content if isinstance(c, dict)
                )[:800].lower()
                if not text.strip():
                    out["called"] = name
                    out["is_fake"] = True
                    out["reason"] = "empty content (false-green)"
                    return out
                hit = next((m for m in REFUSAL_MARKERS if m in text), None)
                if hit:
                    out["called"] = name
                    out["is_fake"] = True
                    out["reason"] = f"refusal/stub marker: '{hit}'"
                    return out
                out["called"] = name
                out["ok"] = True
                out["real"] = True
                out["reason"] = f"real payload ({len(text)} chars)"
                return out
            except Exception as exc:  # noqa: BLE001
                out["reason"] = f"{type(exc).__name__}: {str(exc)[:100]}"
        if out["called"] is None and out["reason"] and "needs arguments" in out["reason"]:
            out["ok"] = True  # tidak bisa diprobe, tapi bukan fake
        if out["auth_gated"]:
            out["ok"] = True  # tidak bisa diprobe tanpa kredensial, tapi bukan fake
        return out

    # ---------------- layer 5: contract (native) ----------------
    @staticmethod
    def _layer5_contract(tools: list[dict]) -> dict:
        out = {"ok": False, "tools_with_schema": 0, "invalid": [], "error": None}
        invalid = []
        good = 0
        for t in tools:
            if not isinstance(t, dict):
                continue
            name = t.get("name")
            schema = t.get("inputSchema")
            if name and isinstance(schema, dict) and schema.get("type") == "object":
                good += 1
            else:
                invalid.append(name or "<unnamed>")
        out["tools_with_schema"] = good
        out["invalid"] = invalid[:20]
        out["ok"] = good > 0 and len(invalid) == 0
        return out

    # ---------------- layer 6: conformance (native) ----------------
    @staticmethod
    def _layer6_conformance(handshake: dict, tools: dict) -> dict:
        out = {"ok": False, "checks": {}, "error": None}
        supported = {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28"}
        pv = handshake.get("protocol_version")
        out["checks"]["protocol_version_known"] = pv in supported
        out["checks"]["handshake_ok"] = bool(handshake.get("ok"))
        out["checks"]["tools_schema_object"] = tools.get("schemas_valid", 0) > 0
        out["checks"]["server_info_present"] = bool(handshake.get("server_info"))
        out["ok"] = all(out["checks"].values())
        return out

    # ---------------- layer 8: mock vs real (false-green) ----------------
    @staticmethod
    def _layer8_mock(l1: dict, handshake: dict, tools: dict, reality: dict) -> dict:
        """Deteksi 'false-green': endpoint balas 200 tapi tak ada data nyata.
        Implementasi lokal (paket skillsmp 'mock-vs-real-detector' -> 404)."""
        out = {"ok": True, "false_green": False, "signals": []}
        if l1.get("status") == 200 and not handshake.get("ok"):
            out["signals"].append("200 without MCP handshake")
        if l1.get("status") == 200 and handshake.get("ok") and tools.get("count", 0) == 0:
            out["signals"].append("handshake ok but zero tools")
        if reality.get("is_fake"):
            out["signals"].append("reality check failed: " + str(reality.get("reason")))
        if reality.get("called") and reality.get("ok") is False and not reality.get("is_fake"):
            out["signals"].append("tool call inconclusive")
        out["false_green"] = bool(out["signals"])
        return out

    # ---------------- audits ----------------
    async def _audit_drift(self, client: httpx.AsyncClient, url: str) -> dict:
        out = {"drifted": False, "chain": [], "final_host": None, "error": None}
        try:
            r = await client.get(url, follow_redirects=True)
            out["chain"] = [str(h.url) for h in r.history][:5]
            out["final_host"] = domain_of(str(r.url))
            orig = domain_of(url)
            out["drifted"] = bool(out["final_host"]) and out["final_host"] != orig
        except Exception as exc:  # noqa: BLE001
            out["error"] = f"{type(exc).__name__}: {str(exc)[:80]}"
        return out

    async def _audit_mcpjacking(self, url: str) -> dict:
        """DNS resolve (timeout keras) + RDAP expiry opsional.

        RDAP dipanggil hanya bila --rdap diaktifkan: untuk 1000 domain ia
        menghabiskan puluhan menit demi info yang jarang mengubah verdict.
        Yang wajib: DNS resolve — domain yang tidak resolve = kandidat takeover.
        """
        out = {"jackable": False, "domain": None, "resolves": None, "expiry": None,
               "error": None}
        dom = domain_of(url)
        out["domain"] = dom
        if not dom:
            out["error"] = "no domain"
            return out
        try:
            infos = await asyncio.wait_for(
                asyncio.to_thread(socket.getaddrinfo, dom, 443,
                                  proto=socket.IPPROTO_TCP), timeout=6)
            out["resolves"] = len({i[4][0] for i in infos})
        except Exception as exc:  # noqa: BLE001
            out["error"] = f"dns: {type(exc).__name__}"
            # HANYA kegagalan resolusi nama (NXDOMAIN -> socket.gaierror) yang
            # membuktikan domain sudah hilang. Timeout DNS hanyalah lambat.
            out["jackable"] = isinstance(exc, socket.gaierror)
            return out
        if self.rdap:
            try:
                r = await asyncio.wait_for(asyncio.to_thread(
                    httpx.get, f"https://rdap.org/domain/{dom}", timeout=8,
                    follow_redirects=True), timeout=10)
                if r.status_code == 200:
                    for ev in r.json().get("events", []):
                        if ev.get("eventAction") == "expiration":
                            out["expiry"] = ev.get("eventDate")
                    if out["expiry"]:
                        exp = datetime.fromisoformat(out["expiry"].replace("Z", "+00:00"))
                        out["jackable"] = exp < datetime.now(timezone.utc)
            except Exception as exc:  # noqa: BLE001
                out["error"] = (out["error"] or "") + f" rdap:{type(exc).__name__}"
        return out

    @staticmethod
    def _audit_unauth(l1: dict, handshake: dict, tools: dict, no_auth: bool) -> dict:
        """tools/list tanpa auth berhasil => exposure. Ini nyata: kita memang
        tidak mengirim Authorization sama sekali."""
        exposed = bool(handshake.get("ok")) and tools.get("count", 0) > 0
        return {"exposed": exposed, "declared_no_auth": no_auth,
                "tools_visible": tools.get("count", 0)}

    # ---------------- external tools (deep) ----------------
    def _tool_reality(self, url: str) -> dict:
        if not REALITY_LAUNCHER.exists():
            return {"ok": False, "error": "launcher missing"}
        rc, so, se = _run([str(PY312), str(REALITY_LAUNCHER), "--url", url, "--json",
                           "--timeout", "20"], self.tool_timeout,
                          env={"PYTHONPATH": str(PYLIBS)})
        data = extract_json(so) or {}
        return {"ok": rc == 0, "rc": rc, "fake_count": data.get("fake_success_count",
                data.get("fake_count")), "real_count": data.get("real_count"),
                "raw": data if data else so[:300], "stderr": se[:200]}

    def _tool_contract(self, url: str, tag: str) -> dict:
        entry = NODE_ENTRIES["mcp-contract-check"]
        if not entry.exists():
            return {"ok": False, "error": "entry missing"}
        snap = TOOLS / f"_contract_{tag}.json"
        rc, so, se = _run([str(NODE), str(entry), "--url", url, "--fuzz",
                           "--save-contract", str(snap)], self.tool_timeout)
        tools = []
        if snap.exists():
            try:
                tools = json.loads(snap.read_text(encoding="utf-8")).get("tools", [])
            except ValueError:
                pass
        return {"ok": rc == 0 and len(tools) > 0, "rc": rc, "tool_count": len(tools),
                "stdout": so.strip()[:200], "stderr": se[:200]}

    def _tool_spec(self, url: str) -> dict:
        entry = NODE_ENTRIES["mcp-spec-test"]
        if not entry.exists():
            return {"ok": False, "error": "entry missing"}
        rc, so, se = _run([str(NODE), str(entry), "-u", url,
                           "--spec-version", "2026-07-28", "--no-interactive",
                           "--no-browser"], self.tool_timeout)
        text = so + se
        passed = failed = 0
        m = re.search(r"(\d+)\s+passed\s+(\d+)\s+failed", text)
        if m:
            passed, failed = int(m.group(1)), int(m.group(2))
        conformant = "Verdict: not conformant" not in text and passed > 0
        return {"ok": conformant, "rc": rc, "passed": passed, "failed": failed,
                "verdict": "conformant" if conformant else "not conformant",
                "tail": text[-400:]}

    def _tool_doctor(self, url: str) -> dict:
        entry = NODE_ENTRIES["mcpdoctor"]
        if not entry.exists():
            return {"ok": False, "error": "entry missing"}
        rc, so, se = _run([str(NODE), str(entry), "test",
                           "--transport", "streamable-http", "--url", url,
                           "--format", "json"], self.tool_timeout)
        data = extract_json(so) or {}
        return {"ok": bool(data), "rc": rc, "score": data.get("score"),
                "grade": data.get("grade"), "passed": data.get("passed"),
                "failed": data.get("failed"), "total": data.get("total"),
                "stderr": se[:150]}

    def _tool_probe(self, url: str) -> dict:
        entry = NODE_ENTRIES["mcp-probe"]
        if not entry.exists():
            return {"ok": False, "error": "entry missing"}
        rc, so, se = _run([str(NODE), str(entry), "--url", url, "--json", "--quiet"],
                          self.tool_timeout)
        data = extract_json(so) or {}
        results = data.get("results") or []
        passed = sum(1 for r in results if r.get("status") == "pass")
        failed = sum(1 for r in results if r.get("status") == "fail")
        return {"ok": passed > 0, "rc": rc, "passed": passed,
                "failed": failed, "total": len(results),
                "server": (data.get("server") or {}).get("name")}

    # ---------------- classification ----------------
    @staticmethod
    def _classify(r: dict) -> str:
        hs = r.get("layer2_handshake") or {}
        jack = r.get("audit_mcpjacking") or {}
        if not (r.get("layer1_reachable") or {}).get("ok"):
            # Domain TIDAK resolve = entri registry basi yang domainnya sudah
            # hilang -> kandidat takeover (MCPJacking). Ini temuan keamanan
            # yang lebih berguna daripada sekadar "DEAD", jadi didahulukan.
            if jack.get("jackable"):
                return "JACKABLE"
            return "DEAD"
        if not hs.get("ok"):
            if jack.get("jackable"):
                return "JACKABLE"
            if (r.get("audit_silent_drift") or {}).get("drifted"):
                return "DRIFT"
            if hs.get("mcp_shaped") and hs.get("auth_required"):
                return "AUTH_REQUIRED"
            return "NOT_MCP"
        # handshake MCP BERHASIL -> konektor hidup; nilai kualitasnya
        ua = r.get("audit_unauth") or {}
        if ua.get("exposed") and not ua.get("declared_no_auth"):
            return "UNAUTH_EXPOSED"
        l4 = r.get("layer4_reality") or {}
        if l4.get("auth_gated"):
            return "AUTH_REQUIRED"  # tool butuh kredensial -> bukan FAKE
        if l4.get("is_fake"):
            return "FAKE"
        spec = r.get("tool_spec_test") or {}
        if spec.get("ok") is False and spec.get("passed") is not None:
            return "NON_CONFORMANT"
        if not (r.get("layer6_conformance") or {}).get("ok"):
            return "NON_CONFORMANT"
        score = r.get("score", 0)
        if score >= 80:
            return "REAL_GRADE_A"
        if score >= 60:
            return "REAL_GRADE_B"
        return "REAL_GRADE_C"

    @staticmethod
    def _score(layers: dict, deep: dict | None) -> int:
        """Skor 0-100. Bila mcpdoctor tersedia (deep), pakai skornya."""
        if deep and isinstance(deep.get("score"), (int, float)):
            return int(deep["score"])
        s = 0
        for key, pts in (("layer1_reachable", 10), ("layer2_handshake", 20),
                         ("layer3_tools", 15), ("layer4_reality", 20),
                         ("layer5_contract", 15), ("layer6_conformance", 20)):
            if (layers.get(key) or {}).get("ok"):
                s += pts
        return min(s, 100)

    # ---------------- one connector ----------------
    async def verify_connector(self, connector: dict,
                               client: httpx.AsyncClient) -> dict:
        url = connector.get("endpoint_url") or connector.get("url") or ""
        cid = connector.get("id") or url
        r: dict = {
            "connector_id": cid,
            "url": url,
            "source": connector.get("source") or "glama-connector",
            "declared_auth": connector.get("auth_type") or "",
            "declared_no_auth": bool(connector.get("no_auth")),
            "verified_at": _now(),
        }
        if not url.startswith("http"):
            r.update({"layer1_reachable": {"ok": False, "error": "no http url"},
                      "layer2_handshake": {}, "layer3_tools": {}, "layer4_reality": {},
                      "layer5_contract": {}, "layer6_conformance": {},
                      "layer8_mock_check": {}, "audit_mcpjacking": {},
                      "audit_silent_drift": {}, "audit_unauth": {}})
            r["classification"] = "DEAD"
            return r

        l1 = await self._layer1_reachable(client, url)
        body = l1.pop("_body", None)
        l1.pop("_text", None)
        sid = l1.get("session_id")
        l2 = await self._layer2_handshake(client, url, body, l1.get("status"))
        if l2.get("ok"):
            await self._notify_initialized(client, url, sid)
        l3 = await self._layer3_tools(client, url, sid)
        raw_tools = l3.pop("_raw_tools", []) or []
        l4 = await self._layer4_reality(client, url, raw_tools, sid)
        l5 = self._layer5_contract(raw_tools)
        l6 = self._layer6_conformance(l2, l3)
        l8 = self._layer8_mock(l1, l2, l3, l4)
        drift = await self._audit_drift(client, url)
        jack = await self._audit_mcpjacking(url)
        unauth = self._audit_unauth(l1, l2, l3, r["declared_no_auth"])

        r.update({
            "layer1_reachable": l1, "layer2_handshake": l2, "layer3_tools": l3,
            "layer4_reality": l4, "layer5_contract": l5, "layer6_conformance": l6,
            "layer8_mock_check": l8, "audit_mcpjacking": jack,
            "audit_silent_drift": drift, "audit_unauth": unauth,
        })

        deep_info: dict | None = None
        if self.deep and l2.get("ok"):
            tag = re.sub(r"[^a-zA-Z0-9]", "_", cid)[-40:]
            # jalankan 5 tool NYATA secara paralel: waktu per konektor = max(tool),
            # bukan jumlah(tool). Ini yang membuat 649 konektor tetap < 2 jam.
            (r["tool_reality_check"], r["tool_contract_check"], r["tool_spec_test"],
             r["tool_mcpdoctor"], r["tool_mcp_probe"]) = await asyncio.gather(
                asyncio.to_thread(self._tool_reality, url),
                asyncio.to_thread(self._tool_contract, url, tag),
                asyncio.to_thread(self._tool_spec, url),
                asyncio.to_thread(self._tool_doctor, url),
                asyncio.to_thread(self._tool_probe, url),
            )
            if r["tool_reality_check"].get("fake_count"):
                l4["is_fake"] = True
                l4["reason"] = "mcp-reality-check: fake success detected"
            doc = r["tool_mcpdoctor"]
            # skor mcpdoctor hanya dipakai bila ia BENAR-BENAR menjalankan check
            # (total>0). total==0 = mcpdoctor gagal terhubung, bukan "konektor
            # jelek" — memakai 0 di situ akan salah menurunkan grade.
            if (doc.get("total") or 0) > 0 and doc.get("score") is not None:
                deep_info = {"score": doc["score"]}

        r["score"] = self._score(r, deep_info)
        r["risk_flags"] = [f for f, on in (
            ("JACKABLE", jack.get("jackable")),
            ("DRIFT", drift.get("drifted")),
        ) if on]
        r["classification"] = self._classify(r)
        return r

    async def run(self, connectors: list[dict]) -> list[dict]:
        sem = asyncio.Semaphore(self.concurrency)
        # tool eksternal dijalankan via asyncio.to_thread; executor default hanya
        # ~8 worker sehingga 5 tool x 12 konektor akan terserialisasi. Naikkan.
        from concurrent.futures import ThreadPoolExecutor
        pool = ThreadPoolExecutor(max_workers=self.concurrency * 6 + 8)
        asyncio.get_running_loop().set_default_executor(pool)
        limits = httpx.Limits(max_connections=self.concurrency * 2,
                              max_keepalive_connections=self.concurrency)
        async with httpx.AsyncClient(follow_redirects=False, timeout=15,
                                     limits=limits,
                                     verify=self.verify_tls) as client:
            done = 0
            total = len(connectors)

            async def one(c: dict) -> dict:
                nonlocal done
                async with sem:
                    try:
                        r = await asyncio.wait_for(
                            self.verify_connector(c, client),
                            timeout=self.connector_timeout)
                    except asyncio.TimeoutError:
                        r = {"connector_id": c.get("id"), "url": c.get("endpoint_url"),
                             "source": c.get("source"), "classification": "DEAD",
                             "layer1_reachable": {"ok": False, "error": "connector timeout"},
                             "score": 0, "timeout": True}
                    except Exception as exc:  # noqa: BLE001
                        r = {"connector_id": c.get("id"), "url": c.get("endpoint_url"),
                             "classification": "DEAD",
                             "error": f"{type(exc).__name__}: {exc}"}
                    done += 1
                    if done % 100 == 0 or done == total:
                        print(f"  ... {done}/{total} verified", flush=True)
                    return r
            self.results = await asyncio.gather(*[one(c) for c in connectors])
        pool.shutdown(wait=False)
        return self.results


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------

def summarize(results: list[dict]) -> dict:
    from collections import Counter
    by = Counter(r.get("classification", "UNKNOWN") for r in results)
    return {
        "total": len(results),
        "by_classification": dict(sorted(by.items(), key=lambda kv: -kv[1])),
        "generated_at": _now(),
    }


def write_report(results: list[dict], summary: dict, out_json: Path,
                 out_md: Path) -> None:
    out_json.write_text(json.dumps({"summary": summary, "results": results},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [
        "# Connector 8-Layer Verification Report",
        "",
        f"- generated: {summary['generated_at']}",
        f"- total verified: {summary['total']}",
        "",
        "## Classification",
        "",
        "| classification | count |",
        "|---|---|",
    ]
    for k, v in summary["by_classification"].items():
        lines.append(f"| {k} | {v} |")
    lines += ["", "## Sample (first 30)", "",
              "| connector | class | status | score | tools |", "|---|---|---|---|---|"]
    for r in results[:30]:
        lines.append("| {} | {} | {} | {} | {} |".format(
            r.get("connector_id"), r.get("classification"),
            (r.get("layer1_reachable") or {}).get("status"),
            r.get("score"), (r.get("layer3_tools") or {}).get("count")))
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_connectors(limit: int | None, source: str,
                    ids_file: str | None = None) -> list[dict]:
    path = ROOT / "glama_connectors.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    items = [v for v in data.values() if isinstance(v, dict) and v.get("endpoint_url")]
    if ids_file:
        wanted = set(json.loads((ROOT / ids_file).read_text(encoding="utf-8")))
        items = [v for v in items if v.get("id") in wanted]
    if limit:
        items = items[:limit]
    return items


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="8-layer connector verification")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--ids-file", default=None,
                    help="JSON list of connector ids to verify (subset)")
    ap.add_argument("--concurrency", type=int, default=12)
    ap.add_argument("--deep", action="store_true",
                    help="jalankan tool eksternal nyata (layer 4-7)")
    ap.add_argument("--tool-timeout", type=float, default=60.0)
    ap.add_argument("--out", default="connector_verification_results.json")
    ap.add_argument("--md", default="docs/connector-verification-report.md")
    ap.add_argument("--no-verify-tls", action="store_true")
    ap.add_argument("--rdap", action="store_true",
                    help="cek expiry domain via RDAP (lambat, default mati)")
    ap.add_argument("--connector-timeout", type=float, default=45.0)
    args = ap.parse_args()

    connectors = load_connectors(args.limit, "glama-connector", args.ids_file)
    h = ConnectorVerificationHarness(concurrency=args.concurrency, deep=args.deep,
                                     tool_timeout=args.tool_timeout,
                                     verify_tls=not args.no_verify_tls,
                                     rdap=args.rdap,
                                     connector_timeout=args.connector_timeout)
    t0 = time.time()
    results = asyncio.run(h.run(connectors))
    summary = summarize(results)
    summary["elapsed_s"] = round(time.time() - t0, 1)
    summary["deep"] = args.deep
    summary["concurrency"] = args.concurrency
    write_report(results, summary, ROOT / args.out, ROOT / args.md)
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
