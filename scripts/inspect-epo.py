#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline GPS-only 72-byte EPO structural inspector, not an upload validator.

Does not access serial devices, fetch data, check record-internal checksums,
or establish receiver compatibility. Times are GPS hours, not UTC.
"""
import argparse
from collections import Counter
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path

def inspect(data):
    if not data or len(data) > 276480 or len(data) % 2304:
        raise ValueError("Expected 1..120 complete GPS-only 2304-byte EPO sets")
    first = int.from_bytes(data[:3], "little")
    ids = Counter()
    for index in range(len(data) // 72):
        record = data[index * 72:(index + 1) * 72]
        hour = int.from_bytes(record[:3], "little")
        if hour != first + 6 * (index // 32):
            raise ValueError("Non-consecutive or inconsistent record GPS hours")
        sat = record[3]
        if sat not in (0, index % 32 + 1):
            raise ValueError("Unexpected satellite slot identifier")
        ids[sat] += 1
    sets = len(data) // 2304
    epoch = datetime(1980, 1, 6)
    return {
        "bytes": len(data), "sets": sets, "record_bytes": 72,
        "first_gps_hour": first, "end_gps_hour_exclusive": first + sets * 6,
        "start_gps_calendar": (epoch + timedelta(hours=first)).isoformat(),
        "end_gps_calendar_exclusive": (epoch + timedelta(hours=first + sets * 6)).isoformat(),
        "zero_id_records": ids[0],
        "sha256": hashlib.sha256(data).hexdigest(),
        "upload_qualified": False,
    }

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    try:
        with args.file.open("rb") as stream:
            data = stream.read(276481)
        print(json.dumps(inspect(data), indent=2))
    except (OSError, ValueError) as exc:
        parser.exit(1, str(exc) + "\n")

if __name__ == "__main__":
    main()
