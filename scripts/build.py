#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build/test host tools in a pinned container. Never access USB."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]


def docker():
    if os.environ.get("BSP_DOCKER"):
        return shlex.split(os.environ["BSP_DOCKER"])
    if os.access("/var/run/docker.sock", os.R_OK | os.W_OK):
        return ["docker"]
    for helper in ("doas", "sudo"):
        if shutil.which(helper):
            return [helper, "docker"]
    return ["docker"]


def run(command, **kwargs):
    print("+", shlex.join(map(str, command)), flush=True)
    return subprocess.run(command, check=True, **kwargs)


def lock():
    data = json.loads((ROOT / "container/lock.json").read_text())
    if not re.fullmatch(r".+@sha256:[0-9a-f]{64}", data["base_image"]):
        raise ValueError("builder must be digest-pinned")
    if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z", data["debian_snapshot"]):
        raise ValueError("immutable package snapshot required")
    return data


def image():
    data = lock()
    recipe = hashlib.sha256((ROOT / "container/Dockerfile").read_bytes()
                            + (ROOT / "container/lock.json").read_bytes()).hexdigest()
    tag = "openh432-tools:" + recipe[:16]
    result = subprocess.run(docker() + ["image", "inspect", tag],
                            capture_output=True, text=True)
    if result.returncode:
        run(docker() + ["build", "--platform", data["platform"],
            "--build-arg", "BASE_IMAGE=" + data["base_image"],
            "--build-arg", "DEBIAN_SNAPSHOT=" + data["debian_snapshot"],
            "--build-arg", "RUST_VERSION=" + data["rust_version"],
            "--build-arg", "LIBUSB_VERSION=" + data["libusb_version"],
            "--label", "org.openh432.tools.recipe=" + recipe,
            "-t", tag, str(ROOT / "container")])
        result = run(docker() + ["image", "inspect", tag],
                     capture_output=True, text=True)
    info = json.loads(result.stdout)[0]
    if info["Config"].get("Labels", {}).get("org.openh432.tools.recipe") != recipe:
        raise RuntimeError("builder label mismatch")
    return info["Id"]


def container_args(image_id, out):
    data = lock()
    return docker() + ["run", "--rm", "--platform", data["platform"],
        "--network=none", "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--user", "1000:1000", "--hostname", "openh432-tools-builder",
        "--mount", "type=bind,src=" + str(ROOT) + ",dst=/src,readonly",
        "--mount", "type=bind,src=" + str(out) + ",dst=/out",
        "--workdir", "/src", "--env", "HOME=/out/home",
        "--env", "CARGO_HOME=/out/cargo", "--env", "CARGO_TARGET_DIR=/out/target",
        "--env", "SOURCE_DATE_EPOCH=" + str(data["source_date_epoch"]),
        "--env", "PYTHONDONTWRITEBYTECODE=1",
        "--env", "RUSTFLAGS=--remap-path-prefix=/src=openh432-tools",
        image_id]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("image", "test", "build"))
    parser.add_argument("--out", type=Path, default=ROOT / "out")
    args = parser.parse_args()
    image_id = image()
    if args.action == "image":
        print(image_id)
        return
    out = args.out.resolve()
    if out == ROOT or out in ROOT.parents:
        parser.error("output cannot be the checkout or an ancestor")
    out.mkdir(parents=True, exist_ok=True)
    if args.action == "test":
        command = ["sh", "-ec", "cargo test --locked --offline; python3 -m unittest discover -s tests -v; python3 -O -m unittest discover -s tests -p test_tools.py"]
    else:
        command = ["cargo", "build", "--release", "--locked", "--offline"]
    run(container_args(image_id, out) + command)
    names = subprocess.check_output(
        ["git", "-C", str(ROOT), "ls-files", "-c", "-o", "--exclude-standard", "-z"]
    ).decode().split("\0")
    inputs = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
              for name in sorted(set(names)) if name and (ROOT / name).is_file()}
    record = out / (args.action + "-" + uuid.uuid4().hex + ".json")
    record.write_text(json.dumps({"container": image_id, "lock": lock(),
                                 "inputs": inputs, "hardware_tested": False},
                                indent=2) + "\n")


if __name__ == "__main__":
    main()
