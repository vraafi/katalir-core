# -*- coding: utf-8 -*-
"""Bagian 1 + 2 brief: benchmark vs n8n & self-correcting loop."""
import json

import pytest

import workflow_autofix as af
import workflow_spec as ws


def spec(n_nodes=2, edges=None, name="Test"):
    nodes = [{"id": f"n{i+1}", "kind": "trigger" if i == 0 else "agent",
              "label": f"N{i+1}", "config": {}} for i in range(n_nodes)]
    if edges is None:
        edges = [{"source": f"n{i+1}", "target": f"n{i+2}"}
                 for i in range(n_nodes - 1)]
    return json.dumps({"name": name, "nodes": nodes, "edges": edges})


def bad_spec(kind="no_trigger"):
    """Spec yang PASTI ditolak validator - dipakai untuk uji no-progress.

    Penting: `bad_spec()` justru VALID (node pertama jadi trigger), jadi
    tidak boleh dipakai sebagai contoh spec cacat.
    """
    if kind == "no_trigger":
        return json.dumps({"name": "B", "nodes": [
            {"id": "n1", "kind": "agent", "label": "A", "config": {}}],
            "edges": []})
    if kind == "dup_id":
        return json.dumps({"name": "B", "nodes": [
            {"id": "n1", "kind": "trigger", "label": "A", "config": {}},
            {"id": "n1", "kind": "agent", "label": "B", "config": {}}],
            "edges": []})
    return json.dumps({"name": "B", "nodes": [
        {"id": "n1", "kind": "trigger", "label": "A", "config": {}}],
        "edges": [{"source": "n1", "target": "HANTU"}]})


# ======================================================================
# BAGIAN 1 - 10 kelemahan n8n yang TIDAK boleh ada di Katalir
# ======================================================================

def test_n8n01_tidak_stuck_berjam_jam():
    """#1 Loop punya batas keras waktu DAN jumlah iterasi."""
    assert af.TIME_BUDGET_S == 120.0
    assert af.MAX_ITERATIONS == 10
    calls = []

    def gen():
        calls.append(1)
        return bad_spec()   # selalu invalid (tanpa trigger)

    t = [0.0]

    def clock():
        t[0] += 40.0         # tiap cek jam = 40 detik kerja
        return t[0]

    r = af.run_self_correcting_loop(gen, lambda s, e: s, clock=clock)
    assert r["ok"] is False
    assert r["reason"] == "timeout"
    assert len(calls) >= 1, "generate harus sempat jalan sebelum timeout"
    assert r["iterations"] < af.MAX_ITERATIONS, "timeout harus memotong sebelum batas iterasi"


def test_n8n02_tidak_stop_premature_di_10_node():
    """#2 Workflow 10+ node tidak boleh ditolak sebagai 'terlalu banyak'."""
    for n in (10, 12, 25):
        r = ws.validate_spec(spec(n))
        assert r["ok"] is True, f"{n} node ditolak: {r.get('errors')}"
        assert r["spec"]["nodes"].__len__() == n


def test_n8n03_edge_ke_node_hantu_ditolak():
    """#3 Alamat ke node yang tidak ada = hallucinasi, wajib ditolak."""
    bad = json.dumps({"name": "x", "nodes": [{"id": "n1", "kind": "trigger",
                                              "label": "T", "config": {}}],
                      "edges": [{"source": "n1", "target": "GHOST"}]})
    r = ws.validate_spec(bad)
    assert r["ok"] is False
    assert any("GHOST" in e for e in r["errors"])


def test_n8n03_source_hantu_ditolak():
    bad = json.dumps({"name": "x", "nodes": [{"id": "n1", "kind": "trigger",
                                              "label": "T", "config": {}}],
                      "edges": [{"source": "HANTU", "target": "n1"}]})
    r = ws.validate_spec(bad)
    assert r["ok"] is False
    assert r["errors"]


def test_n8n05_validasi_tidak_false_positive():
    """#5 Spec yang BENAR tidak boleh ditolak (false positive = parah)."""
    r = ws.validate_spec(spec(3))
    assert r["ok"] is True
    assert not r.get("errors")
    assert r["spec"]["name"] == "Test"


def test_n8n05_tanpa_trigger_ditolak_akurat():
    """#5 Sebaliknya: workflow mustahil (tanpa pemicu) harus ditolak."""
    bad = json.dumps({"name": "x", "nodes": [{"id": "n1", "kind": "agent",
                                              "label": "A", "config": {}}],
                      "edges": []})
    r = ws.validate_spec(bad)
    assert r["ok"] is False
    assert any("trigger" in e for e in r["errors"])


def test_n8n07_credential_palsu_ditolak():
    """#7 Node mcp wajib punya provider sah; tanpa itu = credential palsu."""
    bad = json.dumps({"name": "x",
                      "nodes": [{"id": "n1", "kind": "trigger", "label": "T",
                                 "config": {}},
                                {"id": "n2", "kind": "mcp", "label": "M",
                                 "config": {"chat_id": "1"}}],
                      "edges": [{"source": "n1", "target": "n2"}]})
    r = ws.validate_spec(bad)
    assert r["ok"] is False
    assert any("provider" in e for e in r["errors"])


def test_n8n08_workflow_id_hantu_ditolak_saat_muat():
    """#8 Memuat workflow dengan id yang tidak ada harus error jelas."""
    import database as db
    # Sifat anti-fabricasi yang bisa diuji offline: user_id WAJIB ada.
    import inspect
    params = list(inspect.signature(db.get_workflow).parameters)
    assert "workflow_id" in params and "user_id" in params
    with pytest.raises(TypeError):
        db.get_workflow("00000000-0000-0000-0000-000000000000")


# ======================================================================
# BAGIAN 2 - self-correcting loop
# ======================================================================

def test_loop_lulus_diterima_pertama():
    """Spec langsung benar -> 1 iterasi, tanpa kerja sia-sia."""
    n = []
    r = af.run_self_correcting_loop(lambda: (n.append(1), spec(2))[1],
                                    lambda s, e: pytest.fail("tak boleh repair"))
    assert r["ok"] is True
    assert r["iterations"] == 1
    assert r["node_count"] == 2
    assert r["repaired_count"] == 0


def test_loop_memperbaiki_dan_lulus():
    """Rusak lalu diperbaiki -> sukses pada iterasi 2."""
    seq = [bad_spec(), spec(2)]

    def gen():
        return seq.pop(0)

    r = af.run_self_correcting_loop(gen, lambda s, e: spec(2))
    # generate mengembalikan spec rusak (1 node tanpa trigger), repair benar.
    assert r["ok"] is True
    assert r["iterations"] == 2
    assert r["repaired_count"] == 1


def test_loop_no_progress_berhenti_early():
    """Error identik 3x -> berhenti di 3, JANGAN buang sampai 10."""
    n = []

    def gen():
        n.append(1)
        return bad_spec()

    r = af.run_self_correcting_loop(gen, lambda s, e: bad_spec())
    assert r["ok"] is False
    assert r["reason"] == "no_progress", f"alasan stop salah: {r['reason']}"
    assert r["iterations"] == 3, f"harus berhenti di 3, bukan {r['iterations']}"
    assert len(n) == 1, f"generate hanya boleh 1x, dapat {len(n)}"


def test_no_progress_melihat_id_yang_berbeda_sebagai_error_sama():
    """Model ganti nama node tiap retry -> tetap error yang SAMA.

    Ini kasus yang sering menipu: stringify mentah akan melihat
    'GHOST' vs 'n1' sebagai dua masalah berbeda, sehingga loop terus
    berjalan padahal perbaikannya sia-sia.
    """
    ids = iter(["GHOST", "HANTU", "x9", "lenol", "noda"] * 12)

    def bad():
        tgt = next(ids)
        return json.dumps({"name": "x", "nodes": [
            {"id": "n1", "kind": "trigger", "label": "T", "config": {}}],
            "edges": [{"source": "n1", "target": tgt}]})

    r = af.run_self_correcting_loop(bad, lambda s, e: bad())
    assert r["ok"] is False
    assert r["reason"] == "no_progress", f"alasan stop: {r['reason']}"
    assert r["iterations"] == 3, f"harus berhenti di 3, bukan {r['iterations']}"
    assert r["no_progress_signature"], "harus ada jejak alasan stop"


def test_error_berbeda_terus_maju_sampai_batas():
    """Error yang BERUBAH = ada progres -> boleh jalan sampai max_iterations.

    Ini kebalikan dari test sebelumnya: membuktikan bahwa no-progress
    tidak membunuhkan semua loop lebih awal.
    """
    # Tiap iterasi memperbaiki error SEBELUMNYA tapi memunculkan error
    # BARU di node lain -> progres nyata, bukan siklus.
    idx = iter(range(1, 40))
    n = [0]

    def bad():
        n[0] += 1
        i = next(idx)
        return json.dumps({"name": "x", "nodes": [
            {"id": f"n{i}", "kind": "trigger", "label": f"A{i}", "config": {}},
            {"id": f"n{i}", "kind": "agent", "label": f"B{i}", "config": {}}],
            "edges": []})

    r = af.run_self_correcting_loop(bad, lambda s, e: bad())
    assert r["ok"] is False
    assert r["reason"] == "max_iterations", f"alasan stop: {r['reason']}"
    assert r["iterations"] == 10, f"harus tepat 10, bukan {r['iterations']}"
    assert n[0] == 10, f"10 iterasi = 1 generate + 9 repair, dapat {n[0]}"
    assert len(r["error_log"]) == 10
    # Bukti progres: 10 error itu berbeda satu sama lain.
    msgs = {" || ".join(b) for b in r["error_log"]}
    assert len(msgs) == 10, f"harusnya 10 error berbeda, ada {len(msgs)}"


def test_timeout_berhenti_dengan_alasan_jelas():
    t = [0.0]

    def clock():
        t[0] += 61.0
        return t[0]

    r = af.run_self_correcting_loop(lambda: bad_spec(),
                                    lambda s, e: bad_spec(), clock=clock)
    assert r["ok"] is False
    assert r["reason"] == "timeout"
    assert "120" in r["detail"]


def test_generator_exception_tidak_melempar_ke_pemanggil():
    """Error LLM/API diperlakukan sebagai data, bukan crash."""

    def boom():
        raise RuntimeError("429 rate limited")

    r = af.run_self_correcting_loop(boom, lambda s, e: spec(2))
    assert r["ok"] is False
    assert any("429" in e for e in r["errors"])


def test_generator_exception_no_progress_berhenti():
    def boom():
        raise RuntimeError("429 rate limited")

    r = af.run_self_correcting_loop(boom, lambda s, e: spec(2))
    assert r["reason"] == "no_progress"
    assert r["iterations"] == 3


def test_laporan_gagal_tidak_mengklaim_selesai():
    """#Anti-hallucination: laporan gagal TIDAK boleh berisi 'berhasil'."""
    r = af.run_self_correcting_loop(lambda: bad_spec(),
                                    lambda s, e: bad_spec())
    assert r["ok"] is False
    msg = r["message"].lower()
    assert "belum bisa diselesaikan" in msg
    assert "berhasil" not in msg
    assert "sukses" not in msg
    for word in ("berhasil", "sukses", "selesai", "done"):
        assert word not in msg.replace("belum bisa diselesaikan", "")


def test_laporan_gagal_memuat_error_yang_bertahan():
    r = af.run_self_correcting_loop(lambda: bad_spec(),
                                    lambda s, e: bad_spec())
    assert r["errors"], "harus menyebut error yang masih ada"
    assert all(isinstance(e, str) and e for e in r["errors"])


def test_progress_cb_terpanggil_dan_tidak_melempar():
    ev = []

    def cb(e):
        ev.append(e["event"])
        raise RuntimeError("UI callback boom")

    r = af.run_self_correcting_loop(lambda: spec(2), lambda s, e: spec(2),
                                    progress_cb=cb)
    assert r["ok"] is True
    assert "validated" in ev


def test_tanda_tangan_stabil_terhadap_kosmetik():
    q = chr(39)
    a = af.error_signature({"errors": ["edge target " + q + "GHOST" + q + " x"]})
    b = af.error_signature({"errors": ["EDGE TARGET " + q + "n1" + q + "  x"]})
    assert a == b
    c = af.error_signature({"errors": ["id node duplikat: n1"]})
    assert a != c


def test_tanda_tangan_kosong_bila_valid():
    assert af.error_signature({"ok": True, "errors": []}) == ""
