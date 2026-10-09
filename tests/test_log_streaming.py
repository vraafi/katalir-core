# tests/test_log_streaming.py — Fitur #4: log streaming ke SIEM
# ======================================================================
# 20 tes / 13 skenario wajib. Transport DIJALANKAN sebagai callable (bukan
# di-stub logikanya): format webhook, frame syslog RFC 5424, dan envelope
# Sentry benar-benar dibentuk oleh kode produksi, lalu diperiksa isinya.
# Tidak ada jaringan: transport palsu mengembalikan bool seperti klien nyata.
# ======================================================================

from __future__ import annotations

import json
import os

import pytest

import log_streaming as LS


class Recorder:
    """Transport palsu: mencatat payload + bisa dipaksa gagal."""

    def __init__(self, ok: bool = True):
        self.calls: list[dict] = []
        self.ok = ok

    def __call__(self, payload: dict) -> bool:
        self.calls.append(payload)
        return self.ok

    @property
    def n(self) -> int:
        return len(self.calls)


def webhook(rec, **spec):
    base = {"type": "webhook", "label": "ops", "url": "https://siem.example/hook"}
    base.update(spec)
    return LS.build_destination(base, transport=rec)


def syslog(rec, **spec):
    base = {"type": "syslog", "label": "sys", "host": "soc.example",
            "protocol": "udp"}
    base.update(spec)
    return LS.build_destination(base, transport=rec)


def sentry(rec, **spec):
    base = {"type": "sentry", "label": "sen",
            "dsn": "https://pub123@o1.ingest.sentry.io/42"}
    base.update(spec)
    return LS.build_destination(base, transport=rec)


# ---------------------------------------------------------------------------
# BASIC (3)
# ---------------------------------------------------------------------------
def test_b1_webhook_mengirim_event_lengkap():
    """B1: satu event workflow -> satu HTTP POST dengan payload terstruktur."""
    rec = Recorder()
    d = webhook(rec, subscribedEvents=["n8n.workflow"])
    b = LS.EventBus([d])
    hasil = b.emit_event("n8n.workflow.success", workflow_id="wf-1",
                         execution_id="ex-9", data={"nodes": 3})

    assert hasil == {"ops": True}
    assert rec.n == 1
    call = rec.calls[0]
    assert call["url"] == "https://siem.example/hook"
    assert call["method"] == "POST"
    body = call["json"]
    assert body["event"] == "n8n.workflow.success"
    assert body["group"] == "n8n.workflow"
    assert body["level"] == "info"
    assert body["workflow_id"] == "wf-1"
    assert body["execution_id"] == "ex-9"
    assert body["data"] == {"nodes": 3}
    assert body["event_id"] and body["iso"].endswith("Z")
    # Terkirim ke semua tujuan -> spool bersih.
    assert b.spool_size() == 0


def test_b2_syslog_frame_rfc5424():
    """B2: syslog -> frame RFC 5424 dengan PRI benar (facility 16, info=6)."""
    rec = Recorder()
    d = syslog(rec, facility=16, app_name="katalir")
    LS.EventBus([d]).emit_event("n8n.workflow.started", workflow_id="w")

    assert rec.n == 1
    frame = rec.calls[0]["frame"]
    # Layout RFC 5424: <PRI>VERSION SP TIMESTAMP SP HOSTNAME SP APP-NAME
    #                  SP PROCID SP MSGID SP SD MSG
    assert frame.startswith("<134>1 ")          # PRI = 16*8 + 6 = 134
    parts = frame.split(" ")
    assert parts[0] == "<134>1"                 # PRI + VERSION
    assert len(parts) >= 7
    assert parts[1] != "-"                      # TIMESTAMP
    assert parts[2] != "-"                      # HOSTNAME (dari make_event)
    assert parts[3] == "katalir"                # APP-NAME
    assert parts[4] == "-"                      # PROCID
    assert parts[5] == "n8n.workflow.started"   # MSGID
    assert parts[6] == "-"                      # STRUCTURED-DATA
    # MSG diawali JSON tepat setelah STRUCTURED-DATA "- " (SD kosong).
    idx = frame.find(' - {"')
    assert idx > 0
    body = json.loads(frame[idx + 3:])
    assert body["event"] == "n8n.workflow.started"


def test_b3_sentry_envelope_dan_key_masked():
    """B3: sentry -> envelope 3 baris; DSN public key TIDAK dikembalikan."""
    rec = Recorder()
    d = sentry(rec)
    LS.EventBus([d]).emit_event("n8n.workflow.failed", level="error",
                                data={"msg": "boom"})

    assert rec.n == 1
    lines = rec.calls[0]["envelope"].strip().splitlines()
    assert len(lines) == 3
    head = json.loads(lines[0])
    assert "ingest.sentry.io/42" in head["dsn"]
    item = json.loads(lines[1])
    assert item["type"] == "event"
    body = json.loads(lines[2])
    assert body["level"] == "error"
    assert body["extra"]["event"] == "n8n.workflow.failed"
    # Header auth memuat sentry_key (memang perlu) tetapi `config()`
    # tidak pernah mengembalikan DSN utuh.
    assert "sentry_key=pub123" in rec.calls[0]["headers"]["X-Sentry-Auth"]
    assert d.config()["public_key"] == "***"


# ---------------------------------------------------------------------------
# DURABILITY (2)
# ---------------------------------------------------------------------------
def test_d1_spool_menyimpan_kegagalan_dan_flush_mengirim_ulang():
    """D1: tujuan gagal -> event TETAP di spool, lalu terkirim saat flush."""
    rec = Recorder(ok=False)
    d = webhook(rec)
    b = LS.EventBus([d])
    b.emit_event("n8n.workflow.started", workflow_id="w1")

    assert rec.n == 1                    # dicoba
    assert b.spool_size() == 1           # GAGAL -> tetap tersimpan
    assert d.failed == 1 and d.sent == 0

    rec.ok = True                        # tujuan pulih
    out = b.flush()
    assert out == {"attempted": 1, "delivered": 1, "remaining": 0,
                   "had_destination": True}
    assert rec.n == 2
    assert b.spool_size() == 0


def test_d2_spool_bertahan_melewati_restart(tmp_path):
    """D2: spool ditulis ke disk -> bus BARU memuatnya kembali (re-emit)."""
    path = str(tmp_path / "eventlog.log")
    rec = Recorder(ok=False)
    b1 = LS.EventBus([webhook(rec)], spool_path=path)
    b1.emit_event("n8n.audit.user.login.failed", user_id="u1")
    assert b1.spool_size() == 1
    assert os.path.exists(path)

    # "Restart": bus baru dengan file spool yang sama.
    rec2 = Recorder(ok=True)
    b2 = LS.EventBus([webhook(rec2)], spool_path=path)
    assert b2.spool_size() == 1          # dimuat dari disk
    out = b2.flush()
    assert out["delivered"] == 1
    assert rec2.calls[0]["json"]["event"] == "n8n.audit.user.login.failed"


# ---------------------------------------------------------------------------
# EDGE CASE (3)
# ---------------------------------------------------------------------------
def test_e1_langganan_grup_event_dan_wildcard():
    """E1: `subscribedEvents` menerima nama grup, nama event, dan wildcard."""
    # Grup: `n8n.audit` mencakup semua event audit.
    assert LS.event_matches("n8n.audit.user.login.success", ["n8n.audit"])
    assert LS.event_matches("n8n.audit.twofa.enabled", ["n8n.audit"])
    assert not LS.event_matches("n8n.workflow.started", ["n8n.audit"])
    # Nama event persis.
    assert LS.event_matches("n8n.node.started", ["n8n.node.started"])
    assert not LS.event_matches("n8n.node.finished", ["n8n.node.started"])
    # Wildcard.
    assert LS.event_matches("n8n.audit.user.login.failed", ["n8n.audit.user.*"])
    assert not LS.event_matches("n8n.audit.workflow.created", ["n8n.audit.user.*"])
    # Daftar kosong = SEMUA.
    assert LS.event_matches("n8n.workflow.started", [])
    assert LS.event_matches("n8n.workflow.started", None)
    # Grup diturunkan dari nama (grup terpanjang yang cocok).
    assert LS.event_group("n8n.audit.user.login.success") == "n8n.audit"
    assert LS.event_group("n8n.workflow.failed") == "n8n.workflow"
    assert LS.event_group("katalir.custom") == ""


def test_e2_konfigurasi_cacat_ditolak_tegas():
    """E2: tujuan tanpa field wajib / nilai tak sah -> DestinationError."""
    with pytest.raises(LS.DestinationError):
        LS.build_destination({"type": "webhook"})            # tanpa url
    with pytest.raises(LS.DestinationError):
        LS.build_destination({"type": "webhook", "url": "https://x",
                              "method": "DELETE"})
    with pytest.raises(LS.DestinationError):
        LS.build_destination({"type": "syslog"})             # tanpa host
    with pytest.raises(LS.DestinationError):
        LS.build_destination({"type": "syslog", "host": "h",
                              "protocol": "smoke"})
    with pytest.raises(LS.DestinationError):
        LS.build_destination({"type": "syslog", "host": "h",
                              "protocol": "tls"})            # tanpa tlsCa
    with pytest.raises(LS.DestinationError):
        LS.build_destination({"type": "syslog", "host": "h", "facility": 99})
    with pytest.raises(LS.DestinationError):
        LS.build_destination({"type": "sentry", "dsn": "bukan-url"})
    with pytest.raises(LS.DestinationError):
        LS.build_destination({"type": "unknown"})


def test_e3_anonimisasi_audit_menyembunyikan_data_sensitif():
    """E3: `anonymizeAuditMessages` menutup kredensial pada event audit."""
    rec = Recorder()
    d = webhook(rec, anonymizeAuditMessages=True,
                subscribedEvents=["n8n.audit"])
    b = LS.EventBus([d])
    b.emit_event("n8n.audit.user.credentials.created", user_id="u1",
                 data={"name": "gmail", "api_key": "sk-abcdefghijklmnop1234",
                       "email": "budi@example.com"})

    body = rec.calls[0]["json"]
    flat = json.dumps(body)
    assert "sk-abcdefghijklmnop1234" not in flat
    assert body["anonymized"] is True

    # Event NON-audit tidak dianonimkan (perilaku n8n: hanya n8n.audit.*).
    rec2 = Recorder()
    d2 = webhook(rec2, anonymizeAuditMessages=True)
    LS.EventBus([d2]).emit_event("n8n.workflow.started",
                                 data={"api_key": "sk-abcdefghijklmnop1234"})
    assert "anonymized" not in rec2.calls[0]["json"]


# ---------------------------------------------------------------------------
# PERFORMANCE (2)
# ---------------------------------------------------------------------------
def test_p1_1000_event_fan_out_cepat():
    """P1: 1000 event × 3 tujuan selesai jauh di bawah 3 detik."""
    import time
    recs = [Recorder(), Recorder(), Recorder()]
    dests = [webhook(recs[0], label="a"), webhook(recs[1], label="b"),
             sentry(recs[2], label="c")]
    b = LS.EventBus(dests)
    t0 = time.perf_counter()
    for i in range(1000):
        b.emit_event("n8n.workflow.started", workflow_id=f"w{i}")
    elapsed = time.perf_counter() - t0
    assert elapsed < 3.0, f"terlalu lambat: {elapsed:.3f}s"
    assert recs[0].n == 1000 and recs[1].n == 1000 and recs[2].n == 1000


def test_p2_spool_dibatasi_tidak_tumbuh_tanpa_batas():
    """P2: spool menghormati `max_spool` walau tujuan terus gagal."""
    rec = Recorder(ok=False)
    b = LS.EventBus([webhook(rec)], max_spool=50)
    for i in range(500):
        b.emit_event("n8n.workflow.failed", workflow_id=f"w{i}")
    assert b.spool_size() == 50
    # Yang tersisa adalah event PALING BARU (bukan paling lama).
    assert b._spool[-1]["workflow_id"] == "w499"


# ---------------------------------------------------------------------------
# SECURITY (2)
# ---------------------------------------------------------------------------
def test_s1_circuit_breaker_menghentikan_pengiriman_setelah_batas():
    """S1: 5 kegagalan dalam jendela -> pengiriman BERHENTI (tidak membanjiri
    downstream yang sedang bermasalah), tujuan lain tetap jalan."""
    now = [1000.0]
    rec_bad = Recorder(ok=False)
    rec_good = Recorder(ok=True)
    bad = LS.build_destination(
        {"type": "webhook", "label": "bad", "url": "https://bad.example",
         "circuitBreaker": {"maxFailures": 3, "failureWindow": 60000}},
        transport=rec_bad, clock=lambda: now[0])
    good = LS.build_destination(
        {"type": "webhook", "label": "good", "url": "https://good.example"},
        transport=rec_good, clock=lambda: now[0])
    b = LS.EventBus([bad, good])

    for i in range(5):
        b.emit_event("n8n.workflow.failed", workflow_id=f"w{i}")

    assert bad.breaker.is_open is True
    assert rec_bad.n == 3               # hanya 3 percobaan, lalu berhenti
    assert bad.skipped >= 2
    assert rec_good.n == 5              # tujuan sehat TIDAK terpengaruh
    snap = bad.stats()["circuit_breaker"]
    assert snap["open"] is True and snap["open_count"] == 1

    # Setelah cooldown, breaker half-open -> percobaan diizinkan lagi.
    now[0] += 120.0
    assert bad.breaker.is_open is False


def test_s2_dsn_dan_header_tidak_bocor_di_config():
    """S2: `config()`/statistik tidak pernah memuat DSN utuh atau token header."""
    d = sentry(Recorder(), dsn="https://secretkey@o9.ingest.sentry.io/7")
    cfg = d.config()
    assert "secretkey" not in json.dumps(cfg)
    assert cfg["public_key"] == "***"

    h = webhook(Recorder(), sendHeaders=True, headerParameters={
        "parameters": [{"name": "Authorization", "value": "Bearer supersecret"}]})
    st = json.dumps(h.stats())
    assert "supersecret" not in st


# ---------------------------------------------------------------------------
# TAMBAHAN: pabrik dari env, bridge, dan fan-out multi-tujuan
# ---------------------------------------------------------------------------
def test_x1_destinations_from_env_mengikuti_flag_managed():
    """X1: hanya dibaca bila `MANAGED_BY_ENV=true` (pola n8n v2.19.0+)."""
    specs = [{"type": "webhook", "label": "ops",
              "url": "https://x.example", "subscribedEvents": ["n8n.audit"]},
             {"type": "syslog", "label": "soc", "host": "10.0.0.1"}]
    payload = json.dumps(specs)

    # Flag tidak diset -> TIDAK membaca apa pun.
    assert LS.destinations_from_env({}) == []
    assert LS.destinations_from_env(
        {"KATALIR_LOG_STREAMING_DESTINATIONS": payload}) == []

    env = {"KATALIR_LOG_STREAMING_MANAGED_BY_ENV": "true",
           "KATALIR_LOG_STREAMING_DESTINATIONS": payload}
    rec = Recorder()
    dests = LS.destinations_from_env(env, transport=rec)
    assert [d.type for d in dests] == ["webhook", "syslog"]
    assert dests[0].subscribed_events == ["n8n.audit"]

    # Satu entri cacat dilewati, entri sehat tetap dibangun.
    env2 = {"KATALIR_LOG_STREAMING_MANAGED_BY_ENV": "true",
            "KATALIR_LOG_STREAMING_DESTINATIONS": json.dumps(
                [{"type": "webhook"}, {"type": "syslog", "host": "h"}])}
    dests2 = LS.destinations_from_env(env2, transport=rec)
    assert [d.type for d in dests2] == ["syslog"]

    with pytest.raises(LS.DestinationError):
        LS.destinations_from_env(
            {"KATALIR_LOG_STREAMING_MANAGED_BY_ENV": "true",
             "KATALIR_LOG_STREAMING_DESTINATIONS": "{bukan json"})


def test_x2_fan_out_ke_semua_tujuan_dan_hormati_langganan():
    """X2: tiga tujuan dengan langganan berbeda menerima tepat event-nya."""
    ra, rb, rc = Recorder(), Recorder(), Recorder()
    da = webhook(ra, label="audit-only", subscribedEvents=["n8n.audit"])
    db_ = syslog(rb, label="wf-only", subscribedEvents=["n8n.workflow"])
    dc = sentry(rc, label="all")
    b = LS.EventBus([da, db_, dc])

    b.emit_event("n8n.audit.user.login.success", user_id="u")
    b.emit_event("n8n.workflow.success", workflow_id="w")

    assert ra.n == 1 and rb.n == 1 and rc.n == 2
    assert ra.calls[0]["json"]["event"].startswith("n8n.audit")
    assert rb.calls[0]["json"]["event"].startswith("n8n.workflow")


def test_x3_bridge_map_dan_stream_helper():
    """X3: `stream()` menerjemahkan nama Katalir -> nama n8n."""
    assert LS.BRIDGE_MAP["workflow_success"] == "n8n.workflow.success"
    assert LS.BRIDGE_MAP["mfa_enabled"] == "n8n.audit.twofa.enabled"
    assert LS.BRIDGE_MAP["execution_data_revealed"] == \
        "n8n.audit.execution.data.revealed"

    rec = Recorder()
    LS.set_bus(LS.EventBus([webhook(rec)]))
    try:
        LS.stream("workflow_failed", workflow_id="w1", level="error",
                  data={"err": "x"})
        assert rec.n == 1
        assert rec.calls[0]["json"]["event"] == "n8n.workflow.failed"
        assert rec.calls[0]["json"]["level"] == "error"
    finally:
        LS.set_bus(None)


def test_x4_make_event_menormalkan_level():
    """X4: level `warning` -> `warn`; level liar -> `info` (tidak meledak)."""
    assert LS.make_event("n8n.workflow.started", level="warning")["level"] == "warn"
    assert LS.make_event("n8n.workflow.started", level="nonsense")["level"] == "info"
    ev = LS.make_event("n8n.audit.user.login.failed", user_id="u7")
    assert ev["group"] == "n8n.audit"
    assert ev["user_id"] == "u7"
    assert isinstance(ev["ts"], float)
