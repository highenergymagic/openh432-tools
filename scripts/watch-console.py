#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Wait for the OpenH432 Linux maintenance console; run explicit checks.

Require the expected USB device, ACM interface and product identity. Historical
product/serial strings remain accepted for installed images. These descriptors
are discovery aids, not authentication. No arbitrary serial port is opened.
"""
import argparse
import errno
import glob
import os
import re
from pathlib import Path
import select
import secrets
import shlex
import sys
import termios
import time


def read_attribute(parent, name, optional=False):
    try:
        return (parent / name).read_text().strip()
    except FileNotFoundError:
        if optional:
            return ''
        raise


def linux_console_identity(parent):
    if (read_attribute(parent, 'idVendor').lower(),
            read_attribute(parent, 'idProduct').lower()) != ('0525', 'a4a7'):
        return None
    product = read_attribute(parent, 'product')
    serial = read_attribute(parent, 'serial', optional=True)
    if product == 'OpenH432-RAM' and serial == 'H432-RAM-TEST':
        return serial
    if (product != 'Braille Sense U2 (Linux)'
            or read_attribute(parent, 'manufacturer') != 'Fractal Microsystems'):
        return None
    if serial and not re.fullmatch(r'FM-H432B-MAC-[0-9A-F]{12}', serial):
        return None
    return serial


def find_console(serial=None):
    matches = []
    for entry in glob.glob('/sys/class/tty/ttyACM*'):
        device = (Path(entry) / 'device').resolve()
        acm_interface = False
        for parent in (device, *device.parents):
            try:
                if (read_attribute(parent, 'bInterfaceClass', optional=True).lower(),
                        read_attribute(parent, 'bInterfaceSubClass', optional=True).lower()) == ('02', '02'):
                    acm_interface = True
                if not acm_interface:
                    continue
                identity = linux_console_identity(parent)
                if identity is not None and (serial is None or identity == serial):
                    matches.append('/dev/' + Path(entry).name)
                    break
            except OSError as exc:
                # USB sysfs attributes can disappear between path discovery
                # and read(), including ENODEV while a gadget disconnects.
                if exc.errno in (errno.ENOENT, errno.ENODEV, errno.EACCES):
                    continue
                raise
    if len(matches) > 1:
        raise RuntimeError('multiple OpenH432 consoles match; use --serial or connect exactly one device')
    return matches[0] if matches else None


def command_status(data, token=None):
    marker = b'OPENH432_CMD_STATUS' + (b'_' + token.encode('ascii') if token else b'')
    match = re.search(rb'\n' + re.escape(marker) + rb'=([0-9]+)\r?\n', data)
    return int(match.group(1)) if match else None


def has_shell_prompt(data):
    # Only the two prompts used by our RAM development shells. This is not
    # authentication; USB product+serial identity is checked separately.
    # Newer systemd emits CSI, OSC and DCS records before the first prompt.
    data = re.sub(rb'\x1b(?:\][^\x07\x1b]*(?:\x07|\x1b\\)|P[^\x1b]*\x1b\\|\[[0-?]*[ -/]*[@-~])', b'', data)
    return re.search(rb'(?:^|\n)(?:/|~) # ', data) is not None


def write_all(fd, data, deadline):
    """Handle nonblocking ACM backpressure without replaying partial commands."""
    offset = 0
    while offset < len(data):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("USB console command write timed out")
        if not select.select([], [fd], [], min(0.1, remaining))[1]:
            continue
        try:
            count = os.write(fd, data[offset:])
        except BlockingIOError:
            continue
        if count <= 0:
            raise OSError("USB console command write made no progress")
        offset += count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--serial', help='Select an exact USB identity; new images use a factory-MAC-derived board ID')
    parser.add_argument('--wait-prompt', action='store_true',
                        help='For a new boot, wait for the RAM shell prompt before sending checks')
    parser.add_argument('--expect-disconnect', action='store_true',
                        help='Keep draining shutdown logs after successful command until USB disconnects')
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument('--command', help='Explicit shell command; defaults to read-only boot checks')
    commands.add_argument('--command-file', type=Path,
                          help='Host-side UTF-8 script to run in a child shell on the U2')
    args = parser.parse_args()
    deadline = time.monotonic() + args.timeout
    print('Waiting for the Braille Sense U2 Linux USB console...', flush=True)
    device = None
    while time.monotonic() < deadline:
        device = find_console(args.serial)
        if device:
            break
        time.sleep(0.1)
    if not device:
        raise SystemExit('No matching Linux USB console appeared before timeout')
    fd = os.open(device, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        attrs = termios.tcgetattr(fd)
        attrs[0] = 0
        attrs[1] = 0
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        attrs[3] = 0
        attrs[4] = attrs[5] = termios.B115200
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        print(f'Opened identified Linux console {device}; host monotonic={time.monotonic():.6f}', flush=True)
        # The initramfs contains a physical development shell, not a login.
        sent = False
        command_done = False
        token = secrets.token_hex(8)
        ready_at = time.monotonic() + 2
        received = bytearray()
        while time.monotonic() < deadline:
            if (not sent and time.monotonic() >= ready_at
                    and (not args.wait_prompt or has_shell_prompt(received))):
                check = args.command or ('uname -a; cat /sys/kernel/realtime; '
                         'cat /proc/meminfo; cat /proc/mounts; dmesg')
                if args.command_file:
                    check = 'sh -c ' + shlex.quote(args.command_file.read_text(encoding='utf-8'))
                print(f'Sending user-space checks; host monotonic={time.monotonic():.6f}', flush=True)
                marker = "OPENH432_CMD_STATUS_" + token
                command = ('\n' + check + "; u2_status=$?; printf '\\n" + marker + "=%s\\n' \"$u2_status\"\n").encode()
                if len(command) > 4000:
                    raise ValueError('console command exceeds the target tty line limit')
                write_all(fd, command, deadline)
                sent = True
            if not select.select([fd], [], [], 0.1)[0]:
                continue
            try:
                data = os.read(fd, 65536)
            except OSError as exc:
                if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                    continue
                if args.expect_disconnect and command_done and exc.errno in (errno.EIO, errno.ENODEV, errno.ENXIO):
                    print('\nUSB disconnected after successful command.', flush=True)
                    return
                raise
            if not data:
                if args.expect_disconnect and command_done and not find_console(args.serial):
                    print('\nUSB disconnected after successful command.', flush=True)
                    return
                continue
            received.extend(data)
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
            status = command_status(received, token)
            if sent and not command_done and status is not None:
                if status:
                    raise SystemExit(f'Target command failed with status {status}')
                command_done = True
                print('\nConfirmed successful user-space command completion.', flush=True)
                if not args.expect_disconnect:
                    return
                print('Keeping USB console open to drain shutdown logs...', flush=True)
        raise SystemExit('Console appeared but user-space commands did not complete')
    finally:
        os.close(fd)


if __name__ == '__main__':
    main()
