# SPDX-License-Identifier: MIT
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "scripts/install-verity-slot.sh"


class InstallVeritySlot(unittest.TestCase):
    def fixture(self, root, slot):
        def write(name, data):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(data + "\n")
        for directory in ("bin", "dev", "run"):
            (root / directory).mkdir()
        write("proc/cmdline", "rauc.slot=" + ("B" if slot == "A" else "A"))
        attrs = {"class/ubi/ubi0/mtd_num": "1", "class/mtd/mtd1/name": "linux-ubi",
                 "class/mtd/mtd1/offset": "4194304", "class/mtd/mtd1/size": "531628032",
                 "class/ubi/ubi0/eraseblock_size": "126976"}
        for number, name in ((0, "kernel_a"), (1, "kernel_b"), (3, "systembase_a"), (4, "systembase_b")):
            for key, value in {"name": name, "type": "static", "reserved_ebs": "1651",
                               "upd_marker": "0", "corrupted": "0"}.items():
                attrs[f"class/ubi/ubi0_{number}/{key}"] = value
            (root / f"dev/ubi0_{number}").write_bytes(b"preserve")
        for key, value in attrs.items():
            write("sys/" + key, value)
        commands = {
            "id": "echo 0",
            "sync": ":",
            "fw_printenv": "echo 3",
            "fw_setenv": 'echo "env $*" >> "$FIXTURE/log"',
            "ubirmvol": 'echo "remove $*" >> "$FIXTURE/log"',
            "ubimkvol": 'echo "create $*" >> "$FIXTURE/log"',
            "ubiupdatevol": 'echo "write $1" >> "$FIXTURE/log"; '
                            'case "$1:$FAIL" in *ubi0_3:write|*ubi0_4:write) exit 1;; esac; '
                            'cp "$2" "$1"; case "$1:$FAIL" in *ubi0_3:readback|*ubi0_4:readback) echo bad > "$1";; esac',
        }
        for command, body in commands.items():
            path = root / "bin" / command
            path.write_text("#!/bin/sh\n" + body + "\n")
            path.chmod(0o755)
        text = SOURCE.read_text()
        for prefix in ("sys", "dev", "proc", "run"):
            text = text.replace(f"/{prefix}/", str(root / prefix) + "/")
        (root / "install.sh").write_text(text)
        (root / "kernel").write_bytes(b"k" * 4096)
        (root / "image").write_bytes(b"r" * 12288)

    def run_install(self, root, slot, failure="", bad_hash=False):
        digest = lambda name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        return subprocess.run(["sh", str(root / "install.sh"), slot,
                               str(root / "kernel"), str(root / "image"),
                               "0" * 64 if bad_hash else digest("kernel"), digest("image"),
                               "--confirm-replace-inactive-slot"], capture_output=True,
                              env=dict(os.environ, PATH=str(root / "bin") + ":" + os.environ["PATH"],
                                       FIXTURE=str(root), FAIL=failure))

    def test_both_slots_and_write_order(self):
        for slot, kid, rid, other in (("A", 0, 3, 4), ("B", 1, 4, 3)):
            with self.subTest(slot=slot), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.fixture(root, slot)
                result = self.run_install(root, slot)
                self.assertEqual(result.returncode, 0, result.stderr)
                log = (root / "log").read_text()
                self.assertLess(log.index(f"env BOOT_{slot}_LEFT 0"), log.index("write "))
                self.assertLess(log.index("remove "), log.index("create "))
                self.assertIn("--skipcheck", log)
                self.assertGreater(log.index(f"env BOOT_{slot}_LEFT 3"), log.index("create "))
                self.assertEqual((root / f"dev/ubi0_{rid}").read_bytes(), (root / "image").read_bytes())
                self.assertEqual((root / f"dev/ubi0_{other}").read_bytes(), b"preserve")
                self.assertFalse((root / "run/openh432-slot-update.lock").exists())

    def test_failed_write_or_readback_never_reactivates(self):
        for failure in ("write", "readback"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.fixture(root, "A")
                self.assertNotEqual(self.run_install(root, "A", failure).returncode, 0)
                log = (root / "log").read_text()
                self.assertIn("env BOOT_A_LEFT 0", log)
                self.assertNotIn("env BOOT_A_LEFT 3", log)
                self.assertNotIn("env BOOT_ORDER", log)

    def test_active_slot_or_wrong_hash_rejected_before_writes(self):
        for active in (True, False):
            with self.subTest(active=active), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.fixture(root, "A")
                if active:
                    (root / "proc/cmdline").write_text("rauc.slot=A\n")
                self.assertNotEqual(self.run_install(root, "A", bad_hash=not active).returncode, 0)
                self.assertFalse((root / "log").exists())
