# tests/test_ai_workflow_gen.py — Fitur #8 hard test (12 skenario, Okt 2026)
# Deterministik, tanpa model: `vision_fn` disuntik.
from __future__ import annotations

import time

import pytest

import ai_workflow_gen as gen


def _vision(steps, confidence=0.9, ambiguous=False, questions=None):
    def fn(media, filename, language):
        return {"steps": steps, "confidence": confidence,
                "ambiguous": ambiguous, "questions": questions or []}
    return fn


def _steps(*aksi):
    return [{"action": a, "target": f"target-{a}"} for a in aksi]


# 1. Upload screenshot UI -> generate workflow
def test_01_screenshot():
    out = gen.generate(b"PNGDATA", "screen.png",
                       _vision(_steps("open", "click", "submit")))
    wf = out["workflow"]
    assert wf is not None
    assert wf["nodes"][0]["kind"] == "trigger"
    assert len(wf["nodes"]) == 4            # trigger + 3 langkah
    assert out["media"]["kind"] == "image"


# 2. Upload video demo -> generate workflow
def test_02_video():
    out = gen.generate(b"MP4DATA", "demo.mp4",
                       _vision(_steps("open", "type", "download")))
    assert out["media"]["kind"] == "video"
    assert len(out["workflow"]["nodes"]) == 4


# 3. Multi-step (5 langkah)
def test_03_multistep():
    out = gen.generate(b"x", "a.png",
                       _vision(_steps("open", "type", "click", "api", "download")))
    wf = out["workflow"]
    assert len(wf["nodes"]) == 6            # trigger + 5
    # rantai edge berurutan
    assert len(wf["edges"]) == 5
    assert wf["edges"][0]["source"] == "trigger"


# 4. Kondisi IF/ELSE
def test_04_condition():
    steps = [{"action": "check", "target": "saldo",
              "condition": "saldo > 100"},
             {"action": "api", "target": "transfer"}]
    out = gen.generate(b"x", "a.png", _vision(steps))
    wf = out["workflow"]
    cabang = [e for e in wf["edges"] if e.get("branch")]
    assert {e["branch"] for e in cabang} == {"true", "false"}
    node = [n for n in wf["nodes"] if n["id"] == "step_1"][0]
    assert node["config"]["condition"] == "saldo > 100"


# 5. Error handling (on_error)
def test_05_error_handling():
    steps = [{"action": "api", "target": "kirim", "on_error": "retry"}]
    out = gen.generate(b"x", "a.png", _vision(steps))
    node = [n for n in out["workflow"]["nodes"] if n["id"] == "step_1"][0]
    assert node["on_error"] == "retry"
    assert node["config"]["on_error"] == "retry"


# 6. Bahasa ID + EN
def test_06_language():
    out_id = gen.generate(b"x", "a.png", _vision(_steps("open")), language="id")
    out_en = gen.generate(b"x", "a.png", _vision(_steps("open")), language="en")
    assert out_id["workflow"]["nodes"][0]["label"] == "Mulai"
    assert out_en["workflow"]["nodes"][0]["label"] == "Start"
    assert "Langkah 1" in out_id["workflow"]["nodes"][1]["label"]
    assert "Step 1" in out_en["workflow"]["nodes"][1]["label"]


# 7. Complex workflow 10+ node
def test_07_complex_10_nodes():
    aksi = ["open", "type", "click", "api", "check", "ai", "approve",
            "search", "download", "submit"]
    out = gen.generate(b"x", "a.png", _vision(_steps(*aksi)))
    wf = out["workflow"]
    assert len(wf["nodes"]) == 11           # trigger + 10
    kinds = {n["kind"] for n in wf["nodes"]}
    assert {"trigger", "agent", "wait_for_human", "vector_store"} <= kinds


# 8. Ambiguous input -> tanya klarifikasi
def test_08_ambiguous():
    out = gen.generate(b"x", "a.png",
                       _vision(_steps("open"), confidence=0.2, ambiguous=True))
    assert out["needs_clarification"] is True
    assert out["questions"]
    assert any("langkah pertama" in q.lower() for q in out["questions"])


def test_08b_low_confidence_warning():
    out = gen.generate(b"x", "a.png", _vision(_steps("open"), confidence=0.3))
    assert out["warnings"]
    assert out["needs_clarification"] is True


# 9. Invalid file -> error graceful
def test_09_invalid_file():
    with pytest.raises(gen.MediaError):
        gen.generate(b"x", "malware.exe", _vision(_steps("open")))
    with pytest.raises(gen.MediaError):
        gen.generate(b"x", "doc.pdf", _vision(_steps("open")))
    with pytest.raises(gen.MediaError):
        gen.generate(b"", "empty.png", _vision(_steps("open")))
    # model gagal -> GenerationError, bukan crash
    def boom(media, filename, language):
        raise RuntimeError("model down")
    with pytest.raises(gen.GenerationError):
        gen.generate(b"x", "a.png", boom)


# 10. Performa < 30s per video
def test_10_performance():
    def lambat(media, filename, language):
        time.sleep(0.05)
        return {"steps": _steps(*(["open"] * 20)), "confidence": 0.95}
    t0 = time.perf_counter()
    out = gen.generate(b"x", "demo.mp4", lambat)
    dt = time.perf_counter() - t0
    assert dt < 30
    assert out["analysis"]["duration_s"] < 30
    assert len(out["workflow"]["nodes"]) == 21


# 11. Batas ukuran 100MB
def test_11_size_limit():
    ok = gen.MAX_MEDIA_BYTES
    meta = gen.validate_media("a.png", ok)
    assert meta["size_bytes"] == ok
    with pytest.raises(gen.MediaError):
        gen.validate_media("a.png", ok + 1)


# 12. Keamanan: validasi unggahan
def test_12_upload_security():
    # ekstensi palsu berbahaya
    for bad in ("a.php", "a.svg", "a.html", "a.js", "a.exe", "a.sh"):
        with pytest.raises(gen.MediaError):
            gen.validate_media(bad, 100)
    # MIME tidak diizinkan
    with pytest.raises(gen.MediaError):
        gen.validate_media("a.png", 100, mime="application/x-msdownload")
    # path traversal -> disanitasi ke basename
    meta = gen.validate_media("../../etc/passwd.png", 100)
    assert "/" not in meta["filename"] and ".." not in meta["filename"]
