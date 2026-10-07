"""sandbox_runner.py — harness E2E sandbox untuk Katalir (7 Okt 2026).

APA YANG DIUJI
--------------
Bukan simulasi: harness ini menjalankan **`StatefulOrchestrator` yang asli**
(mesin DAG produksi, termasuk self-healing) dan menyisipkan satu titik
panggilan keluar yang melewati seluruh rantai zero-trust:

    config node  ->  ${auth.X} placeholder            (agent hanya lihat ini)
                 ->  resolve_for_egress()              (nilai asli muncul DI SINI saja)
                 ->  mock server (in-process ASGI)     (tidak ada kredensial asli)
                 ->  mask_known_values()               (scoped secrets: cocok NILAI)
                 ->  redact_agent_output()             (pola + canary, fail-closed)
                 ->  assert_no_leak()                  (gerbang terakhir)

Setiap langkah punya bukti mentah di keluaran `main()`.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SANDBOX = Path(__file__).resolve().parent
for _p in (str(ROOT), str(SANDBOX)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import agent_redactor as ar  # noqa: E402
import credential_proxy as cp  # noqa: E402
import mock_server  # noqa: E402
from execution_engine import (  # noqa: E402
    FlowGraph, NodeKind, StatefulOrchestrator,
)
from self_healing import SelfHealingAgent  # noqa: E402

# ---------------------------------------------------------------------------
# Kredensial TEST (fiktif). Tidak ada nilai produksi di sini.
# ---------------------------------------------------------------------------
TEST_CREDS = {
    "telegram_bot": "7000000001:TESTONLY_abcdefghijklmnopqrstuvwxyz012345678",
    "telegram_chat": "TESTCHAT_987654321",
    "gemini_api": "AIzaTESTONLY_abcdefghijklmnopqrstuvwxyz0123",
    "sheets_id": "TESTSHEET_1AbCdEfGhIjKlMnOpQrStUvWxYz012345",
    "github_token": "ghp_TESTONLYabcdefghijklmnopqrstuvwxyz01",
}


def seed_test_credentials() -> dict[str, str]:
    """Isi store test + canary. Nilai fiktif, tidak pernah menyentuh produksi."""
    cp.clear_store()
    canaries: dict[str, str] = {}
    for key, value in TEST_CREDS.items():
        canaries[key] = cp.put_test_credential(key, value, canary=True)
    return canaries


# ---------------------------------------------------------------------------
# TITIK EGRESS SANDBOX
# ---------------------------------------------------------------------------
class SandboxEgress:
    """Executor MCP pengganti: satu-satunya tempat kredensial jadi nyata."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.leak_checks = 0

    async def __call__(self, orch, node, inp) -> dict:
        # `{{...}}` diresolv mesin; `${auth.X}` DIBIARKAN (sintaks berbeda).
        cfg = orch._resolve_cfg(node.data.config or {}, where=f"node '{node.id}'")
        op = cfg.pop("op", None)
        # --- EGRESS: satu-satunya resolusi nilai asli ---
        egress = cp.resolve_cfg_for_egress(cfg)
        self.calls.append({
            "node": node.id,
            "op": op,
            "args_masked": cp.mask_known_values(egress),
        })
        raw = await self._dispatch(op, egress)
        # --- jalur pulang: mask nilai -> redact pola -> gerbang terakhir ---
        safe = ar.redact_agent_output(cp.mask_known_values(raw))
        cp.assert_no_leak(safe, where=f"output node '{node.id}'")
        self.leak_checks += 1
        return safe

    async def _dispatch(self, op: str | None, args: dict) -> dict:
        async with mock_server.client() as c:
            if op == "telegram_send":
                r = await c.get("/mock/telegram/sendMessage", params={
                    "chat_id": str(args.get("chat_id", "")),
                    "text": str(args.get("text", "")),
                })
            elif op == "telegram_echo_token":
                r = await c.get("/mock/telegram/echo_token",
                                params={"token": str(args.get("token", ""))})
            elif op == "sheets_write":
                r = await c.get("/mock/sheets/write", params={
                    "spreadsheet_id": str(args.get("spreadsheet_id", "")),
                    "range": str(args.get("range", "A1")),
                    "values": str(args.get("values", "")),
                })
            elif op == "github_commit":
                r = await c.post("/mock/github/commit", json={
                    "repo": str(args.get("repo", "")),
                    "path": str(args.get("path", "")),
                    "content": str(args.get("content", "")),
                })
            elif op == "http_echo":
                r = await c.get("/mock/http/echo",
                                params={"url": str(args.get("url", ""))})
            elif op == "http_fail":
                r = await c.get("/mock/http/fail",
                                params={"code": int(args.get("code", 500))})
            elif op == "http_flaky":
                r = await c.get("/mock/http/flaky", params={
                    "key": str(args.get("key", "default")),
                    "fail_times": int(args.get("fail_times", 2)),
                })
            else:
                raise RuntimeError(f"op sandbox tidak dikenal: {op!r}")

            if r.status_code >= 400:
                # Sama seperti `tools.http_request` (BUG-B2): >=400 = GAGAL,
                # supaya self-healing mengklasifikasi dan node ditandai error.
                raise RuntimeError(
                    f"HTTP {r.status_code} dari sandbox.mock: {r.text[:200]}")
            return r.json()


def sandbox_agent_executor(prompts: list[str] | None = None):
    """Agent deterministik (tanpa LLM) — untuk menguji orkestrasi multi-agent."""
    def _mk():
        async def _exec(orch, node, inp):
            cfg = orch._resolve_cfg(node.data.config or {},
                                    where=f"node '{node.id}'")
            reply = cfg.get("prompt") or cfg.get("system_prompt") or "ok"
            if prompts is not None:
                prompts.append(f"{node.id}:{reply}")
            return ar.redact_agent_output({
                "type": "agent.think", "status": "success",
                "reply": reply, "provider": "sandbox-stub",
            })
        return _exec
    return _mk


def make_graph(nodes: list[tuple[str, dict]],
               edges: list[tuple[str, str]]) -> FlowGraph:
    return FlowGraph(
        nodes=[{"id": nid, "data": data} for nid, data in nodes],
        edges=[{"id": f"e{i}", "source": s, "target": t}
               for i, (s, t) in enumerate(edges)],
    )


def build_orch(graph: FlowGraph, trigger_input: dict,
               agent_prompts: list[str] | None = None) -> StatefulOrchestrator:
    orch = StatefulOrchestrator(
        graph, trigger_input=trigger_input,
        healing_factory=lambda: SelfHealingAgent(search_enabled=False))
    orch.EXECUTORS = dict(orch.EXECUTORS)
    orch.EXECUTORS[NodeKind.MCP] = SandboxEgress()
    orch.EXECUTORS[NodeKind.AGENT] = sandbox_agent_executor(agent_prompts)()
    return orch


# ---------------------------------------------------------------------------
# 10 TEST WORKFLOW (MODE MOCK)
# ---------------------------------------------------------------------------
def t01_simple() -> tuple:
    g = make_graph(
        [("t", {"kind": "trigger", "label": "webhook"}),
         ("tg", {"kind": "mcp", "label": "telegram", "config": {
             "op": "telegram_send",
             "chat_id": "${auth.telegram_chat}",
             "text": "Halo dari sandbox: {{t.context.text}}"}}),
         ],
        [("t", "tg")])
    return g, {"text": "pesan-1"}, {"tg": "completed"}


def t02_medium_chain() -> tuple:
    g = make_graph(
        [("t", {"kind": "trigger", "label": "webhook"}),
         ("h", {"kind": "mcp", "label": "http", "config": {
             "op": "http_echo", "url": "https://example.test/post/1"}}),
         ("tg", {"kind": "mcp", "label": "telegram", "config": {
             "op": "telegram_send",
             "chat_id": "${auth.telegram_chat}",
             "text": "judul={{h.data.title}}"}}),
         ],
        [("t", "h"), ("h", "tg")])
    return g, {"text": "x"}, {"h": "completed", "tg": "completed"}


def t03_condition_branch() -> tuple:
    g = make_graph(
        [("t", {"kind": "trigger", "label": "webhook"}),
         ("gate", {"kind": "mcp", "label": "if-valid", "config": {
             "condition": "{{t.context.status}} == 'valid'",
             "op": "telegram_send",
             "chat_id": "${auth.telegram_chat}",
             "text": "valid"}}),
         # CATATAN SEMANTIK (temuan, lihat laporan §7): `else_condition`
         # BUKAN cabang else — ia gerbang AND tambahan (`_condition_gate`
         # mensyaratkan SEMUA kunci truthy). Cabang else yang sebenarnya
         # ditulis sebagai negasi eksplisit di `condition`.
         ("else", {"kind": "mcp", "label": "if-invalid", "config": {
             "condition": "{{t.context.status}} == 'invalid'",
             "op": "telegram_send",
             "chat_id": "${auth.telegram_chat}",
             "text": "invalid"}}),
         ],
        [("t", "gate"), ("t", "else")])
    return g, {"status": "valid"}, {"gate": "completed", "else": "completed"}


def t04_complex_sheets() -> tuple:
    g = make_graph(
        [("t", {"kind": "trigger", "label": "webhook"}),
         ("h", {"kind": "mcp", "label": "http", "config": {
             "op": "http_echo", "url": "https://example.test/items"}}),
         ("sh", {"kind": "mcp", "label": "sheets", "config": {
             "op": "sheets_write",
             "spreadsheet_id": "${auth.sheets_id}",
             "range": "A1:B1",
             "values": "{{h.data.title}},{{t.context.text}}"}}),
         ("tg", {"kind": "mcp", "label": "telegram", "config": {
             "op": "telegram_send",
             "chat_id": "${auth.telegram_chat}",
             "text": "cells={{sh.updatedCells}}"}}),
         ],
        [("t", "h"), ("h", "sh"), ("sh", "tg")])
    return g, {"text": "baris1"}, {"h": "completed", "sh": "completed", "tg": "completed"}


def t05_multi_agent() -> tuple:
    g = make_graph(
        [("t", {"kind": "trigger", "label": "webhook"}),
         ("a1", {"kind": "agent", "label": "researcher", "config": {
             "prompt": "riset topik"}}),
         ("a2", {"kind": "agent", "label": "writer", "config": {
             "prompt": "tulis dari {{a1.reply}}"}}),
         ],
        [("t", "a1"), ("a1", "a2")])
    return g, {"text": "topik"}, {"a1": "completed", "a2": "completed"}


def t06_mcp_tool() -> tuple:
    g = make_graph(
        [("t", {"kind": "trigger", "label": "webhook"}),
         ("m", {"kind": "mcp", "label": "mcp-tool", "config": {
             "op": "github_commit",
             "repo": "sandbox/demo",
             "path": "docs/note.md",
             "content": "commit dari sandbox"}}),
         ],
        [("t", "m")])
    return g, {}, {"m": "completed"}


def t07_webhook_payload() -> tuple:
    g = make_graph(
        [("t", {"kind": "trigger", "label": "webhook"}),
         ("tg", {"kind": "mcp", "label": "telegram", "config": {
             "op": "telegram_send",
             "chat_id": "${auth.telegram_chat}",
             "text": "halo {{t.context.text}}"}}),
         ],
        [("t", "tg")])
    return g, {"text": "dari-webhook"}, {"tg": "completed"}


def t08_hard_github() -> tuple:
    g = make_graph(
        [("t", {"kind": "trigger", "label": "webhook"}),
         ("c", {"kind": "mcp", "label": "commit", "config": {
             "op": "github_commit",
             "repo": "sandbox/demo",
             "path": "src/app.py",
             "content": "print('{{t.context.text}}')"}}),
         ("tg", {"kind": "mcp", "label": "notify", "config": {
             "op": "telegram_send",
             "chat_id": "${auth.telegram_chat}",
             "text": "sha={{c.sha}}"}}),
         ],
        [("t", "c"), ("c", "tg")])
    return g, {"text": "hi"}, {"c": "completed", "tg": "completed"}


def t09_error_recovery() -> tuple:
    g = make_graph(
        [("t", {"kind": "trigger", "label": "webhook"}),
         ("bad", {"kind": "mcp", "label": "dead-endpoint", "config": {
             "op": "http_fail", "code": 500}}),
         ],
        [("t", "bad")])
    return g, {}, {"bad": "error"}


def t10_full_orchestration() -> tuple:
    g = make_graph(
        [("t", {"kind": "trigger", "label": "webhook"}),
         ("gate", {"kind": "mcp", "label": "if-valid", "config": {
             "condition": "{{t.context.status}} == 'valid'",
             "op": "http_echo", "url": "https://example.test/gate"}}),
         ("sh", {"kind": "mcp", "label": "sheets", "config": {
             "op": "sheets_write",
             "spreadsheet_id": "${auth.sheets_id}",
             "range": "A1",
             "values": "{{gate.data.title}}"}}),
         ("c", {"kind": "mcp", "label": "commit", "config": {
             "op": "github_commit",
             "repo": "sandbox/demo", "path": "log.txt",
             "content": "cells={{sh.updatedCells}}"}}),
         ("tg", {"kind": "mcp", "label": "notify", "config": {
             "op": "telegram_send",
             "chat_id": "${auth.telegram_chat}",
             "text": "sha={{c.sha}}"}}),
         ],
        [("t", "gate"), ("gate", "sh"), ("sh", "c"), ("c", "tg")])
    return g, {"status": "valid", "text": "orchestrasi"}, {
        "gate": "completed", "sh": "completed", "c": "completed", "tg": "completed"}


TESTS = [
    ("TEST #1  Simple  — Trigger -> Telegram (mock)", t01_simple),
    ("TEST #2  Medium  — HTTP -> Extract -> Telegram (mock)", t02_medium_chain),
    ("TEST #3  Medium  — Condition + Branch (mock)", t03_condition_branch),
    ("TEST #4  Complex — Multi-step + Sheets (mock)", t04_complex_sheets),
    ("TEST #5  Complex — Multi-Agent (mock)", t05_multi_agent),
    ("TEST #6  Advanced— MCP Tool (mock)", t06_mcp_tool),
    ("TEST #7  Advanced— Webhook payload (mock)", t07_webhook_payload),
    ("TEST #8  Hard    — GitHub Commit (mock)", t08_hard_github),
    ("TEST #9  Hard    — Error Recovery (mock)", t09_error_recovery),
    ("TEST #10 VeryHard— Full Orchestration (mock)", t10_full_orchestration),
]


def run_one(name: str, builder) -> dict:
    """Jalankan satu workflow; kembalikan bukti mentah + verdict."""
    mock_server.reset_flaky()
    graph, trigger_input, expect_states = builder()
    prompts: list[str] = []
    orch = build_orch(graph, trigger_input, agent_prompts=prompts)
    egress: SandboxEgress = orch.EXECUTORS[NodeKind.MCP]

    steps: list = []
    error = None

    async def _on_step(step):
        # WAJIB async: `_run_node` melakukan `await on_step(step)`.
        steps.append(step.model_copy(deep=True))

    t0 = time.monotonic()
    try:
        asyncio.run(orch.run(on_step=_on_step))
    except Exception as exc:  # noqa: BLE001 - diharapkan pada test error
        error = f"{type(exc).__name__}: {exc}"
    duration = round(time.monotonic() - t0, 2)

    states = dict(orch.states)
    ok_states = all(states.get(nid) == want for nid, want in expect_states.items())

    # Gerbang kebocoran: TIDAK ADA nilai kredensial test di output mana pun.
    leaks: list[str] = []
    for nid, out in orch.outputs.items():
        try:
            cp.assert_no_leak(json.dumps(out, default=str), where=f"output {nid}")
        except Exception as exc:  # noqa: BLE001
            leaks.append(f"{nid}: {exc}")

    canary_hits = [nid for nid, out in orch.outputs.items()
                   if ar.scan_canary(json.dumps(out, default=str))]

    ok = ok_states and not leaks and not canary_hits
    if name.startswith("TEST #9"):
        ok = ok and error is not None          # error recovery HARUS gagal jujur

    return {
        "name": name,
        "ok": ok,
        "duration_s": duration,
        "states": states,
        "expected": expect_states,
        "error": error,
        "leaks": leaks,
        "canary_hits": canary_hits,
        "egress_calls": len(egress.calls),
        "leak_checks": egress.leak_checks,
        "outputs": {k: v for k, v in orch.outputs.items()},
        "steps": [(s.node_id, s.status) for s in steps],
        "agent_prompts": prompts,
    }


def run_all() -> list[dict]:
    seed_test_credentials()
    ar.reset_stats()
    return [run_one(name, builder) for name, builder in TESTS]


def main() -> int:
    results = run_all()
    passed = sum(1 for r in results if r["ok"])
    print("=" * 78)
    print("E2E WORKFLOW TEST — MOCK MODE (sandbox, in-process)")
    print("=" * 78)
    for r in results:
        mark = "PASS" if r["ok"] else "FAIL"
        print(f"\n[{mark}] {r['name']}  ({r['duration_s']}s)")
        print(f"    states   : {r['states']}  (harap {r['expected']})")
        print(f"    egress   : {r['egress_calls']} panggilan · "
              f"{r['leak_checks']} gerbang anti-bocor")
        if r["steps"]:
            print(f"    steps    : {r['steps']}")
        if r["error"]:
            print(f"    error    : {r['error'][:160]}")
        if r["leaks"]:
            print(f"    LEAK     : {r['leaks']}")
        if r["canary_hits"]:
            print(f"    CANARY   : {r['canary_hits']}")
        print(f"    output   : {json.dumps(r['outputs'], default=str)[:300]}")
    print("\n" + "-" * 78)
    print(f"RINGKASAN: {passed}/{len(results)} PASS")
    print(f"Statistik redaksi: {ar.get_stats()}")
    print("-" * 78)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
