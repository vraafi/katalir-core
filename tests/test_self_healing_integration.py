"""Integrasi self-healing ke execution engine.

INI test yang membuktikan modul healing bukan dead code. Test unit di
`test_self_healing.py` hanya menguji kelasnya sendiri; test ini
menjalankan workflow sungguhan lewat `StatefulOrchestrator.run()` dan
menghitung percobaan yang benar-benar terjadi.
"""
import asyncio
import unittest

from execution_engine import (
    FlowGraph, NodeKind, StatefulOrchestrator, ExecutionStep,
)
from self_healing import SelfHealingAgent


def make_graph() -> FlowGraph:
    return FlowGraph(
        nodes=[
            {"id": "t1", "data": {"kind": "trigger", "label": "start"}},
            {"id": "a1", "data": {"kind": "agent", "label": "worker"}},
        ],
        edges=[{"id": "e1", "source": "t1", "target": "a1"}],
    )


def make_orchestrator(executor, healing_factory=None) -> StatefulOrchestrator:
    """Executor agent diganti fungsi yang dikontrol test; trigger apa adanya."""
    orch = StatefulOrchestrator(
        make_graph(), trigger_input={}, healing_factory=healing_factory)
    orch.EXECUTORS = dict(orch.EXECUTORS)
    orch.EXECUTORS[NodeKind.AGENT] = executor
    return orch


def no_network_healing() -> SelfHealingAgent:
    """Healing agent tanpa jaringan: keputusan tetap rules, Search dimatikan."""
    return SelfHealingAgent(search_enabled=False)


def spy_healing(counter: dict) -> callable:
    """Factory yang membungkus handle_failure dan menghitung pemanggilannya."""
    def factory():
        base = no_network_healing()
        original = base.handle_failure

        async def wrapped(**kw):
            counter["n"] += 1
            return await original(**kw)
        base.handle_failure = wrapped  # type: ignore[assignment]
        return base
    return factory


class TestRetryActuallyHappens(unittest.TestCase):
    def test_transient_error_recovers_before_max(self):
        """503 dua kali lalu sukses -> workflow harus SELESAI."""
        calls = {"n": 0}

        async def flaky(orch, node, inp):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise RuntimeError("503 Service Unavailable")
            return {"ok": True}

        orch = make_orchestrator(flaky, no_network_healing)
        steps = asyncio.run(orch.run())

        self.assertEqual(calls["n"], 3, "harus mencoba 3x lalu berhasil")
        self.assertEqual(orch.states["a1"], "completed")
        self.assertEqual(orch.outputs["a1"], {"ok": True})
        self.assertEqual(len([s for s in steps if s.status == "retrying"]), 2,
                         "tiap percobaan gagal harus tercatat")

    def test_retry_step_carries_healing_payload(self):
        """UI butuh tahu kenapa retry, bukan cuma bahwa retry terjadi."""
        calls = {"n": 0}

        async def flaky(orch, node, inp):
            calls["n"] += 1
            if calls["n"] <= 1:
                raise RuntimeError("503 Service Unavailable")
            return {"ok": True}

        orch = make_orchestrator(flaky, no_network_healing)
        steps = asyncio.run(orch.run())

        healing = [s for s in steps if s.status == "retrying"][0].output["healing"]
        for key in ("action", "category", "attempt", "max_attempts",
                    "reason", "delay_ms", "trace", "suggestions"):
            self.assertIn(key, healing)
        self.assertEqual(healing["action"], "retry")
        self.assertEqual(healing["attempt"], 1)
        self.assertEqual(healing["max_attempts"], 3)   # S8: 5 -> 3

    def test_on_step_sees_every_retry(self):
        """Callback on_step yang dipakai pencatat log harus melihat healing."""
        seen: list[str] = []
        calls = {"n": 0}

        async def flaky(orch, node, inp):
            calls["n"] += 1
            if calls["n"] <= 3:
                raise RuntimeError("503 Service Unavailable")
            return {"ok": True}

        orch = make_orchestrator(flaky, no_network_healing)

        async def on_step(step: ExecutionStep):
            seen.append(f"{step.node_id}:{step.status}")

        asyncio.run(orch.run(on_step=on_step))
        self.assertEqual(len([s for s in seen if s.endswith(":retrying")]), 3,
                         "on_step harus menerima setiap percobaan, bukan hanya hasil akhir")


class TestEscalateAndAbort(unittest.TestCase):
    def test_persistent_5xx_escalates_after_three(self):
        calls = {"n": 0}

        async def always_503(orch, node, inp):
            calls["n"] += 1
            raise RuntimeError("503 Service Unavailable")

        orch = make_orchestrator(always_503, no_network_healing)

        async def go():
            await orch.run()

        with self.assertRaises(RuntimeError):
            asyncio.run(go())
        # S8 (7 Okt 2026): 3 percobaan gagal + 1 yang escalate = 4 pemanggilan
        # (dulu 5 + 1 = 6). Batas 3 percobaan + anggaran wall-clock 30s
        # membuat node berakhir `error` dengan cepat, bukan menggantung.
        self.assertEqual(calls["n"], 4)
        self.assertEqual(orch.states["a1"], "error")

    def test_final_error_step_carries_escalation(self):
        """Escalate tanpa saran tidak bisa ditampilkan di UI."""
        async def always_503(orch, node, inp):
            raise RuntimeError("503 Service Unavailable")

        orch = make_orchestrator(always_503, no_network_healing)
        steps: list[ExecutionStep] = []

        async def on_step(step):
            steps.append(step.model_copy(deep=True))

        async def go():
            await orch.run(on_step=on_step)

        with self.assertRaises(RuntimeError):
            asyncio.run(go())

        err = [s for s in steps if s.status == "error"]
        self.assertTrue(err, "harus ada step error")
        healing = err[0].output["healing"]
        self.assertEqual(healing["action"], "escalate")
        self.assertTrue(healing["suggestions"], "escalate wajib membawa saran")

    def test_credential_is_not_retried(self):
        """Regresi paling mahal kalau salah: 401 yang di-retry membakar
        kuota user untuk hal yang dijamin gagal."""
        calls = {"n": 0}

        async def unauthorized(orch, node, inp):
            calls["n"] += 1
            raise RuntimeError("401 Unauthorized: invalid_grant")

        orch = make_orchestrator(unauthorized, no_network_healing)

        async def go():
            await orch.run()

        with self.assertRaises(RuntimeError):
            asyncio.run(go())
        self.assertEqual(calls["n"], 1, "credential tidak boleh di-retry sama sekali")

    def test_404_aborts_without_retry(self):
        calls = {"n": 0}

        async def missing(orch, node, inp):
            calls["n"] += 1
            raise RuntimeError("404 Not Found")

        orch = make_orchestrator(missing, no_network_healing)

        async def go():
            await orch.run()

        with self.assertRaises(RuntimeError):
            asyncio.run(go())
        self.assertEqual(calls["n"], 1)

    def test_unknown_error_retries_twice_then_escalates(self):
        calls = {"n": 0}

        async def weird(orch, node, inp):
            calls["n"] += 1
            raise RuntimeError("wibble: undocumented failure mode")

        orch = make_orchestrator(weird, no_network_healing)

        async def go():
            await orch.run()

        with self.assertRaises(RuntimeError):
            asyncio.run(go())
        self.assertEqual(calls["n"], 3, "2 retry lalu escalate = 3 pemanggilan")


class TestNoHealingWhereItShouldNotBe(unittest.TestCase):
    def test_successful_node_never_calls_healing(self):
        counter = {"n": 0}

        async def fine(orch, node, inp):
            return {"ok": True}

        orch = make_orchestrator(fine, spy_healing(counter))
        asyncio.run(orch.run())
        self.assertEqual(counter["n"], 0,
                         "node yang sukses tidak boleh menyentuh healing")

    def test_broken_graph_does_not_invoke_healing(self):
        """Graph rusak itu bug konfigurasi, bukan kegagalan sementara --
        healing tidak boleh membuatnya berputar-putar 5x."""
        counter = {"n": 0}
        graph = FlowGraph(
            nodes=[{"id": "a1", "data": {"kind": "agent"}}], edges=[])
        orch = StatefulOrchestrator(graph, trigger_input={},
                                    healing_factory=spy_healing(counter))

        async def go():
            await orch.run()

        with self.assertRaises(RuntimeError):
            asyncio.run(go())
        self.assertEqual(counter["n"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
