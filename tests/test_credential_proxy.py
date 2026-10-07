"""Test proxy kredensial (placeholder `${auth.X}` + canary + penjaga bocor)."""
from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import agent_redactor as ar  # noqa: E402
import credential_proxy as cp  # noqa: E402


class TestPlaceholder(unittest.TestCase):
    def setUp(self):
        cp.clear_store()

    def test_placeholder_terdeteksi(self):
        self.assertTrue(cp.has_placeholder("x=${auth.telegram_bot}"))
        self.assertFalse(cp.has_placeholder("x=literal"))
        self.assertFalse(cp.has_placeholder("${auth.}"))

    def test_nama_placeholder(self):
        text = "${auth.a} dan ${auth.b} dan ${auth.a}"
        self.assertEqual(cp.placeholder_names(text), ["a", "b"])

    def test_resolve_mengganti_nilai(self):
        cp.put_test_credential("telegram_bot", "TOKEN-ABC", canary=False)
        self.assertEqual(cp.resolve_placeholder("Bearer ${auth.telegram_bot}"),
                         "Bearer TOKEN-ABC")

    def test_resolve_tanpa_kunci_melempar(self):
        with self.assertRaises(cp.CredentialMissingError):
            cp.resolve_placeholder("${auth.tidak_ada}")

    def test_placeholder_tidak_diresolv_tanpa_permintaan(self):
        """Teks biasa dengan placeholder tetap utuh (tidak bocor nilai)."""
        cp.put_test_credential("sheets_id", "SHEET-XYZ", canary=False)
        text = "id=${auth.sheets_id}"
        self.assertEqual(text, "id=${auth.sheets_id}")
        self.assertEqual(cp.resolve_placeholder(text), "id=SHEET-XYZ")

    def test_resolve_cfg_rekursif(self):
        cp.put_test_credential("telegram_chat", "CHAT-1", canary=False)
        cfg = {"a": "${auth.telegram_chat}",
               "b": {"c": ["x", "${auth.telegram_chat}"]},
               "d": 5}
        out = cp.resolve_cfg_for_egress(cfg)
        self.assertEqual(out["a"], "CHAT-1")
        self.assertEqual(out["b"]["c"][1], "CHAT-1")
        self.assertEqual(out["d"], 5)
        # config asli TIDAK boleh termutasi
        self.assertEqual(cfg["a"], "${auth.telegram_chat}")


class TestTestOnlyGuard(unittest.TestCase):
    def test_tolak_nama_non_test(self):
        for bad in ("TELEGRAM_BOT_TOKEN", "GEMINI_API_KEY", "SUPABASE_KEY",
                    "VPS_PASSWORD", "path/aneh"):
            with self.subTest(name=bad):
                with self.assertRaises(cp.ProductionCredentialRefused):
                    cp.assert_test_only(bad)

    def test_terima_nama_test(self):
        self.assertEqual(cp.assert_test_only("TEST_TELEGRAM_BOT_TOKEN"),
                         "TEST_TELEGRAM_BOT_TOKEN")

    def test_env_map_hanya_test(self):
        for env_name in cp.TEST_ENV_MAP.values():
            self.assertTrue(env_name.startswith("TEST_"),
                            f"{env_name} bukan variabel test")

    def test_load_melaporkan_status_tanpa_nilai(self):
        # Lingkungan ini memang TIDAK punya kredensial test.
        status = cp.load_test_credentials()
        self.assertEqual(set(status), set(cp.TEST_ENV_MAP))
        for value in status.values():
            self.assertIn(value, ("SET", "MISSING"))
        self.assertEqual(cp.store_keys(), [],
                         "tidak boleh ada kredensial test di lingkungan ini")

    def test_load_strict_melempar_bila_kosong(self):
        with self.assertRaises(cp.CredentialMissingError):
            cp.load_test_credentials(strict=True)


class TestCanary(unittest.TestCase):
    def setUp(self):
        cp.clear_store()

    def test_format_canary(self):
        canary = cp.generate_canary()
        self.assertTrue(re.fullmatch(ar.CANARY_PATTERN_SRC, canary),
                        f"format canary salah: {canary}")

    def test_canary_unik(self):
        seen = {cp.generate_canary() for _ in range(50)}
        self.assertEqual(len(seen), 50)

    def test_register_dan_ambil(self):
        cp.put_test_credential("github_token", "ghp_X", canary=True)
        canary = cp.get_canary("github_token")
        self.assertTrue(canary.startswith(ar.CANARY_PREFIX))
        self.assertEqual(cp.all_canaries()["github_token"], canary)


class TestPenjagaBocor(unittest.TestCase):
    def setUp(self):
        cp.clear_store()

    def test_leaking_keys_menemukan_nilai(self):
        cp.put_test_credential("sheets_id", "SHEET-ABC", canary=False)
        self.assertEqual(cp.leaking_keys("id=SHEET-ABC"), ["sheets_id"])
        self.assertEqual(cp.leaking_keys("bersih"), [])

    def test_assert_no_leak_melempar(self):
        cp.put_test_credential("sheets_id", "SHEET-ABC", canary=False)
        with self.assertRaises(cp.ProductionCredentialRefused):
            cp.assert_no_leak({"out": "SHEET-ABC"})
        cp.assert_no_leak({"out": "aman"})   # tidak melempar

    def test_mask_known_values_rekursif(self):
        cp.put_test_credential("telegram_chat", "CHAT-9", canary=False)
        out = cp.mask_known_values({"a": "x CHAT-9 y",
                                    "b": ["CHAT-9", {"c": "CHAT-9"}]})
        self.assertNotIn("CHAT-9", str(out))
        self.assertEqual(out["a"], f"x {cp.MASK} y")
        self.assertEqual(out["b"][1]["c"], cp.MASK)


if __name__ == "__main__":
    unittest.main(verbosity=2)
