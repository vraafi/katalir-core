"""Uji Fitur #8 — Distributed tracing (OpenTelemetry / LangSmith).

12 kategori skenario: 3 basic, 2 durability, 3 edge, 2 performance,
2 security (+ ekstra). Memakai transport disuntik sehingga pengkodean
protobuf NYATA dijalankan tanpa jaringan.
"""
from __future__ import annotations

import json
import os
import struct
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tracing as T  # noqa: E402


# ---------------------------------------------------------------------------
# Perkakas uji
# ---------------------------------------------------------------------------

class Recorder:
    """Transport OTLP palsu yang merekam payload protobuf nyata."""

    def __init__(self, status: int = 200, body: str = "{}"):
        self.calls: list[tuple[str, bytes, dict]] = []
        self.status = status
        self.body = body

    def __call__(self, url: str, body: bytes, headers: dict):
        self.calls.append((url, body, dict(headers)))
        return self.status, self.body

    @property
    def count(self) -> int:
        return len(self.calls)

    @property
    def last_body(self) -> bytes:
        return self.calls[-1][1] if self.calls else b""


def exporter(rec: Recorder, **kw) -> T.OTLPExporter:
    kw.setdefault("endpoint", "http://collector.test:4318")
    kw.setdefault("transport", rec)
    kw.setdefault("service_version", "9.9.9")
    return T.OTLPExporter(**kw)


def tracer(rec: Recorder | None = None, **kw) -> T.Tracer:
    exp = exporter(rec) if rec is not None else None
    return T.Tracer(exporter=exp, auto_flush=False, **kw)


def has_hex(body: bytes, hexstr: str) -> bool:
    return bytes.fromhex(hexstr) in body


def has_str(body: bytes, text: str) -> bool:
    return text.encode() in body


# ===========================================================================
# B — BASIC
# ===========================================================================

def test_b1_traceparent_format_and_parse():
    """B1: header traceparent versi 00 dibentuk & diurai dengan benar."""
    tid = T.new_trace_id()
    sid = T.new_span_id()
    tp = T.format_traceparent(tid, sid)
    assert tp == f"00-{tid}-{sid}-01"
    assert T.is_valid_traceparent(tp)
    ctx = T.parse_traceparent(tp)
    assert ctx == {"trace_id": tid, "span_id": sid, "sampled": True, "flags": 1}


def test_b2_workflow_and_node_spans_exported():
    """B2: satu eksekusi memancarkan span workflow.execute + node.execute."""
    rec = Recorder()
    tr = tracer(rec)
    et = T.start_execution(tr, workflow_id="wf-1", workflow_name="Demo",
                           node_count=2, execution_id="ex-1")
    with et.node(node_id="n1", node_name="HTTP Request",
                 node_type="n8n-nodes-base.httpRequest"):
        pass
    root = et.finish(status="success")
    assert tr.flush()["ok"] is True
    assert rec.count == 1
    body = rec.last_body
    # protobuf memuat trace_id, span root, dan nama span berupa string.
    assert has_hex(body, root.trace_id)
    assert has_hex(body, root.span_id)
    assert has_str(body, T.SPAN_WORKFLOW)
    assert has_str(body, T.SPAN_NODE)
    assert has_str(body, "n8n.workflow.id")
    assert has_str(body, "wf-1")


def test_b3_otlp_headers_and_protobuf_content_type():
    """B3: header OTLP (auth + content-type) benar, endpoint jadi /v1/traces."""
    rec = Recorder()
    exp = T.OTLPExporter(
        "https://api.smith.langchain.com/otel", transport=rec,
        headers={"x-api-key": "ls-secret", "Langsmith-Project": "katalir"})
    assert exp.url == "https://api.smith.langchain.com/otel/v1/traces"
    tr = T.Tracer(exporter=exp, auto_flush=False)
    et = T.start_execution(tr, workflow_id="wf-2", execution_id="ex-2")
    et.finish(status="success")
    tr.flush()
    url, _, headers = rec.calls[-1]
    assert url.endswith("/v1/traces")
    assert headers["x-api-key"] == "ls-secret"
    assert headers["Langsmith-Project"] == "katalir"
    assert headers["Content-Type"] == "application/x-protobuf"


# ===========================================================================
# D — DURABILITY
# ===========================================================================

def test_d1_spool_survives_failed_export():
    """D1: ekspor gagal -> span dikembalikan ke antrean, lalu berhasil."""
    rec = Recorder(status=503, body="nope")
    tr = tracer(rec)
    et = T.start_execution(tr, workflow_id="wf-d1", execution_id="ex-d1")
    et.finish(status="success")
    out = tr.flush()
    assert out["ok"] is False
    assert tr.pending_count() == 1, "span gagal hilang, bukan dikembalikan"
    rec.status = 200
    out2 = tr.flush()
    assert out2["ok"] is True
    assert tr.pending_count() == 0


def test_d2_spool_bounded_by_max_spool():
    """D2: antrean tidak tumbuh tanpa batas saat backend mati terus-menerus."""
    rec = Recorder(status=500)
    tr = tracer(rec)
    for i in range(T.MAX_SPOOL + 50):
        et = T.start_execution(tr, workflow_id=f"wf-{i}",
                               execution_id=f"ex-{i}")
        et.finish(status="success")
        if i % 200 == 0:
            tr.flush()
    tr.flush()
    assert tr.pending_count() <= T.MAX_SPOOL


# ===========================================================================
# E — EDGE
# ===========================================================================

def test_e1_nested_node_uses_workflow_as_parent():
    """E1: span node memakai span workflow sebagai induk (trace sama)."""
    tr = tracer()
    et = T.start_execution(tr, workflow_id="wf-e1", execution_id="ex-e1")
    sp = et.start_node(node_id="n1", node_name="A", node_type="t")
    et.finish_node(sp)
    assert sp.trace_id == et.span.trace_id
    assert sp.parent_span_id == et.span.span_id


def test_e2_subworkflow_and_resume_links():
    """E2: sub-workflow jadi anak; resume setelah wait memakai span link."""
    tr = tracer()
    parent = T.start_execution(tr, workflow_id="wf-parent",
                               execution_id="ex-p")
    child = T.start_execution(tr, workflow_id="wf-child", execution_id="ex-c",
                              traceparent=parent.traceparent)
    assert child.span.trace_id == parent.span.trace_id
    assert child.span.parent_span_id == parent.span.span_id
    resumed = T.start_execution(tr, workflow_id="wf-parent",
                                execution_id="ex-p2")
    resumed.link_previous(parent.span.trace_id, parent.span.span_id)
    assert resumed.span.links[0]["reason"] == "wait_resume"
    assert resumed.span.links[0]["span_id"] == parent.span.span_id


def test_e3_config_validation_rejects_bad_input():
    """E3: konfigurasi tak sah ditolak (endpoint, protokol, header, sampler)."""
    with pytest.raises(T.TracingError):
        T.OTLPExporter("ftp://nope.test")
    with pytest.raises(T.TracingError):
        T.OTLPExporter("http://x.test", protocol="carrier-pigeon")
    with pytest.raises(T.TracingError):
        T.build_headers("no-equals-sign")
    with pytest.raises(T.TracingError):
        T.Sampler(1.5)
    with pytest.raises(T.TracingError):
        T.Sampler(-0.1)
    with pytest.raises(T.TracingError):
        T.format_traceparent("zz", "00" * 8)
    with pytest.raises(T.TracingError):
        T.crashed_attributes(detector="made-up-detector")


# ===========================================================================
# P — PERFORMANCE
# ===========================================================================

def test_p1_1000_spans_encode_and_export():
    """P1: 1.000 span dikodekan & diekspor dalam waktu wajar."""
    rec = Recorder()
    tr = tracer(rec)
    t0 = time.perf_counter()
    for i in range(200):
        et = T.start_execution(tr, workflow_id=f"wf-{i}",
                               execution_id=f"ex-{i}", node_count=4)
        for j in range(4):
            with et.node(node_id=f"n{j}", node_name=f"Node {j}",
                         node_type="n8n-nodes-base.set"):
                pass
        et.finish(status="success")
    elapsed = time.perf_counter() - t0
    assert tr.started == 1000, tr.started
    assert elapsed < 20.0, f"terlalu lambat: {elapsed:.2f}s"


def test_p2_sampling_drops_whole_trace_consistently():
    """P2: sampler rasio -> keputusan konsisten per trace-id (bukan per span)."""
    s = T.Sampler(0.25)
    kept = 0
    total = 2000
    seen: dict[str, bool] = {}
    for _ in range(total):
        tid = T.new_trace_id()
        d = s.should_sample(tid)
        kept += 1 if d else 0
        seen[tid] = d
        assert s.should_sample(tid) == d, "keputusan berubah untuk trace sama"
    ratio = kept / total
    assert 0.18 < ratio < 0.33, f"rasio di luar dugaan: {ratio:.3f}"


# ===========================================================================
# S — SECURITY
# ===========================================================================

def test_s1_inbound_traceparent_validated_strictly():
    """S1: traceparent cacat DITOLAK (bukan dipercaya apa adanya)."""
    zero_trace = "00-" + "0" * 32 + "-" + "1" * 16 + "-01"
    zero_span = "00-" + "1" * 32 + "-" + "0" * 16 + "-01"
    ff = "ff-" + "1" * 32 + "-" + "1" * 16 + "-01"
    cases = [
        "",
        "garbage",
        "00-abc-def-01",
        zero_trace,
        zero_span,
        ff,
        "00-" + "1" * 32 + "-" + "1" * 16,          # tanpa flags
        "00-" + "1" * 31 + "-" + "1" * 16 + "-01",  # trace-id kurang 1 hex
        "00-" + "1" * 32 + "-" + "1" * 15 + "-01",  # span-id kurang 1 hex
        "00-" + "1" * 32 + "-" + "1" * 16 + "-zz",  # flags bukan hex
        "00-" + "g" * 32 + "-" + "1" * 16 + "-01",  # trace-id bukan hex
    ]
    for c in cases:
        assert not T.is_valid_traceparent(c), f"lolos padahal cacat: {c!r}"
        assert T.parse_traceparent(c) is None

    # Huruf BESAR diterima: W3C §3.2.2 mewajibkan huruf kecil saat
    # MENGHASILKAN, tetapi penerima boleh menerima keduanya. Pengurai
    # menormalkan ke huruf kecil sebelum memakai nilainya.
    upper = "00-" + "A" * 32 + "-" + "B" * 16 + "-01"
    assert T.is_valid_traceparent(upper)
    assert T.parse_traceparent(upper) == {"trace_id": "a" * 32,
                                          "span_id": "b" * 16,
                                          "sampled": True, "flags": 1}

    # traceparent sah dipakai sebagai induk; trace_id tetap dari pemanggil.
    tr = tracer()
    good = "00-" + "a" * 32 + "-" + "b" * 16 + "-01"
    et = T.start_execution(tr, workflow_id="w", traceparent=good)
    assert et.span.trace_id == "a" * 32
    assert et.span.parent_span_id == "b" * 16

    # traceparent cacat diabaikan -> trace_id BARU, bukan nilai penyerang.
    et2 = T.start_execution(tr, workflow_id="w", traceparent=zero_trace)
    assert et2.span.trace_id != "0" * 32
    assert et2.span.parent_span_id == ""

    # Span yang dibangkitkan selalu huruf kecil (W3C §3.2.2).
    for _ in range(50):
        tp = T.format_traceparent(T.new_trace_id(), T.new_span_id())
        assert tp == tp.lower()


def test_s2_agent_pii_can_be_excluded_and_secrets_not_leaked():
    """S2: input/output agen dapat dimatikan; rahasia tidak ikut ke span."""
    # Dengan record_inputs=False, atribut prompt/args/hasil TIDAK dibuat.
    attrs_off = T.agent_attributes(agent_name="Bot", model="openai/gpt-4o",
                                   prompt="RAHASIA-123")
    assert "gen_ai.prompt" in attrs_off   # fungsi murni: masih ada
    # Simulasi gerbang n8n: N8N_AGENTS_TRACING_RECORD_INPUTS=false
    env = {"N8N_OTEL_ENABLED": "true", "N8N_AGENTS_TRACING_ENABLED": "true",
           "N8N_AGENTS_TRACING_RECORD_INPUTS": "false",
           "N8N_AGENTS_TRACING_RECORD_OUTPUTS": "false"}
    assert T.agents_tracing_enabled(env) is True
    # tool span tanpa arguments/result saat input/output dimatikan
    tool_off = T.agent_attributes(operation="execute_tool", tool_name="search")
    assert "gen_ai.tool.call.arguments" not in tool_off
    assert "gen_ai.tool.call.result" not in tool_off

    # Atribut tetap tidak boleh memuat header auth dari exporter.
    rec = Recorder()
    exp = T.OTLPExporter("https://ls.test/otel", transport=rec,
                         headers={"x-api-key": "SUPER-SECRET-KEY"})
    tr = T.Tracer(exporter=exp, auto_flush=False)
    et = T.start_execution(tr, workflow_id="wf-s2", execution_id="ex-s2")
    et.finish(status="success")
    tr.flush()
    body = rec.last_body
    assert b"SUPER-SECRET-KEY" not in body, "kunci API bocor ke payload span"
    assert b"x-api-key" not in body


# ===========================================================================
# X — EKSTRA
# ===========================================================================

def test_x1_env_factory_matches_n8n_variables():
    """X1: env `N8N_OTEL_*` + `OTEL_EXPORTER_OTLP_*` dibaca dengan benar."""
    env = {
        "N8N_OTEL_ENABLED": "true",
        "N8N_OTEL_EXPORTER_OTLP_ENDPOINT": "https://api.smith.langchain.com/otel",
        "N8N_OTEL_EXPORTER_OTLP_HEADERS": "x-api-key=ls-abc,Langsmith-Project=prod",
        "N8N_OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
        "N8N_OTEL_TRACES_SAMPLE_RATE": "0.5",
        "N8N_OTEL_TRACES_PRODUCTION_ONLY": "false",
        "N8N_OTEL_SERVICE_NAME": "katalir",
        "N8N_OTEL_SERVICE_VERSION": "2.1.0",
        "N8N_INSTANCE_ROLE": "worker",
        "N8N_AGENTS_TRACING_ENABLED": "true",
    }
    assert T.enabled(env) is True
    assert T.production_only(env) is False
    assert T.agents_tracing_enabled(env) is True
    d = T.describe(env)
    assert d["sample_rate"] == 0.5
    assert d["headers"] == ["Langsmith-Project", "x-api-key"]
    assert d["url"] == "https://api.smith.langchain.com/otel/v1/traces"
    assert d["instance_role"] == "worker"
    assert d["service_name"] == "katalir"
    assert "langsmith" in d["backends"]
    assert d["span_names"] == {"workflow": "workflow.execute",
                               "node": "node.execute"}


def test_x2_crashed_execution_span():
    """X2: span eksekusi crash (2.42.0) punya atribut detektor yang benar."""
    rec = Recorder()
    tr = tracer(rec)
    sp = T.trace_crashed_execution(
        tr, workflow_id="wf-c", workflow_name="Crashy", execution_id="ex-c",
        detector="stall", reconstructed=False)
    assert sp.status_code == T.STATUS_ERROR
    assert sp.attributes["n8n.execution.status"] == "crashed"
    assert sp.attributes["n8n.execution.error_type"] == "WorkflowCrashedError"
    assert sp.attributes["n8n.execution.crash.detector"] == "stall"
    assert sp.attributes["n8n.execution.reconstructed"] is False
    assert "n8n.workflow.node_count" not in sp.attributes
    assert sp.ended
    assert tr.flush()["ok"] is True
    assert has_str(rec.last_body, "n8n.execution.crash.detector")
    assert has_str(rec.last_body, "stall")

    # Pergantian nama detektor tidak sah sudah ditolak di test E3.


def test_x3_agent_and_tool_span_names_and_attributes():
    """X3: span agen `gen_ai.*` + tool `execute_tool <tool>`, nama sesuai n8n."""
    assert T.agent_span_name("Sales Bot") == "Sales Bot.generate"
    assert T.agent_span_name("Sales Bot", streaming=True) == "Sales Bot.stream"
    assert T.tool_span_name("search_web") == "execute_tool search_web"

    a = T.agent_attributes(agent_name="Sales Bot", model="openai/gpt-4o",
                           conversation_id="th-1", agent_id="ag-1",
                           source="workflow", user_id="u-1",
                           execution_id="ex-1", workflow_id="wf-1",
                           node_id="n-1", prompt="hi", tool_count=3)
    assert a["gen_ai.operation.name"] == "invoke_agent"
    assert a["gen_ai.agent.name"] == "Sales Bot"
    assert a["gen_ai.request.model"] == "openai/gpt-4o"
    assert a["gen_ai.conversation.id"] == "th-1"
    assert a["thread_id"] == "th-1"
    assert a["agent_id"] == "ag-1"
    assert a["source"] == "workflow"
    payload = json.loads(a["gen_ai.prompt"])
    assert payload["prompt"] == "hi" and payload["tool_count"] == 3

    t = T.agent_attributes(operation="execute_tool", tool_name="search_web",
                           tool_call_id="c-1", tool_arguments={"q": "x"},
                           tool_result="ok")
    assert t["gen_ai.operation.name"] == "execute_tool"
    assert t["gen_ai.tool.name"] == "search_web"
    assert t["gen_ai.tool.call.id"] == "c-1"
    assert t["gen_ai.tool.call.arguments"] == {"q": "x"}
    assert t["gen_ai.tool.call.result"] == "ok"


def test_x4_protobuf_wire_format_is_valid():
    """X4: struktur protobuf dapat diuraikan (round-trip field penting)."""
    tr = tracer()
    et = T.start_execution(tr, workflow_id="wf-x4", workflow_name="Wire",
                           node_count=1, execution_id="ex-x4",
                           mode="webhook")
    et.finish(status="success")
    body = T.encode_export_request(
        [et.span], T.resource_attributes(service_name="katalir",
                                         service_version="1.2.3"),
        scope_name="katalir.tracing", scope_version="1.0.0")

    # ResourceSpans (field 1) ada.
    assert body[0] == 0x0A
    # Resource attributes dikodekan.
    assert has_str(body, "service.name")
    assert has_str(body, "katalir")
    assert has_str(body, "service.version")
    assert has_str(body, "1.2.3")
    assert has_str(body, "n8n.instance.id")
    assert has_str(body, "n8n.instance.role")
    # Span terenkode dengan trace_id/span_id biner 16/8 byte.
    assert has_hex(body, et.span.trace_id)
    assert has_hex(body, et.span.span_id)
    assert has_str(body, "workflow.execute")
    assert has_str(body, "n8n.execution.mode")
    assert has_str(body, "webhook")

    # start_time_unix_nano ada sebagai fixed64 di dalam span.
    needle = struct.pack("<Q", et.span.start_ns)
    assert needle in body


def test_x5_outbound_traceparent_injection():
    """X5: header keluar diberi traceparent; dapat dimatikan lewat env."""
    tr = tracer()
    et = T.start_execution(tr, workflow_id="wf-x5", execution_id="ex-x5")
    hdrs = T.inject_into_headers({"Content-Type": "application/json"}, et)
    assert hdrs["traceparent"] == et.traceparent
    assert hdrs["Content-Type"] == "application/json"
    off = T.inject_into_headers({}, et,
                                {"N8N_OTEL_TRACES_INJECT_TRACEPARENT": "false"})
    assert "traceparent" not in off
    assert T.inject_into_headers({}, None) == {}


def test_x6_mode_gating_production_only():
    """X6: default hanya mode produksi yang ditrace (seperti n8n)."""
    assert T.should_trace_mode("manual") is False
    assert T.should_trace_mode("webhook") is True
    assert T.should_trace_mode("trigger") is True
    assert T.should_trace_mode("retry") is True
    assert T.should_trace_mode("manual",
                               {"N8N_OTEL_TRACES_PRODUCTION_ONLY": "false"}) \
        is True


def test_x7_scope_of_trace_workflow_helper():
    """X7: `trace_workflow` mengembalikan None saat tracing nonaktif."""
    off = {"N8N_OTEL_ENABLED": "false"}
    assert T.trace_workflow(off, workflow_id="w", mode="webhook") is None
    on = {"N8N_OTEL_ENABLED": "true",
          "N8N_OTEL_EXPORTER_OTLP_ENDPOINT": "http://x.test:4318"}
    got = T.trace_workflow(on, workflow_id="w", mode="webhook")
    assert got is not None
    assert got.span.attributes["n8n.workflow.id"] == "w"
    # manual diblokir oleh production_only default
    assert T.trace_workflow(on, workflow_id="w", mode="manual") is None
