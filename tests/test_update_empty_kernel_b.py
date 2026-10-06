# SPDX-License-Identifier: MIT
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "scripts/update-empty-kernel-b.sh"

class KernelBUpdate(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sys = self.root / "sys"
        self.dev = self.root / "dev"
        self.stage = self.root / "stage"
        self.bin = self.root / "bin"
        for path in (self.sys, self.dev, self.stage, self.bin):
            path.mkdir()
        self.write(self.root / "proc/mounts", "")
        attrs = {
            "class/mtd/mtd0/name": "factory-boot", "class/mtd/mtd0/size": "4194304",
            "class/mtd/mtd0/flags": "0", "class/mtd/mtd1/name": "linux-ubi",
            "class/mtd/mtd1/offset": "4194304", "class/mtd/mtd1/size": "531628032",
            "class/mtd/mtd1/writesize": "2048", "class/mtd/mtd1/erasesize": "131072",
            "class/mtd/mtd1/ecc_strength": "8", "class/mtd/mtd1/flags": "1024",
            "class/mtd/mtd2/name": "bbt-reserved", "class/mtd/mtd2/flags": "0",
            "block/mmcblk0/ro": "1", "class/ubi/ubi0/mtd_num": "1",
            "class/ubi/ubi0/ro_mode": "0", "class/ubi/ubi0/eraseblock_size": "126976"}
        for key, value in attrs.items():
            self.write(self.sys / key, value)
        for i, name in enumerate(("kernel_a", "kernel_b")):
            for key, value in {"name": name, "type": "static", "reserved_ebs": "132",
                               "corrupted": "0", "upd_marker": "0",
                               "data_bytes": "8192" if i == 0 else "0"}.items():
                self.attr(i, key, value)
        self.a = b"A" * 8192
        self.image = b"B" * 8192
        (self.dev / "ubi0_0").write_bytes(self.a)
        (self.dev / "ubi0_1").write_bytes(b"")
        self.image_path = self.stage / "kernel.img"
        self.image_path.write_bytes(self.image)
        text = SOURCE.read_text()
        for old, new in (("/sys/", str(self.sys) + "/"),
                         ("/dev/", str(self.dev) + "/"),
                         ("/proc/", str(self.root / "proc") + "/"),
                         ("/tmp/openh432-stage/", str(self.stage) + "/")):
            text = text.replace(old, new)
        self.script = self.root / "update.sh"
        self.script.write_text(text)
        self.mock("id", "echo 0")
        self.mock("sync", ":")
        self.mock("ubiupdatevol", 'echo written > "$FIXTURE/wrote"; cp "$2" "$1"; '
                  'stat -c %s "$2" > "$FIXTURE/sys/class/ubi/ubi0_1/data_bytes"')

    def write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n")

    def attr(self, vol, key, value):
        self.write(self.sys / ("class/ubi/ubi0_%d" % vol) / key, value)

    def mock(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/sh\nset -eu\n" + body + "\n")
        path.chmod(0o755)

    def run_update(self, digest=None):
        env = dict(os.environ, FIXTURE=str(self.root),
                   PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        return subprocess.run(["sh", str(self.script), str(self.image_path),
            digest or hashlib.sha256(self.image).hexdigest(),
            hashlib.sha256(self.a).hexdigest(), "--confirm-write-empty-kernel-b"],
            env=env, capture_output=True, text=True)

    def refused(self):
        self.assertNotEqual(self.run_update().returncode, 0)
        self.assertFalse((self.root / "wrote").exists())

    def test_success_and_a_preserved(self):
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.dev / "ubi0_0").read_bytes(), self.a)
        self.assertEqual((self.dev / "ubi0_1").read_bytes(), self.image)
        self.assertIn("PRESERVATION_PASS", result.stdout)

    def test_nonempty_b(self):
        self.attr(1, "data_bytes", "8192")
        self.refused()

    def test_wrong_volume(self):
        self.attr(1, "name", "recovery")
        self.refused()

    def test_interrupted_previous_update(self):
        self.attr(1, "upd_marker", "1")
        self.refused()

    def test_readonly_window(self):
        self.write(self.sys / "class/mtd/mtd1/flags", "0")
        self.refused()

    def test_kernel_a_changed(self):
        (self.dev / "ubi0_0").write_bytes(b"changed")
        self.refused()

    def test_bad_source_hash(self):
        result = self.run_update("0" * 64)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "wrote").exists())

    def test_bad_readback(self):
        self.mock("ubiupdatevol", 'echo written > "$FIXTURE/wrote"; '
                  'echo 8192 > "$FIXTURE/sys/class/ubi/ubi0_1/data_bytes"')
        self.assertNotEqual(self.run_update().returncode, 0)
        self.assertTrue((self.root / "wrote").exists())

if __name__ == "__main__":
    unittest.main()
