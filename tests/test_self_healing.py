"""Test self-healing: klasifikasi, batas percobaan, dan graceful abort.

Tan's tanpa LLM dan tanpa jaringan, jadi hasilnya deterministik dan
tidak bisa "lucky pass" tergantung model yang sedang menjawab.
"""
import asyncio
import unittest

from self_healing import MAX_ATTEMPTS, SelfHealingAgent, classify_error


class TestClassification(unittest.TestCase):
    def test_token_expired_is_credential_not_retry(self):
        # Ini kasus inti dari brief (Gmail 401). Kalau ini diklasifikasi
        # retry, engine akan membakar 3 percobaan untuk hal yang mustahil
        # berhasil tanpa token baru.
        for msg in ("401 Unauthorized", "invalid_grant: token has expired",
                    "Could not refresh access token: invalid_grant"):
            self.assertEqual(classify_error(msg).action, "credential", msg)

    def test_rate_limit_and_5xx_are_retryable(self):
        for msg in ("429 Too Many Requests", "rate limit exceeded",
                    "503 Service Unavailable", "502 Bad Gateway",
                    "Connection reset by peer", "ETIMEDOUT"):
            self.assertEqual(classify_error(msg).action, "retry", msg)

    def test_404_and_400_abort(self):
        # Retry payload yang sama tidak akan menemukan target yang tidak
        # ada, dan 400 tidak akan jadi 200 dengan payload yang sama.
        for msg in ("404 Not Found", "400 Bad Request", "422 validation error"):
            self.assertEqual(classify_error(msg).action, "abort", msg)

    def test_unknown_error_is_not_matched(self):
        # Penting: tidak ada rule = tidak ada aksi. Jangan sampai error
        # aneh ikut dapat aksi retry.
        self.assertIsNone(classify_error("wibble: something nobody predicted"))
        self.assertIsNone(classify_error(""))


class TestAttemptLimit(unittest.TestCase):
    def test_stops_at_max_attempts(self):
        agent = SelfHealingAgent(search_enabled=False)

        async def run():
            out = []
            for attempt in range(1, MAX_ATTEMPTS + 2):
                plan = await agent.handle_failure(
                    node_id="gmail_1", error="503 Service Unavailable", attempt=attempt)
                out.append(plan.action if plan else None)
            return out

        actions = asyncio.run(run())
        self.assertEqual(actions, ["retry", "retry", "retry", None])
        self.assertIsNone(actions[3], "retry harus berhenti, bukan loop")

    def test_credential_never_retries(self):
        agent = SelfHealingAgent(search_enabled=False)

        async def run():
            for attempt in (1, 2, 3):
                plan = await agent.handle_failure(
                    node_id="gmail_1", error="401 token expired", attempt=attempt)
                self.assertEqual(plan.action, "credential")

        asyncio.run(run())

    def test_unknown_error_aborts_immediately(self):
        agent = SelfHealingAgent(search_enabled=False)

        async def run():
            plan = await agent.handle_failure(
                node_id="x", error="wibble: unpredictable", attempt=1)
            return plan

        plan = asyncio.run(run())
        self.assertEqual(plan.action, "abort")
        self.assertIn("tidak dikenali", plan.reason)


class TestResilience(unittest.TestCase):
    def test_broken_llm_does_not_block_healing(self):
        """LLM gagal = pengayaan hilang, bukan healing hilang."""
        async def bad_llm(message, attempt):
            raise RuntimeError("model unavailable")

        agent = SelfHealingAgent(search_enabled=False, llm_reflect=bad_llm)

        async def run():
            return await agent.handle_failure(
                node_id="n", error="503 Service Unavailable", attempt=1)

        plan = asyncio.run(run())
        self.assertEqual(plan.action, "retry")
        ignored = [t for t in plan.trace if t.get("impact") == "ignored"]
        self.assertTrue(ignored, "kegagalan LLM harus tercatat di trace")

    def test_search_failure_does_not_abort(self):
        async def boom(msg):
            raise RuntimeError("search down")

        agent = SelfHealingAgent(search_enabled=True)
        agent.search_forum = boom  # type: ignore[assignment]

        async def run():
            return await agent.handle_failure(
                node_id="n", error="429 rate limit", attempt=2)

        plan = asyncio.run(run())
        self.assertEqual(plan.action, "retry")
        self.assertEqual(plan.search_hits, 0)

    def test_plan_is_json_serialisable(self):
        import json
        agent = SelfHealingAgent(search_enabled=False)

        async def run():
            return await agent.handle_failure(
                node_id="n", error={"status": 429, "message": "rate limit"}, attempt=2)

        plan = asyncio.run(run())
        json.dumps(plan.to_dict())  # tidak boleh melempar
        self.assertEqual(plan.action, "retry")


if __name__ == "__main__":
    unittest.main(verbosity=2)
