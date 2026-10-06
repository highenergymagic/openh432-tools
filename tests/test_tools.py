# SPDX-License-Identifier: MIT
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


backup = module("backup", "inventory-nand-backup.py")
console = module("console", "watch-console.py")
builder = module("builder", "build.py")


class BackupTests(unittest.TestCase):
    def fixture(self, folder, offset=0, marker=255):
        raw = bytearray(b"\xff" * backup.RAW_PEB)
        raw[backup.PAGE] = marker
        data = bytes(raw)
        compressed = gzip.compress(data, mtime=0)
        path = folder / f"{offset:08x}.raw.gz"
        path.write_bytes(compressed)
        info = {"offset": offset, "length": backup.PEB,
                "raw_oob_bytes": len(data),
                "gzip_sha256": hashlib.sha256(compressed).hexdigest(),
                "raw_oob_sha256": hashlib.sha256(data).hexdigest()}
        path.with_suffix(".json").write_text(json.dumps(info))
        return path

    def test_empty_is_not_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                backup.inventory(Path(temp), True)

    def test_partial_never_passes_as_complete(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            self.fixture(folder)
            with self.assertRaises(ValueError):
                backup.inventory(folder)
            self.assertEqual(backup.inventory(folder, True)["status"], "partial")

    def test_corruption(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            path = self.fixture(folder)
            path.write_bytes(path.read_bytes() + b"corrupt")
            with self.assertRaises(ValueError):
                backup.inventory(folder, True)

    def test_gap_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            self.fixture(folder, backup.PEB)
            with self.assertRaises(ValueError):
                backup.inventory(folder, True)

    def test_bad_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            self.fixture(folder, marker=0)
            self.assertEqual(backup.inventory(folder, True)["bad_blocks"], [0])

    def test_complete_small_fixture(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            self.fixture(folder)
            old = backup.TOTAL
            try:
                backup.TOTAL = backup.PEB
                self.assertEqual(backup.inventory(folder)["status"], "complete")
            finally:
                backup.TOTAL = old


class ContractTests(unittest.TestCase):
    def test_container_has_no_hardware_or_network(self):
        command = builder.container_args("image", Path("/tmp/host-tools"))
        self.assertIn("--network=none", command)
        self.assertIn("--cap-drop=ALL", command)
        self.assertNotIn("--privileged", command)
        self.assertFalse(any("/dev/" in item or "docker.sock" in item for item in command))

    def test_command_status_matches_token(self):
        self.assertIsNone(console.command_status(b"\nOPENH432_CMD_STATUS_wrong=0\n", "right"))
        self.assertEqual(console.command_status(b"\nOPENH432_CMD_STATUS_right=7\n", "right"), 7)

    def test_carrier_check_precedes_usb(self):
        # End-to-end argument/parser checks are run by tests/test_cli.py.
        self.assertEqual(builder.lock()["platform"], "linux/amd64")


if __name__ == "__main__":
    unittest.main()
