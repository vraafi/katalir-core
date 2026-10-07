"""test_rate_limit_tiers.py — BAGIAN 6 brief 7 Okt 2026.

Tiga tier rate limit per user:
  * build workflow : 5 / menit
  * tool call      : 20 / menit
  * request        : 100 / jam (di atas 10 / menit pada /chat)
"""
import rate_limit as rl


def test_tier_build_workflow_5_per_menit():
    lim = rl.SlidingWindowLimiter(5, 60.0)
    for i in range(5):
        ok, _ = lim.check("u1")
        assert ok, f"percobaan ke-{i + 1} harus lolos"
    ok, retry = lim.check("u1")
    assert ok is False, "percobaan ke-6 harus ditolak"
    assert retry >= 1


def test_tier_tool_call_20_per_menit():
    lim = rl.SlidingWindowLimiter(20, 60.0)
    allowed = sum(1 for _ in range(21) if lim.check("u2")[0])
    assert allowed == 20, allowed
    ok, retry = lim.check("u2")
    assert ok is False and retry >= 1


def test_tier_request_100_per_jam():
    lim = rl.SlidingWindowLimiter(100, 3600.0)
    allowed = sum(1 for _ in range(101) if lim.check("u3")[0])
    assert allowed == 100, allowed
    assert lim.check("u3")[0] is False


def test_limiter_global_terpasang_sesuai_brief():
    """Instance global punya batas sesuai brief."""
    assert rl.workflow_build_limiter.max_calls == 5
    assert rl.tool_call_limiter.max_calls == 20
    assert rl.request_hourly_limiter.max_calls == 100


def test_reset_all_mengosongkan_semua():
    rl.workflow_build_limiter.check("ux")
    rl.tool_call_limiter.check("ux")
    rl.request_hourly_limiter.check("ux")
    rl.reset_all()
    assert rl.workflow_build_limiter.snapshot("ux") == 0
    assert rl.tool_call_limiter.snapshot("ux") == 0
    assert rl.request_hourly_limiter.snapshot("ux") == 0


def test_tool_call_limiter_dipakai_execute_textual_tool(monkeypatch):
    """`execute_textual_tool` menolak dengan status rate_limited saat limit."""
    import textual_tool_handlers as th

    monkeypatch.setattr(th, "_missing_provider", lambda tool, email: "")
    monkeypatch.setitem(th.HANDLERS, "TELEGRAM",
                        lambda a, e: {"status": "success"})
    # Batas 1 supaya cepat tercapai.
    lim = rl.SlidingWindowLimiter(1, 60.0)
    monkeypatch.setattr(rl, "tool_call_limiter", lim)

    call = {"tool": "TELEGRAM", "args": {"chat_id": "1", "pesan": "x"}}
    first = th.execute_textual_tool(call, "batas@example.test", approved=True)
    assert first.get("status") == "success", first
    second = th.execute_textual_tool(call, "batas@example.test", approved=True)
    assert second.get("status") == "rate_limited", second
    assert second.get("retry_after", 0) >= 1


def test_rate_limit_nonaktif_bila_env_nol():
    """`max_calls <= 0` = limiter nonaktif (fail-open disengaja)."""
    lim = rl.SlidingWindowLimiter(0, 60.0)
    assert all(lim.check("u")[0] for _ in range(1000))
