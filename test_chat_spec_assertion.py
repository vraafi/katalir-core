"""Regression guard: assertion status `/chat` di spec E2E tidak boleh vakum lagi.

Kelas bug yang dijaga (HANDOFF, temuan assertion vakum):

  if (chatStatus >= 500 && chatStatus !== 503) { ... }

Blok itu HANYA dievaluasi kalau request `/chat` benar-benar tertangkap.
`waitForResponse` dulu ber-timeout 25s sementara latensi produksi 20-30s,
sehingga `chatStatus` tetap `-1` -> blok tidak jalan -> spec HIJAU meski
`/chat` membalas 500. Kelas bug yang sama pernah meloloskan 500 ke produksi,
jadi assertion-nya dikunci di sini supaya tidak bisa diam-diam kembali vakum.

Tes ini murni membaca file spec (tanpa jaringan, tanpa browser).
"""

import io
import pathlib
import re

SPEC = pathlib.Path("nexus-frontend/tests/chat-auth.spec.ts")


def _spec() -> str:
    assert SPEC.exists(), "spec hilang: %s" % SPEC
    return io.open(SPEC, encoding="utf-8", newline="").read()


def _consts(src: str) -> dict:
    """Peta konstanta numerik di spec (mis. `CHAT_WAIT_MS = 45000`)."""
    return {
        name: int(value.replace("_", ""))
        for name, value in re.findall(
            r"const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([0-9_]+)\s*;", src
        )
    }


def _code_only(src: str) -> str:
    """Buang komentar. Guard menilai KODE, bukan dokumentasi bug lama -
    dulu regex ini menandai komentar yang MENGUTIP pola `if (chatStatus >= 5xx)`
    sebagai "guard vakum kembali" (false positive).
    """
    no_block = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(re.sub(r"//.*$", "", ln) for ln in no_block.splitlines())


def test_assertion_keras_status_chat_ada():
    """`/chat` harus di-assert eksplisit ke {200, 503}, bukan lewat guard."""
    src = _code_only(_spec())
    # Toleran format: blok boleh satu baris atau multi-baris (Prettier).
    pattern = r"expect\s*\(\s*\[\s*200\s*,\s*503\s*\]"
    assert re.search(pattern, src), (
        "assertion keras `expect([200, 503], ...).toContain(chatStatus)` hilang "
        "-> status /chat tidak lagi diverifikasi"
    )


def test_guard_vakum_tidak_kembali():
    """`if (chatStatus >= 5xx)` membuat assertion tidak dievaluasi saat timeout."""
    src = _code_only(_spec())
    match = re.search(r"if\s*\(\s*chatStatus\s*>=\s*5\d\d", src)
    assert match is None, (
        "guard vakum kembali (%s): assertion hanya jalan kalau request "
        "tertangkap, sehingga 500 bisa lolos hijau" % match.group(0)
    )


def test_timeout_wait_for_response_cukup_untuk_latensi_produksi():
    """Timeout harus >= 45s; 25s < latensi produksi 20-30s -> chatStatus=-1."""
    src = _code_only(_spec())
    consts = _consts(src)
    lines = src.splitlines()
    found = []
    for i, line in enumerate(lines):
        if "waitForResponse" not in line:
            continue
        for j in range(i, min(i + 8, len(lines))):
            hit = re.search(r"timeout:\s*([A-Za-z_][A-Za-z0-9_]*|[0-9_]+)", lines[j])
            if not hit:
                continue
            token = hit.group(1)
            if token.isdigit():
                value = int(token.replace("_", ""))
            elif token in consts:
                value = consts[token]
            else:
                raise AssertionError(
                    "timeout L%d memakai %r yang tidak bisa diresolusi; "
                    "guard tidak bisa menilai nilainya" % (j + 1, token)
                )
            found.append((j + 1, value))
            break
    assert found, "tidak menemukan waitForResponse bertimeout di spec"
    for line_no, value in found:
        assert value >= 45000, (
            "waitForResponse L%s timeout=%dms < 45000ms (latensi /chat produksi "
            "20-30s -> rawan timeout -> chatStatus=-1)" % (line_no, value)
        )


def test_status_dicatat_sebagai_bukti():
    """Output harus memuat `CHAT_STATUS=<code>` supaya bukti bisa digrep."""
    assert "CHAT_STATUS=${chatStatus}" in _code_only(_spec()), (
        "baris bukti `console.log(`CHAT_STATUS=${chatStatus}`)` hilang dari spec"
    )