#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Transfer a SHA256-verified file to the identified development USB console.

Files are staged in private tmpfs storage, never executed or flashed. A failed
transfer is not retried. If interrupted while sending, reset the development
device before reopening its shell; the receiver may still be reading raw bytes.
"""
import argparse
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import secrets
import select
import shlex
import termios
import time

SPEC = importlib.util.spec_from_file_location(
    "console", Path(__file__).with_name("watch-console.py"))
console = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(console)
MAX_SIZE = 64 << 20


def transfer_command(name, size, token):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", name):
        raise ValueError("invalid tmpfs filename")
    if not 0 < size <= MAX_SIZE:
        raise ValueError("file must be 1 byte..64 MiB")
    if not re.fullmatch(r"[0-9a-f]{24}", token):
        raise ValueError("invalid transfer token")
    dest = "/tmp/openh432-stage/" + name
    shell = f"""set -eu
test "$(stat -f -c %T /tmp)" = tmpfs
test ! -L /tmp/openh432-stage
mkdir -p -m 700 /tmp/openh432-stage
test "$(stat -c %u /tmp/openh432-stage)" = 0
chmod 700 /tmp/openh432-stage
test ! -e {dest}
test ! -L {dest}
set -C
saved=$(stty -g < /dev/tty)
trap 'stty "$saved" < /dev/tty' EXIT
stty raw -echo < /dev/tty
printf '\\n{token}_READY\\n'
head -c {size} > {dest}
test "$(stat -c %s {dest})" = {size}
printf '\\n{token}_HASH '
sha256sum {dest}
"""
    command = ("sh -c " + shlex.quote(shell)
               + f"; printf '\\n{token}_END=%s\\n' \"$?\"\n")
    return dest, command


def push(source, name, timeout):
    # Reject invalid names before reading a potentially large source.
    transfer_command(name, 1, "0" * 24)
    data = source.read_bytes()
    token = secrets.token_hex(12)
    dest, command = transfer_command(name, len(data), token)
    expected = hashlib.sha256(data).hexdigest()
    device = console.find_console()
    if not device:
        raise RuntimeError("identified OpenH432 development console absent")
    fd = os.open(device, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    start = time.monotonic()
    deadline = start + timeout
    buffer = b""
    sent = False
    got_hash = None
    try:
        attrs = termios.tcgetattr(fd)
        attrs[0] = attrs[1] = attrs[3] = 0
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        attrs[4] = attrs[5] = termios.B115200
        attrs[6][termios.VMIN] = attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        console.write_all(fd, command.encode(), deadline)
        while time.monotonic() < deadline:
            if not select.select([fd], [], [], 0.1)[0]:
                continue
            block = os.read(fd, 65536)
            if not block:
                raise RuntimeError("console disconnected; transfer incomplete")
            buffer += block
            if len(buffer) > 1 << 20:
                raise RuntimeError("console response exceeds framing limit")
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                line = line.rstrip(b"\r")
                if line == (token + "_READY").encode():
                    if sent:
                        raise RuntimeError("duplicate READY")
                    console.write_all(fd, data, deadline)
                    sent = True
                    print(f"Sent {len(data)} bytes; waiting for SHA256", flush=True)
                elif line.startswith((token + "_HASH ").encode()):
                    fields = line.split()
                    got_hash = fields[1].decode() if len(fields) > 1 else None
                elif line.startswith((token + "_END=").encode()):
                    if (line != (token + "_END=0").encode() or not sent
                            or got_hash != expected):
                        raise RuntimeError("transfer failed or checksum mismatch")
                    print(f"Verified {dest}: {len(data)} bytes SHA256 {expected}, "
                          f"{time.monotonic() - start:.3f}s. No firmware flashed.",
                          flush=True)
                    return
        raise TimeoutError("tmpfs file transfer timed out")
    finally:
        os.close(fd)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    if args.timeout <= 0 or args.timeout > 300:
        parser.error("timeout must be 1..300 seconds")
    push(args.source, args.name, args.timeout)
