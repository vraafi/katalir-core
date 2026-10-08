# tests/test_monitoring.py — Fitur #3 hard test (12 skenario, Okt 2026)
# Deterministik, tanpa jaringan: notifier memakai transport yang disuntik.
from __future__ import annotations

import time

import pytest

import monitoring as mon


# 1. Metrik -> eksposisi Prometheus bisa di-scrape
def test_01_prometheus_scrape():
    m = mon.Metrics()
    m.describe("katalir_executions_total", "Total eksekusi")
    m.inc("katalir_executions_total", 3, {"status": "success"})
    m.inc("katalir_executions_total", 1, {"status": "error"})
    m.set_gauge("katalir_workers_active", 5)
    m.observe("latency_ms", 120)
    m.observe("latency_ms", 900)
    teks = m.render_prometheus()
    parsed = mon.parse_prometheus(teks)
    assert parsed['katalir_executions_total{status="success"}'] == 3
    assert parsed['katalir_executions_total{status="error"}'] == 1
    assert parsed["katalir_workers_active"] == 5
    assert parsed["latency_ms_count"] == 2
    assert parsed["latency_ms_sum"] == 1020


# 2. Aturan alert: error rate > 5% -> fire
def test_02_error_rate_alert():
    values = {"error_rate": 0.12, "success_rate": 0.88, "p95_latency_ms": 500,
              "cost_usd": 1.0}
    firing = mon.evaluate_rules(mon.DEFAULT_RULES, values)
    nama = {a["rule"] for a in firing}
    assert "high_error_rate" in nama
    assert "low_success_rate" in nama
    assert "high_cost" not in nama
    # nilai sehat -> tidak ada alert
    sehat = mon.evaluate_rules(mon.DEFAULT_RULES,
                               {"error_rate": 0.01, "success_rate": 0.99,
                                "p95_latency_ms": 100, "cost_usd": 0.5})
    assert sehat == []


# 3. Notifikasi Slack diterima
def test_03_slack_received():
    terkirim = []
    n = mon.SlackNotifier(webhook_url="https://hooks.slack/x",
                          transport=lambda p: terkirim.append(p) or True)
    alert = {"rule": "high_error_rate", "metric": "error_rate", "value": 0.12,
             "op": ">", "threshold": 0.05, "severity": "critical"}
    assert n.send(alert) is True
    assert terkirim and "high_error_rate" in terkirim[0]["json"]["text"]


# 4. Notifikasi Email diterima
def test_04_email_received():
    terkirim = []
    n = mon.EmailNotifier(to="ops@katalir.io",
                          transport=lambda p: terkirim.append(p) or True)
    assert n.send({"rule": "high_cost", "severity": "warning"}) is True
    assert terkirim[0]["to"] == "ops@katalir.io"
    assert "high_cost" in terkirim[0]["subject"]


def test_04b_notify_all():
    out = []
    ns = [mon.WebhookNotifier(url="u", transport=lambda p: out.append(p) or True),
          mon.TelegramNotifier(bot_token="t", chat_id="1",
                               transport=lambda p: out.append(p) or True)]
    hasil = mon.notify_all(ns, {"rule": "r", "severity": "warning"})
    assert hasil == {"webhook": True, "telegram": True}
    assert len(out) == 2


# 5. Dashboard: muat < 2s
def test_05_dashboard_fast():
    m = mon.Metrics()
    for i in range(5000):
        m.observe("latency_ms", i % 1000)
    for i in range(1000):
        m.inc("katalir_executions_total", 1, {"status": "success"})
    t = mon.Trace("exec-1")
    for i in range(50):
        t.span("node", f"n{i}").finish()
    t0 = time.perf_counter()
    ringkas = mon.dashboard_summary(m, [], [t])
    dt = time.perf_counter() - t0
    assert dt < 2.0, f"dashboard terlalu lambat: {dt:.3f}s"
    assert ringkas["traces"] == 1 and ringkas["spans"] == 50
    assert ringkas["p95_latency_ms"] > 0


# 6. Trace: satu span per node
def test_06_trace_spans():
    nodes = [
        {"id": "trigger", "node_id": "n1", "kind": "trigger",
         "started_at": 100.0, "ended_at": 100.2, "status": "completed"},
        {"id": "agent", "node_id": "n2", "kind": "agent",
         "started_at": 100.2, "ended_at": 101.0, "status": "completed"},
    ]
    t = mon.trace_from_execution("exec-9", nodes)
    d = t.to_dict()
    assert d["trace_id"] == "exec-9"
    assert len(d["spans"]) == 2
    assert d["spans"][1]["duration_ms"] == pytest.approx(800.0, abs=1)
    assert d["spans"][0]["attributes"]["kind"] == "trigger"


# 7. Agregasi log: pencarian OK
def test_07_log_search():
    idx = mon.LogIndex()
    idx.add({"level": "error", "msg": "workflow gagal", "wf": "A"})
    idx.add({"level": "info", "msg": "workflow sukses", "wf": "B"})
    idx.add({"level": "error", "msg": "timeout di node HTTP", "wf": "A"})
    assert len(idx) == 3
    assert len(idx.search("workflow")) == 2
    assert len(idx.search(level="error")) == 2
    assert len(idx.search("timeout")) == 1
    assert idx.search("workflow", limit=1)[0]["wf"] == "B"


# 8. Dedup alert
def test_08_dedup():
    clock = {"t": 1000.0}
    am = mon.AlertManager(dedup_seconds=300, clock=lambda: clock["t"])
    a = [{"rule": "high_error_rate", "severity": "critical"}]
    assert len(am.process(a)) == 1        # pertama -> kirim
    assert am.process(a) == []            # dalam jendela -> dedup
    clock["t"] += 301
    assert len(am.process(a)) == 1        # setelah jendela -> kirim lagi


# 9. Silence (maintenance)
def test_09_silence():
    clock = {"t": 1000.0}
    am = mon.AlertManager(dedup_seconds=0, clock=lambda: clock["t"])
    a = [{"rule": "high_cost", "severity": "warning"}]
    am.silence("high_cost", until_ts=1500.0)
    assert am.process(a) == []            # dibisukan
    clock["t"] = 1600.0
    assert len(am.process(a)) == 1        # silence berakhir
    am.silence("high_cost", until_ts=0.0)  # 0 = selamanya
    assert am.is_silenced("high_cost", now=999999.0) is True


# 10. Performa: 1000 aturan
def test_10_performance_1000_rules():
    rules = [{"name": f"r{i}", "metric": f"m{i}", "op": ">",
              "threshold": 5} for i in range(1000)]
    values = {f"m{i}": 10 for i in range(1000)}
    t0 = time.perf_counter()
    firing = mon.evaluate_rules(rules, values)
    dt = time.perf_counter() - t0
    assert len(firing) == 1000
    assert dt < 1.0, f"1000 aturan terlalu lambat: {dt:.3f}s"


# 11. Benchmark: latensi evaluasi alert
def test_11_alert_latency_benchmark():
    values = {"error_rate": 0.2, "success_rate": 0.8, "p95_latency_ms": 5000,
              "cost_usd": 99.0}
    t0 = time.perf_counter()
    for _ in range(1000):
        mon.evaluate_rules(mon.DEFAULT_RULES, values)
    dt = (time.perf_counter() - t0) / 1000
    assert dt < 0.005, f"latensi/aturan terlalu tinggi: {dt*1000:.3f}ms"


# 12. Keamanan: isi alert tidak membocorkan rahasia
def test_12_alert_no_secret_leak():
    alert = {"rule": "r", "detail": "pakai secret://gmail/app_password dan "
                                    "token sk-abcdefghijklmnop",
             "nested": {"k": "Bearer eyJhbGciOiJIUzI1NiJ9.abc"}}
    bersih = mon.redact(alert)
    blob = str(bersih)
    assert "secret://" not in blob
    assert "sk-abcdefghijklmnop" not in blob
    assert "Bearer" not in blob
    assert mon.MASK in blob
