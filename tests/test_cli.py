# SPDX-License-Identifier: MIT
import os
from pathlib import Path
import subprocess
import unittest


class OfflineCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(["cargo", "build", "--locked", "--offline"], check=True)
        cls.binary = Path(os.environ["CARGO_TARGET_DIR"]) / "debug/openh432-usb"

    def run_cli(self, *args):
        return subprocess.run([str(self.binary), *args], capture_output=True, text=True)

    def test_help_without_usb(self):
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("--confirm-replace-ce", result.stdout)

    def test_default_is_help(self):
        self.assertEqual(self.run_cli().returncode, 0)

    def test_write_gate_without_usb(self):
        result = self.run_cli("flash-os", "missing.b000ff")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NAND write refused", result.stderr)

    def test_invalid_carrier_before_usb(self):
        result = self.run_cli("wait-flash-os", "/src/README.md", "1", "--confirm-replace-ce")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("carrier", result.stderr)
        self.assertNotIn("Waiting for", result.stdout)

    def test_strict_timeout_and_removed_commands(self):
        for args in [("wait-auth", "0"), ("list", "extra"), ("commit-staged", "file")]:
            self.assertNotEqual(self.run_cli(*args).returncode, 0)
