#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate a private NMEA capture without printing coordinates or UTC times."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re

def summarize(data):
    # Check only target-emitted capture blocks, not echoed shell commands.
    blocks = re.findall(rb"^GPS_CAPTURE_BEGIN\r?\n(.*?)^GPS_CAPTURE_END", data, re.S | re.M)
    counts = Counter()
    releases = []
    acks = Counter()
    valid = invalid = fixes = 0
    for block in blocks:
        for match in re.finditer(rb"\$([^\r\n$*]+)\*([0-9a-fA-F]{2})", block):
            body = match[1]
            checksum = 0
            for byte in body:
                checksum ^= byte
            if checksum != int(match[2], 16):
                invalid += 1
                continue
            fields = body.split(b",")
            ident = fields[0]
            if not re.fullmatch(rb"[A-Z][A-Z0-9]{2,15}", ident):
                invalid += 1
                continue
            if ident == b"PMTK001" and len(fields) >= 3:
                if fields[1].isdigit() and fields[2] in (b"0", b"1", b"2", b"3"):
                    acks[fields[1].decode()+":"+fields[2].decode()] += 1
            valid += 1
            counts[ident.decode("ascii")] += 1
            if ident == b"PMTK705" and all(32 <= c <= 126 for c in body):
                release = [field.decode("ascii") for field in fields[1:]]
                if release not in releases:
                    releases.append(release)
            if ident.endswith(b"RMC") and len(fields) > 2 and fields[2] == b"A":
                fixes += 1
            if ident.endswith(b"GGA") and len(fields) > 6 and fields[6] in (b"1", b"2", b"3", b"4", b"5", b"6"):
                fixes += 1
    return {"capture_blocks": len(blocks), "valid_sentences": valid,
            "invalid_checksums_or_ids": invalid, "sentence_types": dict(sorted(counts.items())),
            "fix_indicating_sentences": fixes, "firmware_releases": releases, "command_ack_counts": dict(sorted(acks.items()))}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    args = parser.parse_args()
    result = summarize(args.capture.read_bytes())
    print(json.dumps(result, indent=2))
    return 0 if result["valid_sentences"] >= 3 else 1

if __name__ == "__main__":
    raise SystemExit(main())
