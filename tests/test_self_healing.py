"""Test self-healing hybrid: batas per kategori, backoff, escalate.

Deterministik: tanpa LLM dan tanpa jaringan, jadi hasilnya tidak bisa
bergantung pada model yang sedang menjawab.
"""
import asyncio
import unittest

from self_healing import (
    CATEGORIES, RATE_LIMIT_DELAYS_MS, SelfHealingAgent, classify_error,
)


def run(coro):
    return asyncio.run(coro)


class TestClassification(unittest.TestCase):
    def test_token_expired_is_credential(self):
        for msg in ("401 Unauthorized", "invalid_grant: token has expired",
                    "Could not refresh access token: invalid_grant"):
            self.assertEqual(classify_error(msg).action, "credential", msg)

    def test_rate_limit_5xx_network_are_retry(self):
        for msg in ("429 Too Many Requests", "rate limit exceeded",
                    "503 Service Unavailable", "502 Bad Gateway",
                    "Connection reset by peer", "ETIMEDOUT"):
            self.assertEqual(classify_error(msg).action, "retry", msg)

    def test_404_and_400_abort(self):
        for msg in ("404 Not Found", "400 Bad Request", "422 validation error"):
            self.assertEqual(classify_error(msg).action, "abort", msg)

    def test_unknown_returns_unknown_rule_not_none(self):
        # Versi lama mengembalikan None lalu langsung abort. Sekarang
        # error tak dikenal tetap dapat 2 percobaan sebelum escalate,
        # jadi classify_error tidak boleh pernah mengembalikan None.
        for msg in ("wibble: something nobody predicted", ""):
            rule = classify_error(msg)
            self.assertIsNotNone(rule)
            self.assertEqual(rule.name, "unknown")


class TestHybridCategoryLimits(unittest.TestCase):
    """Kontrak baru: batas per kategori, bukan satu angka global."""

    def _run(self, msg, attempts):
        agent = SelfHealingAgent(search_enabled=False)

        async def go():
            return [await agent.handle_failure(node_id="n", error=msg, attempt=a)
                    for a in attempts]
        return run(go())

    def test_credential_escalates_immediately_zero_retry(self):
        plans = self._run("401 Unauthorized: invalid_grant", [1, 2, 3, 4, 5])
        for p in plans:
            self.assertEqual(p.action, "escalate")
            self.assertEqual(p.max_attempts, 0)
        self.assertTrue(plans[0].suggestions, "escalate harus membawa saran")

    def test_credential_escalate_carries_provider(self):
        p = self._run("401 Unauthorized while calling Gmail API", [1])[0]
        self.assertEqual(p.provider, "gmail",
                         "UI butuh tahu provider mana yang disambung ulang")

    def test_network_retries_three_then_escalates(self):
        # S8 (7 Okt 2026): batas 5 -> 3 percobaan. Endpoint yang mati tidak
        # menjadi hidup karena percobaan ke-4/5; retry berlebih hanya menambah
        # latensi sampai eksekusi menggantung `pending`.
        plans = self._run("ETIMEDOUT contacting api", [1, 2, 3, 4, 5])
        self.assertEqual([p.action for p in plans],
                         ["retry"] * 3 + ["escalate", "escalate"])
        self.assertEqual(plans[-1].max_attempts, 3)

    def test_api_5xx_retries_three_then_escalates(self):
        plans = self._run("503 Service Unavailable", [1, 2, 3, 4, 5])
        self.assertEqual([p.action for p in plans],
                         ["retry"] * 3 + ["escalate", "escalate"])

    def test_connection_refused_fast_fails_after_two(self):
        """Endpoint MENOLAK koneksi -> berhenti setelah 2 percobaan (S8).

        `connection refused` deterministik: port tertutup tidak akan terbuka
        sendiri. Retry berlebih hanya memperlambat tampilnya kegagalan.
        """
        plans = self._run("Connection refused contacting 127.0.0.1:9999",
                          [1, 2, 3, 4])
        self.assertEqual([p.action for p in plans],
                         ["retry", "retry", "escalate", "escalate"])
        self.assertEqual(plans[0].max_attempts, 2)
        self.assertEqual(plans[0].category, "connection_refused")

    def test_unknown_retries_twice_then_escalates(self):
        plans = self._run("wibble: nobody predicted this", [1, 2, 3, 4])
        self.assertEqual([p.action for p in plans],
                         ["retry", "retry", "escalate", "escalate"])
        self.assertEqual(plans[0].max_attempts, 2)

    def test_404_and_400_still_abort_immediately(self):
        for msg in ("404 Not Found", "400 Bad Request"):
            self.assertEqual(self._run(msg, [1])[0].action, "abort", msg)

    def test_escalate_always_carries_suggestions(self):
        """UI butuh sesuatu yang bisa diklik; escalate tanpa saran sia-sia."""
        for msg, n in (("ETIMEDOUT", 6), ("wibble", 3), ("401 token", 1)):
            p = self._run(msg, [n])[-1]
            if p.action == "escalate":
                self.assertTrue(p.suggestions, msg)

    def test_category_table_matches_required_contract(self):
        # S8 (7 Okt 2026): semua kategori retry turun ke 3; endpoint yang
        # menolak koneksi berhenti di 2.
        self.assertEqual(CATEGORIES["credential"], 0)
        self.assertEqual(CATEGORIES["network"], 3)
        self.assertEqual(CATEGORIES["api_5xx"], 3)
        self.assertEqual(CATEGORIES["rate_limit"], 3)
        self.assertEqual(CATEGORIES["connection_refused"], 2)
        self.assertEqual(CATEGORIES["unknown"], 2)


class TestRateLimitBackoff(unittest.TestCase):
    def test_delay_is_exponential(self):
        agent = SelfHealingAgent(search_enabled=False)

        async def go():
            return [(await agent.handle_failure(node_id="n", error="429 rate limit",
                                                attempt=a)).delay_ms
                    for a in range(1, 4)]
        got = run(go())
        self.assertEqual(got, list(RATE_LIMIT_DELAYS_MS))
        for prev, nxt in zip(got, got[1:]):
            self.assertEqual(nxt, prev * 2, "backoff harus mengalikan dua")

    def test_transient_backoff_is_one_two_four(self):
        # S8: backoff transient eksplisit 1s/2s/4s (dulu mulai 0 lalu
        # (0,1,2,4,8)s). Mulai dari 1s memberi jeda nyata untuk error
        # transien tanpa membuat endpoint mati menunggu terlalu lama.
        agent = SelfHealingAgent(search_enabled=False)

        async def go():
            return [(await agent.handle_failure(
                node_id="n", error="503 Service Unavailable", attempt=a)).delay_ms
                for a in (1, 2, 3)]
        self.assertEqual(run(go()), [1000, 2000, 4000])

    def test_no_delay_once_escalated(self):
        # Setelah 5 percobaan, plan-nya escalate -- bukan retry, jadi
        # tidak ada yang perlu menunggu. Percobaan ke-6 tidak boleh
        # "delay 16000 lalu coba lagi": itu loop tak berujung.
        agent = SelfHealingAgent(search_enabled=False)

        async def go():
            return [await agent.handle_failure(node_id="n", error="429 rate limit",
                                               attempt=a) for a in (6, 99)]
        for p in run(go()):
            self.assertEqual(p.action, "escalate")
            self.assertEqual(p.delay_ms, 0, "hanya retry yang menunggu")


class TestSearchEveryAttempt(unittest.TestCase):
    def test_search_runs_on_attempt_one_for_non_credential(self):
        """Perubahan dari versi lama: pencarian tidak lagi nunggu attempt>=2."""
        calls = []

        async def fake(msg):
            calls.append(msg)
            return [{"source": "github", "title": "x", "link": "l"}]

        agent = SelfHealingAgent(search_enabled=True)
        agent.search_forum = fake  # type: ignore[assignment]

        async def go():
            return await agent.handle_failure(node_id="n", error="ETIMEDOUT", attempt=1)

        plan = run(go())
        self.assertEqual(len(calls), 1, "pencarian harus jalan di attempt 1")
        self.assertEqual(plan.search_hits, 1)
        self.assertTrue(plan.suggestions)

    def test_credential_never_searches(self):
        calls = []

        async def fake(msg):
            calls.append(msg)
            return []

        agent = SelfHealingAgent(search_enabled=True)
        agent.search_forum = fake  # type: ignore[assignment]

        async def go():
            return await agent.handle_failure(node_id="n", error="401 token expired", attempt=1)

        plan = run(go())
        self.assertEqual(len(calls), 0, "credential butuh manusia, bukan artikel")
        self.assertEqual(plan.action, "escalate")

    def test_escalate_still_searches_for_suggestions(self):
        calls = []

        async def fake(msg):
            calls.append(msg)
            return [{"source": "stackoverflow", "title": "how to fix", "link": "l"}]

        agent = SelfHealingAgent(search_enabled=True)
        agent.search_forum = fake  # type: ignore[assignment]

        async def go():
            return await agent.handle_failure(node_id="n", error="ETIMEDOUT", attempt=9)

        plan = run(go())
        self.assertEqual(plan.action, "escalate")
        self.assertTrue(calls, "escalate tanpa saran forum tidak berguna")
        self.assertEqual(plan.suggestions[0]["kind"], "stackoverflow")


class TestResilience(unittest.TestCase):
    def test_broken_llm_does_not_block_healing(self):
        """LLM gagal = pengayaan hilang, bukan healing hilang."""
        async def bad_llm(message, attempt):
            raise RuntimeError("model unavailable")

        agent = SelfHealingAgent(search_enabled=False, llm_reflect=bad_llm)

        async def go():
            return await agent.handle_failure(
                node_id="n", error="503 Service Unavailable", attempt=1)

        plan = run(go())
        self.assertEqual(plan.action, "retry")
        self.assertTrue([t for t in plan.trace if t.get("impact") == "ignored"],
                        "kegagalan LLM harus tercatat di trace")

    def test_search_failure_does_not_change_action(self):
        async def boom(msg):
            raise RuntimeError("search down")

        agent = SelfHealingAgent(search_enabled=True)
        agent.search_forum = boom  # type: ignore[assignment]

        async def go():
            return await agent.handle_failure(
                node_id="n", error="429 rate limit", attempt=2)

        plan = run(go())
        self.assertEqual(plan.action, "retry")
        self.assertEqual(plan.search_hits, 0)

    def test_search_failure_still_escalates_with_fallback(self):
        async def boom(msg):
            raise RuntimeError("search down")

        agent = SelfHealingAgent(search_enabled=True)
        agent.search_forum = boom  # type: ignore[assignment]

        async def go():
            return await agent.handle_failure(
                node_id="n", error="429 rate limit", attempt=6)

        plan = run(go())
        self.assertEqual(plan.action, "escalate")
        self.assertTrue(plan.suggestions,
                        "escalate wajib punya saran walau pencarian gagal")

    def test_plan_is_json_serialisable(self):
        import json
        agent = SelfHealingAgent(search_enabled=False)

        async def go():
            return await agent.handle_failure(
                node_id="n", error={"status": 429, "message": "rate limit"}, attempt=2)

        json.dumps(run(go()).to_dict())  # tidak boleh melempar

    def test_dict_and_str_errors_classify_identically(self):
        agent = SelfHealingAgent(search_enabled=False)

        async def a():
            return await agent.handle_failure(node_id="n", error="401 Unauthorized", attempt=1)

        async def b():
            return await agent.handle_failure(
                node_id="n", error={"status": 401, "message": "Unauthorized"}, attempt=1)

        self.assertEqual(run(a()).action, run(b()).action)


if __name__ == "__main__":
    unittest.main(verbosity=2)

