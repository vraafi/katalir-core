import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gateway_roster as gr


def test_free_allowlist_and_plus_wildcard():
    assert gr.is_allowed("gemini-2.5-flash-lite", "free")
    assert gr.is_allowed("any-provider/model", "plus")
    assert not gr.is_allowed("unknown/model", "free")


def test_unknown_tier_is_deny():
    assert not gr.is_allowed("gemini-2.5-flash-lite", "")
    assert not gr.is_allowed("gemini-2.5-flash-lite", "enterprise")


def test_blocked_model_is_logged(caplog):
    with caplog.at_level(logging.INFO, logger="gateway_roster"):
        assert not gr._model_allowed_for_tier("blocked/model", "free")
    assert "model_blocked model=blocked/model tier=free" in caplog.text
