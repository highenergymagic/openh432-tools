#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Verify raw+OOB backup completeness and checksums offline; never restore NAND."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

PEB = 131072
PAGE = 2048
OOB = 64
RAW_PEB = 64 * (PAGE + OOB)
TOTAL = 512 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def inventory(directory, partial=False):
    blocks = []
    expected = 0
    manifests = sorted(directory.glob("*.raw.json"))
    require(bool(manifests), "no backup manifests found")
    for manifest in manifests:
        info = json.loads(manifest.read_text())
        offset, length = info["offset"], info["length"]
        require(type(offset) is int and type(length) is int, "integer ranges required")
        require(offset == expected and 0 < length <= 16 << 20
                and length % PEB == 0 and offset + length <= TOTAL,
                f"gap, overlap or unsupported backup range: {manifest.name}")
        require(manifest.name == f"{offset:08x}.raw.json", "filename/range mismatch")
        raw_size = length // PAGE * (PAGE + OOB)
        require(info["raw_oob_bytes"] == raw_size, "wrong declared raw+OOB size")
        archive = manifest.with_suffix(".gz")
        require(archive.stat().st_size <= raw_size + (1 << 20), "oversized archive")
        compressed = archive.read_bytes()
        require(hashlib.sha256(compressed).hexdigest() == info["gzip_sha256"],
                f"compressed SHA256 mismatch: {manifest.name}")
        with gzip.open(archive, "rb") as stream:
            raw = stream.read(raw_size + 1)
        require(len(raw) == raw_size, "raw+OOB length mismatch")
        require(hashlib.sha256(raw).hexdigest() == info["raw_oob_sha256"],
                "raw+OOB SHA256 mismatch")
        for local in range(0, len(raw), RAW_PEB):
            block = raw[local:local + RAW_PEB]
            main = b"".join(block[p:p+PAGE] for p in range(0, len(block), PAGE+OOB))
            oob = b"".join(block[p+PAGE:p+PAGE+OOB] for p in range(0, len(block), PAGE+OOB))
            index = expected // PEB + local // RAW_PEB
            # On this qualified Samsung SLC geometry, byte zero of first/second
            # page OOB is the marker. CE's byte-one flags are not bad markers.
            markers = [oob[0], oob[OOB]]
            blocks.append({"block": index, "offset": index * PEB,
                "markers": markers, "bad": any(v != 255 for v in markers),
                "all_erased": block == b"\xff" * RAW_PEB,
                "main_sha256": hashlib.sha256(main).hexdigest(),
                "oob_sha256": hashlib.sha256(oob).hexdigest()})
        expected += length
    require(partial or expected == TOTAL, f"incomplete NAND backup: {expected}/{TOTAL}")
    return {"status": "complete" if expected == TOTAL else "partial",
            "captured_data_bytes": expected, "raw_oob_bytes": expected // PAGE * (PAGE + OOB),
            "bad_blocks": [b["block"] for b in blocks if b["bad"]],
            "bad_pool_blocks": [b["block"] for b in blocks if b["bad"]
                                and 4 << 20 <= b["offset"] < 511 << 20],
            "erased_blocks": sum(b["all_erased"] for b in blocks), "blocks": blocks}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--allow-partial", action="store_true",
                        help="inspect a prefix; never report an incomplete capture as complete")
    args = parser.parse_args()
    try:
        print(json.dumps(inventory(args.directory, args.allow_partial), indent=2))
    except (ValueError, KeyError, OSError, EOFError) as error:
        parser.exit(1, f"Backup verification failed: {error}\n")
