"""Uji isolasi bus per-pemilik (temuan E2E Fitur #4).

Regresi yang dijaga: endpoint /stats, /flush, /emit harus berbagi bus
yang SAMA per-pemilik, dan event audit non-HTTP tidak boleh membocor
ke tujuan milik penyewa lain.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import log_streaming as ls  # noqa: E402


@pytest.fixture(autouse=True)
def _clean():
    ls.invalidate_owner_bus(None)
    yield
    ls.invalidate_owner_bus(None)


def _factory_calls(counter: list[int]):
    def _f(owner_id: str) -> ls.EventBus:
        counter[0] += 1
        return ls.EventBus(destinations=[])
    return _f


def test_same_owner_gets_same_bus():
    """Dua panggilan berturut-turut harus mengembalikan objek yang sama."""
    calls: list[int] = [0]
    f = _factory_calls(calls)
    a = ls.owner_bus("u-1", f, now=1000.0)
    b = ls.owner_bus("u-1", f, now=1000.5)
    assert a is b
    assert calls[0] == 1


def test_ttl_expiry_rebuilds_bus():
    """Setelah TTL, bus dibangun ulang dari konfigurasi tersimpan."""
    calls: list[int] = [0]
    f = _factory_calls(calls)
    a = ls.owner_bus("u-1", f, ttl=10.0, now=1000.0)
    b = ls.owner_bus("u-1", f, ttl=10.0, now=1011.0)
    assert a is not b
    assert calls[0] == 2


def test_two_owners_are_isolated():
    """Bus penyewa A tidak boleh dipakai penyewa B."""
    calls: list[int] = [0]
    f = _factory_calls(calls)
    a = ls.owner_bus("u-1", f, now=1.0)
    b = ls.owner_bus("u-2", f, now=1.0)
    assert a is not b
    assert calls[0] == 2


def test_invalidate_single_owner():
    calls: list[int] = [0]
    f = _factory_calls(calls)
    a = ls.owner_bus("u-1", f, now=1.0)
    ls.invalidate_owner_bus("u-1")
    b = ls.owner_bus("u-1", f, now=1.01)
    assert a is not b
    assert calls[0] == 2


def test_invalidate_all_owners():
    calls: list[int] = [0]
    f = _factory_calls(calls)
    ls.owner_bus("u-1", f, now=1.0)
    ls.owner_bus("u-2", f, now=1.0)
    ls.invalidate_owner_bus()
    ls.owner_bus("u-1", f, now=1.0)
    ls.owner_bus("u-2", f, now=1.0)
    assert calls[0] == 4


def test_events_reach_only_owners_destination():
    """Event yang dipancarkan ke bus A tidak muncul di bus B."""
    rx_a: list[dict] = []
    rx_b: list[dict] = []

    class _Sink(ls.Destination):
        type = "sink"

        def __init__(self, label, sink):
            super().__init__(label, subscribed_events=["n8n"])
            self._sink = sink

        def accepts(self, event):
            return True

        def _deliver(self, payload):
            self._sink.append(payload)
            return True

    bus_a = ls.EventBus(destinations=[_Sink("a", rx_a)])
    bus_b = ls.EventBus(destinations=[_Sink("b", rx_b)])
    ls.owner_bus("u-1", lambda _o: bus_a, now=1.0)
    ls.owner_bus("u-2", lambda _o: bus_b, now=1.0)

    ls.owner_bus("u-1", lambda _o: bus_a, now=1.1).emit(
        ls.make_event("n8n.workflow.success", user_id="u-1"))

    assert len(rx_a) == 1
    assert rx_b == [], "event penyewa A membocor ke penyewa B"
