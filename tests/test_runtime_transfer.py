# SPDX-License-Identifier: MIT
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location(
    "runtime_transfer", Path(__file__).resolve().parents[1] /
    "scripts/push-runtime-file.py")
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


class RuntimeTransferTests(unittest.TestCase):
    def test_rejects_path_and_shell_names_before_source_read(self):
        source = Mock()
        for name in ("", "../a", "/tmp/a", "a;b", "a b", "-a", "a" * 65):
            with self.subTest(name=name), self.assertRaises(ValueError):
                tool.push(source, name, 1)
        source.read_bytes.assert_not_called()

    def test_sizes_and_token(self):
        for size in (0, -1, tool.MAX_SIZE + 1):
            with self.assertRaises(ValueError):
                tool.transfer_command("test.bin", size, "a" * 24)
        with self.assertRaises(ValueError):
            tool.transfer_command("test.bin", 1, "bad;token")

    def test_fixed_private_tmpfs_destination_and_no_overwrite(self):
        dest, command = tool.transfer_command("test.bin", 42, "a" * 24)
        self.assertEqual(dest, "/tmp/openh432-stage/test.bin")
        for guard in ("stat -f -c %T /tmp", "test ! -L", "set -C",
                      "chmod 700", "stat -c %u", "head -c 42",
                      "sha256sum", "stty", "_END=%s"):
            self.assertIn(guard, command)
        self.assertNotIn("timeout 300 head", command)
        self.assertNotIn("chmod +x", command)
        self.assertNotIn("/dev/mtd", command)

    def test_missing_identified_device_does_not_open_any_tty(self):
        source = Mock()
        source.read_bytes.return_value = b"test"
        with patch.object(tool.console, "find_console", return_value=None), \
                patch.object(tool.os, "open") as opened:
            with self.assertRaises(RuntimeError):
                tool.push(source, "test.bin", 1)
            opened.assert_not_called()
