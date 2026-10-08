# -*- coding: utf-8 -*-
"""Regresi untuk perbaikan HARD TEST (docs/hard-test-limits.md).

Setiap tes di sini mengunci satu batas yang ditemukan hard test, supaya
perbaikan tidak dapat mundur diam-diam. Menjalankan:

    python -m pytest -q tests/test_hard_test_fixes.py
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ---------------------------------------------------------------------------
# F10 — batas node/edge harus SATU nilai di semua jalur tulis
# ---------------------------------------------------------------------------
def test_batas_graf_konsisten_lintas_jalur_tulis():
    import api_server as AS
    import flow_limits as FL
    import mcp_server as MS
    import workflow_templates as WT

    assert AS.MAX_WORKFLOW_NODES == MS.MAX_FLOW_NODES == WT.MAX_NODES, (
        "batas node berbeda antar jalur tulis — inilah bug yang ditemukan "
        f"hard test: API={AS.MAX_WORKFLOW_NODES} MCP={MS.MAX_FLOW_NODES} "
        f"templates={WT.MAX_NODES}")
    assert AS.MAX_WORKFLOW_EDGES == WT.MAX_EDGES
    assert AS.MAX_WORKFLOW_NODES == FL.MAX_FLOW_NODES
    assert AS.MAX_WORKFLOW_EDGES == FL.MAX_FLOW_EDGES


def test_batas_graf_batas_inclusive():
    import flow_limits as FL
    import workflow_templates as WT

    def flow(n, e=0):
        nodes = [{"id": f"n{i}", "data": {"kind": "noop", "config": {}}}
                 for i in range(n)]
        edges = []
        for i in range(e):
            s, t = i % max(1, n), (i + 1) % max(1, n)
            if s == t:
                t = (s + 1) % max(1, n)
            edges.append({"source": f"n{s}", "target": f"n{t}"})
        return {"nodes": nodes, "edges": edges}

    WT.validate_flow_data(flow(FL.MAX_FLOW_NODES))          # tepat di batas
    with pytest.raises(WT.TemplateError):
        WT.validate_flow_data(flow(FL.MAX_FLOW_NODES + 1))  # di atas batas
    WT.validate_flow_data(flow(50, FL.MAX_FLOW_EDGES))
    with pytest.raises(WT.TemplateError):
        WT.validate_flow_data(flow(50, FL.MAX_FLOW_EDGES + 1))


# ---------------------------------------------------------------------------
# F6 — sandbox: batas memori, str.format, pemotongan error
# ---------------------------------------------------------------------------
def test_sandbox_batas_memori_ditegakkan():
    """Dulu alokasi 4 GB berhasil (cap 128 MB tidak berlaku di Windows)."""
    import code_sandbox as CS

    cap = CS.CODE_MEMORY_MB
    # Jauh di atas cap -> harus GAGAL, apa pun mekanismenya.
    h = CS.execute(f"b = bytes({(cap * 4)}*1024*1024)\nprint(len(b))\n", "python")
    assert h["ok"] is False, f"alokasi {cap*4}MB tidak diblokir: {h}"
    # Alokasi kecil harus tetap berjalan (tidak ada false positive).
    h2 = CS.execute("print(len(bytes(4*1024*1024)))\n", "python")
    assert h2["ok"] is True, f"alokasi wajar ikut diblokir: {h2}"


def test_sandbox_capabilities_mengaku_mekanisme_memori():
    import code_sandbox as CS
    cap = CS.capabilities()
    assert "memory_enforced" in cap and "memory_mechanism" in cap
    assert cap["memory_enforced"] is True, cap


def test_sandbox_str_format_dunder_ditolak():
    """CVE-2026-76825 class: str.format melewati penjaga atribut."""
    import code_sandbox as CS
    for kode in ("print('{0.__class__}'.format(1))",
                 "print('{0.__class__.__mro__}'.format(1))",
                 "print('{0.__class__.__base__.__subclasses__}'.format(1))",
                 "print('{0.__init__.__globals__}'.format(print))"):
        with pytest.raises(CS.SandboxError):
            CS.validate(kode, "python")


def test_sandbox_format_sah_tidak_ikut_diblokir():
    """Tidak boleh ada false positive pada format spec biasa."""
    import code_sandbox as CS
    for kode in ("print('{0:.2f}'.format(3.14159))",
                 "print('Halo {nama}'.format(nama='A'))",
                 "print('{0}-{1}'.format(1, 2))",
                 "print('{0[0]}'.format([1, 2, 3]))"):
        CS.validate(kode, "python")     # tidak boleh melempar


def test_sandbox_error_dipotong():
    import code_sandbox as CS
    kode = "raise ValueError('x' * 200000)\n"
    h = CS.execute(kode, "python")
    assert h["ok"] is False
    assert len(h["error"]) <= CS.CODE_MAX_OUTPUT_BYTES + 200, (
        f"error tidak dipotong: {len(h['error'])} byte")


def test_sandbox_escape_python_tetap_diblokir_saat_eksekusi():
    """Eksekusi nyata, bukan hanya validasi statis."""
    import code_sandbox as CS
    for kode in ("import os\nprint(os.getcwd())",
                 "print(open('/etc/passwd').read())",
                 "print(().__class__.__bases__[0].__subclasses__())"):
        h = CS.execute(kode, "python")
        assert h["ok"] is False, f"escape berhasil: {kode!r} -> {h}"


# ---------------------------------------------------------------------------
# F7 — secrets: batas ukuran cache & path traversal
# ---------------------------------------------------------------------------
def test_vault_cache_melewati_nilai_oversize():
    import vault_cache as VC
    VC.invalidate()
    VC.reset_stats()

    kecil = {"token": "x" * 100}
    VC.put("kecil@x.test", "telegram", kecil)
    ok, _ = VC.get("kecil@x.test", "telegram")
    assert ok is True, "nilai kecil harus di-cache"

    besar = {"blob": "x" * (VC.MAX_VALUE_BYTES + 1024)}
    VC.put("besar@x.test", "telegram", besar)
    ok2, _ = VC.get("besar@x.test", "telegram")
    assert ok2 is False, "nilai oversize tidak boleh di-cache"
    assert VC.stats()["skipped_oversize"] >= 1
    VC.invalidate()


def test_secret_ref_path_traversal_ditolak():
    import secrets_provider as SP
    for ref in ("secret://../../etc/passwd",
                "secret://katalir/../../x",
                "secret://a\\..\\b",
                "secret://katalir/" + "a" * 600):
        with pytest.raises(SP.SecretRefError):
            SP.parse_ref(ref)


def test_secret_ref_normal_masih_diterima():
    import secrets_provider as SP
    assert SP.parse_ref("secret://katalir/telegram") == ("katalir", "telegram", None)
    assert SP.parse_ref("secret://aws/prod/db") == ("aws", "prod", "db")


# ---------------------------------------------------------------------------
# F3 — backoff tidak boleh melewati cap
# ---------------------------------------------------------------------------
def test_backoff_tidak_melewati_cap():
    import retry_policy as RP
    cap = RP.MAX_DELAY_SECONDS
    vals = [RP.backoff_delay(a) for a in range(1, 500)]
    assert max(vals) <= cap + 1e-9, (
        f"delay melewati cap: max={max(vals)} cap={cap}")
    assert all(v == v for v in vals), "ada NaN"


def test_backoff_tetap_memiliki_jitter():
    """Jitter tidak boleh hilang (anti thundering herd)."""
    import retry_policy as RP
    vals = [RP.backoff_delay(1) for _ in range(500)]
    assert len(set(round(v, 6) for v in vals)) > 50, "jitter hilang"
    # Di dekat cap jitter harus tetap menyebar (tidak semua = cap).
    vals_cap = [RP.backoff_delay(50) for _ in range(500)]
    assert max(vals_cap) - min(vals_cap) > 0.5, "tidak ada jitter di dekat cap"
    assert max(vals_cap) <= RP.MAX_DELAY_SECONDS + 1e-9


# ---------------------------------------------------------------------------
# F9 — memory: batas panjang content & clamp top_k
# ---------------------------------------------------------------------------
def test_memory_batas_panjang_content():
    import memory_manager as MM
    mm = MM.MemoryManager("hard-test-user")
    with pytest.raises(ValueError):
        mm.remember("x" * (MM.MAX_CONTENT_CHARS + 1))
    with pytest.raises(ValueError):
        mm.remember("   ")


def test_memory_top_k_clamp_eksplisit():
    import inspect
    import memory_manager as MM
    src = inspect.getsource(MM.MemoryManager.recall)
    assert "MAX_RECALL_TOP_K" in src, "clamp top_k tidak memakai konstanta"


# ---------------------------------------------------------------------------
# F4/F5 — batas dapat disetel lewat env
# ---------------------------------------------------------------------------
def test_batas_dapat_disetel_lewat_env():
    import parallel_fanout as PF
    import subworkflow as SW
    assert isinstance(PF.MAX_BRANCHES, int) and PF.MAX_BRANCHES > 0
    assert isinstance(SW.MAX_DEPTH, int) and SW.MAX_DEPTH > 0

    # Buktikan env benar-benar dibaca (proses terpisah, modul dimuat ulang).
    import subprocess
    kode = (
        "import os,sys; sys.path.insert(0, r'%s');"
        "import subworkflow as SW; print(SW.MAX_DEPTH)" % ROOT)
    env = dict(os.environ, SUBWORKFLOW_MAX_DEPTH="7")
    out = subprocess.run([sys.executable, "-c", kode], capture_output=True,
                         text=True, env=env, timeout=60)
    assert out.stdout.strip() == "7", f"env tidak dibaca: {out.stdout!r} {out.stderr[:200]}"
