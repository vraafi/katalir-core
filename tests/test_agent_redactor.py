"""Test redaktor fail-closed (`agent_redactor`).

Mengunci tiga janji:
  1. 10 pola kredensial benar-benar di-redact.
  2. Canary MELEMPAR (fail-closed), bukan sekadar di-mask.
  3. Redaksi rekursif + tahan tipe aneh, dan tidak pernah lebih longgar
     daripada redaktor log `database.redact_sensitive`.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import agent_redactor as ar  # noqa: E402


#: (nama, nilai mentah, penanda yang harus muncul)
SAMPLES = [
    ("telegram_bot", "1234567890:" + "A" * 35, "[TELEGRAM_BOT_REDACTED]"),
    ("google_api", "AIza" + "B" * 35, "[GOOGLE_API_REDACTED]"),
    ("slack", "xoxb-" + "C" * 12, "[SLACK_REDACTED]"),
    ("github", "ghp_" + "D" * 36, "[GITHUB_REDACTED]"),
    ("jwt", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0." + "E" * 24, "[JWT_REDACTED]"),
    ("bearer", "Bearer " + "F" * 24, "Bearer [REDACTED]"),
    ("openai", "sk-" + "G" * 24, "[OPENAI_KEY_REDACTED]"),
    ("google_oauth", "ya29." + "H" * 24, "[GOOGLE_OAUTH_REDACTED]"),
    ("aws", "AKIA" + "I" * 16, "[AWS_KEY_REDACTED]"),
    ("url_api_key", "https://x.test/a?api_key=SECRETVALUE&z=1",
     "api_key=[REDACTED]"),
]


class TestSepuluhPola(unittest.TestCase):
    def setUp(self):
        ar.reset_stats()

    def test_setiap_pola_diredact(self):
        for name, raw, marker in SAMPLES:
            with self.subTest(pattern=name):
                out = ar.redact(raw)
                self.assertNotIn(raw, out, f"{name}: nilai mentah masih ada")
                self.assertIn(marker, out, f"{name}: penanda tidak muncul")

    def test_ada_sepuluh_pola_kredensial(self):
        credential_rules = [c for c, _rx, _r in ar.CREDENTIAL_PATTERNS
                            if c != "canary"]
        self.assertGreaterEqual(len(credential_rules), 10)

    def test_pemisah_url_dipertahankan(self):
        """Brief menulis pengganti `?\\1=` yang merusak `&` -> `?`.

        Nilai yang benar mempertahankan pemisah aslinya.
        """
        out = ar.redact("https://x.test/a?api_key=AAA&token=BBB&z=1")
        self.assertIn("?api_key=[REDACTED]", out)
        self.assertIn("&token=[REDACTED]", out)
        self.assertIn("&z=1", out)
        self.assertNotIn("?token=", out, "pemisah `&` berubah jadi `?` (bug brief)")

    def test_statistik_tercatat_tanpa_nilai(self):
        ar.redact("ghp_" + "D" * 36)
        stats = ar.get_stats()
        self.assertEqual(stats.get("github"), 1)
        blob = repr(stats)
        self.assertNotIn("D" * 36, blob)
        self.assertNotIn("ghp_", blob)


class TestCanary(unittest.TestCase):
    def setUp(self):
        ar.reset_stats()

    def test_canary_melempar(self):
        canary = ar.CANARY_PREFIX + "ABCDEF012345"
        with self.assertRaises(ar.CanaryDetectedError):
            ar.redact(f"log: {canary}")

    def test_canary_terpotong_pun_tertangkap(self):
        """Pencarian longgar: cukup prefiks."""
        with self.assertRaises(ar.CanaryDetectedError):
            ar.redact(ar.CANARY_PREFIX + "X")

    def test_canary_bisa_dimask_bila_diminta(self):
        canary = ar.CANARY_PREFIX + "ABCDEF012345"
        out = ar.redact(f"log: {canary}", raise_on_canary=False)
        self.assertNotIn(canary, out)
        self.assertIn("[CANARY_DETECTED_ALERT]", out)

    def test_canary_melempar_di_dalam_struktur(self):
        canary = ar.CANARY_PREFIX + "ABCDEF012345"
        with self.assertRaises(ar.CanaryDetectedError):
            ar.redact_agent_output({"a": {"b": [canary]}})

    def test_canary_dihitung_di_statistik(self):
        with self.assertRaises(ar.CanaryDetectedError):
            ar.redact(ar.CANARY_PREFIX + "ABCDEF012345")
        self.assertEqual(ar.get_stats().get("canary_alerts"), 1)

    def test_scan_canary_tidak_melempar(self):
        self.assertTrue(ar.scan_canary(ar.CANARY_PREFIX + "ABCDEF012345"))
        self.assertFalse(ar.scan_canary("teks biasa"))


class TestRekursif(unittest.TestCase):
    def test_dict_bersarang(self):
        payload = {"outer": {"inner": {"tok": "ghp_" + "D" * 36}}}
        out = ar.redact_agent_output(payload)
        self.assertEqual(out["outer"]["inner"]["tok"], "[GITHUB_REDACTED]")

    def test_array_tiap_item(self):
        payload = {"items": ["ghp_" + "D" * 36, "AIza" + "B" * 35, 7]}
        out = ar.redact_agent_output(payload)
        self.assertEqual(out["items"][0], "[GITHUB_REDACTED]")
        self.assertEqual(out["items"][1], "[GOOGLE_API_REDACTED]")
        self.assertEqual(out["items"][2], 7)

    def test_kunci_sensitif_diganti_utuh(self):
        out = ar.redact_agent_output({"Authorization": "apapun-nilainya"})
        self.assertEqual(out["Authorization"], ar.REDACTED)

    def test_tuple_dan_none_dan_bool(self):
        out = ar.redact_agent_output({"t": ("AIza" + "B" * 35,), "n": None,
                                      "b": True})
        self.assertEqual(out["t"][0], "[GOOGLE_API_REDACTED]")
        self.assertIsNone(out["n"])
        self.assertIs(out["b"], True)

    def test_bytes_didekode_lalu_diredact(self):
        out = ar.redact(("ghp_" + "D" * 36).encode())
        self.assertEqual(out, "[GITHUB_REDACTED]")

    def test_batas_kedalaman(self):
        node: dict = {}
        cur = node
        for _ in range(ar.MAX_DEPTH + 3):
            cur["x"] = {}
            cur = cur["x"]
        cur["tok"] = "ghp_" + "D" * 36
        out = ar.redact_agent_output(node)
        blob = str(out)
        self.assertIn("[REDACTED_DEPTH]", blob)
        self.assertNotIn("D" * 36, blob)

    def test_fail_closed_objek_tak_bisa_di_str(self):
        class Jahat:
            def __str__(self):
                raise ValueError("tidak bisa dikonversi")

        with self.assertRaises(ar.RedactionError):
            ar.redact(Jahat())


class TestParityDenganDatabase(unittest.TestCase):
    """Redaktor umum TIDAK BOLEH lebih longgar dari redaktor log produksi."""

    def test_sensitive_keys_superset(self):
        import database

        missing = set(database._SENSITIVE_KEYS) - set(ar.SENSITIVE_KEYS)
        self.assertFalse(
            missing,
            f"kunci sensitif di database tidak ada di agent_redactor: {missing}")

    def test_pola_bersama_sama_sama_diredact(self):
        import database

        shared = [
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0." + "E" * 24,
            "Bearer " + "F" * 24,
            "sk-" + "G" * 24,
            "xoxb-" + "C" * 12,
            "AKIA" + "I" * 16,
            "ghp_" + "D" * 36,
            "1234567890:" + "A" * 35,
            "ya29." + "H" * 24,
        ]
        for raw in shared:
            with self.subTest(sample=raw[:12]):
                self.assertNotIn(raw, ar.redact(raw), "agent_redactor bocor")
                self.assertNotIn(raw, database.redact_sensitive(raw),
                                 "database bocor")


if __name__ == "__main__":
    unittest.main(verbosity=2)
