# SPDX-License-Identifier: MIT
import hashlib
import os
from pathlib import Path
import subprocess
import test_update_empty_kernel_b as kernel
import test_update_empty_systembase_b as base

class MatchingMixin:
    # Matching updates run from a booted system and do not check the internal SD.
    test_writable_internal_sd_refused_despite_readonly_card = None
    test_missing_internal_sd_refused = None

    def setUp(self):
        source = self.module.SOURCE
        self.module.SOURCE = source.with_name(source.name.replace("empty", "matching"))
        try:
            super().setUp()
        finally:
            self.module.SOURCE = source
        self.previous = b"C" * 8192
        (self.dev / self.node).write_bytes(self.previous)
        self.attr(self.vol, "data_bytes", "8192")

    def run_update(self, digest=None):
        env = dict(os.environ, FIXTURE=str(self.root),
                   PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        return subprocess.run(["sh", str(self.script), str(self.image_path),
            digest or hashlib.sha256(self.image).hexdigest(),
            hashlib.sha256(self.a).hexdigest(), hashlib.sha256(self.previous).hexdigest(),
            "--confirm-replace-matching-" + self.kind + "-b"],
            env=env, capture_output=True, text=True)

    def test_nonempty_b(self):
        (self.dev / self.node).write_bytes(b"unexpected previous image")
        self.refused()

    def test_unrelated_mounted_root_and_writable_sd_allowed(self):
        other = "ubi0_4" if self.vol == 1 else "ubi0_3"
        self.write(self.root / "proc/mounts", "/dev/ubiblock" + other[3:] + " /lower squashfs ro 0 0")
        self.write(self.internal / "ro", "0")
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_target_mount_refused(self):
        self.write(self.root / "proc/mounts", "/dev/ubiblock0_" + str(self.vol) + " /lower squashfs ro 0 0")
        self.refused()

    def test_target_named_mount_refused(self):
        self.write(self.root / "proc/mounts", "ubi0:" + self.kind + "_b /lower ubifs ro 0 0")
        self.refused()

    def test_target_block_mapping_refused(self):
        (self.sys / ("class/block/ubiblock0_" + str(self.vol))).mkdir(parents=True)
        self.refused()

    def test_empty_b_refused(self):
        self.attr(self.vol, "data_bytes", "0")
        self.refused()

class MatchingKernelB(MatchingMixin, kernel.KernelBUpdate):
    module = kernel
    node = "ubi0_1"
    vol = 1
    kind = "kernel"

class MatchingSystembaseB(MatchingMixin, base.SystembaseBUpdate):
    module = base
    node = "ubi0_4"
    vol = 4
    kind = "systembase"
