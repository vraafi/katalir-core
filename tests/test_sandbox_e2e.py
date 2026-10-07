"""Test E2E sandbox: 10 workflow mock + kebijakan jaringan + jalur kebocoran.

Test ini menjalankan mesin eksekusi SUNGGUHAN (`StatefulOrchestrator`) dengan
mock server in-process. Tidak ada kredensial produksi, tidak ada paket yang
keluar ke jaringan.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SANDBOX = ROOT / "tests" / "sandbox"
for _p in (str(ROOT), str(SANDBOX)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import agent_redactor as ar  # noqa: E402
import credential_proxy as cp  # noqa: E402
import mock_server  # noqa: E402
import sandbox_runner as sr  # noqa: E402
import tools  # noqa: E402
from execution_engine import FlowNode, FlowNodeData, NodeKind  # noqa: E402


class TestSepuluhWorkflowMock(unittest.TestCase):
    """10 test workflow (mode mock) — dijalankan SEKALI, diverifikasi per-test."""

    results: dict[str, dict] = {}

    @classmethod
    def setUpClass(cls):
        cls.results = {r["name"]: r for r in sr.run_all()}

    def _assert_ok(self, index: int):
        name = sr.TESTS[index][0]
        r = self.results[name]
        self.assertTrue(r["ok"],
                        f"{name} GAGAL: states={r['states']} err={r['error']} "
                        f"leaks={r['leaks']} canary={r['canary_hits']}")

    def test_01_simple(self):
        self._assert_ok(0)

    def test_02_medium_chain(self):
        self._assert_ok(1)

    def test_03_condition_branch(self):
        self._assert_ok(2)

    def test_04_complex_sheets(self):
        self._assert_ok(3)

    def test_05_multi_agent(self):
        self._assert_ok(4)

    def test_06_mcp_tool(self):
        self._assert_ok(5)

    def test_07_webhook_payload(self):
        self._assert_ok(6)

    def test_08_hard_github(self):
        self._assert_ok(7)

    def test_09_error_recovery(self):
        self._assert_ok(8)
        r = self.results[sr.TESTS[8][0]]
        # S8: 3 percobaan lalu node `error` (bukan `pending`), dan cepat.
        retries = [s for s in r["steps"] if s[1] == "retrying"]
        self.assertEqual(len(retries), 3, "harus tepat 3 percobaan ulang")
        self.assertLess(r["duration_s"], 60.0)
        self.assertIsNotNone(r["error"], "kegagalan harus jujur (raise)")

    def test_10_full_orchestration(self):
        self._assert_ok(9)

    def test_semua_workflow_nol_kebocoran(self):
        for name, r in self.results.items():
            with self.subTest(workflow=name):
                self.assertEqual(r["leaks"], [], f"{name}: kredensial bocor")
                self.assertEqual(r["canary_hits"], [], f"{name}: canary bocor")

    def test_seluruh_sepuluh_lulus(self):
        passed = sum(1 for r in self.results.values() if r["ok"])
        self.assertEqual(passed, 10, f"hanya {passed}/10 PASS")

    def test_kondisi_memang_menyaring(self):
        """TEST #3: cabang yang kondisinya tidak terpenuhi harus SKIP."""
        r = self.results[sr.TESTS[2][0]]
        # Node yang di-skip tetap berstatus `completed` (kontrak mesin)...
        self.assertEqual(r["states"]["gate"], "completed")
        self.assertEqual(r["states"]["else"], "completed")
        # ...tetapi TIDAK memanggil egress dan membawa penanda skipped.
        self.assertEqual(r["egress_calls"], 1,
                         "cabang yang tidak terpenuhi tidak boleh jalan")
        self.assertTrue(r["outputs"]["else"].get("skipped"),
                        "node else harus membawa penanda skipped")


class TestKebijakanJaringanSandbox(unittest.TestCase):
    """SSRF guard produksi = kebijakan `blocked_hosts` sandbox."""

    BLOCKED = [
        "http://127.0.0.1:8899/x",
        "http://localhost/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://10.0.0.5/x",
        "http://192.168.1.1/x",
        "http://sandbox.mock/mock/health",   # nama tak bisa diresolusi -> tolak
    ]

    def test_host_terblokir_ditolak(self):
        for url in self.BLOCKED:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    tools.http_request(url)

    def test_skema_non_http_ditolak(self):
        for url in ("ftp://x.test/a", "file:///etc/passwd"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    tools.http_request(url)

    def test_host_publik_lolos_gerbang_host(self):
        """Kontrol positif: guard hanya menolak internal, bukan semua host."""
        self.assertFalse(tools._host_blocked("example.com"))
        self.assertFalse(tools._host_blocked("api.telegram.org"))


class TestIsolasiMock(unittest.TestCase):
    def test_mock_di_proses_sendiri_tanpa_port(self):
        c = mock_server.client()
        self.assertEqual(str(c.base_url).rstrip("/"), "http://sandbox.mock")
        asyncio.run(c.aclose())

    def test_mock_health_in_process(self):
        async def go():
            async with mock_server.client() as c:
                r = await c.get("/mock/health")
                return r.status_code, r.json()

        code, body = asyncio.run(go())
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])

    def test_tidak_ada_kredensial_test_di_lingkungan(self):
        """Zero-trust: bila TEST_* kosong, live mode memang diblokir."""
        cp.clear_store()
        status = cp.load_test_credentials()
        self.assertTrue(all(v == "MISSING" for v in status.values()))
        self.assertEqual(cp.store_keys(), [])


class TestJalurKebocoranKredensial(unittest.TestCase):
    """Body respons yang memuat rahasia harus ditangkap di jalur pulang."""

    def setUp(self):
        sr.seed_test_credentials()

    def _egress_node(self, cfg: dict):
        graph = sr.make_graph([("t", {"kind": "trigger", "label": "x"})], [])
        orch = sr.build_orch(graph, {})
        node = FlowNode(id="e", data=FlowNodeData(kind=NodeKind.MCP, config=cfg))
        return orch, node, sr.SandboxEgress()

    def test_canary_di_body_melempar(self):
        canary = cp.get_canary("telegram_bot")
        orch, node, egress = self._egress_node(
            {"op": "telegram_echo_token", "token": canary})
        with self.assertRaises(ar.CanaryDetectedError):
            asyncio.run(egress(orch, node, {}))

    def test_nilai_kredensial_di_body_dimask(self):
        """Nilai test yang bentuknya bebas (chat id) ditangkap pencocokan NILAI."""
        orch, node, egress = self._egress_node(
            {"op": "telegram_echo_token", "token": "${auth.telegram_chat}"})
        out = asyncio.run(egress(orch, node, {}))
        blob = str(out)
        self.assertNotIn(sr.TEST_CREDS["telegram_chat"], blob)
        self.assertIn(cp.MASK, blob)

    def test_pola_kredensial_di_body_diredact(self):
        """Nilai berbentuk kredensial (bukan milik store) ditangkap POLA."""
        raw = "ghp_" + "D" * 36
        orch, node, egress = self._egress_node(
            {"op": "telegram_echo_token", "token": raw})
        out = asyncio.run(egress(orch, node, {}))
        blob = str(out)
        self.assertNotIn(raw, blob)
        self.assertIn("[GITHUB_REDACTED]", blob)

    def test_placeholder_tidak_terkirim_apa_adanya(self):
        """Placeholder TIDAK boleh lolos ke mock sebagai literal `${auth.X}`."""
        orch, node, egress = self._egress_node(
            {"op": "telegram_echo_token", "token": "${auth.telegram_chat}"})
        asyncio.run(egress(orch, node, {}))
        sent = egress.calls[0]["args_masked"]["token"]
        self.assertNotIn("${auth.", sent, "placeholder dikirim mentah ke egress")


if __name__ == "__main__":
    unittest.main(verbosity=2)
