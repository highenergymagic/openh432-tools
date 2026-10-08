# OpenH432 host tools

Linux command-line tools for installing and maintaining OpenH432 on the
HIMS BrailleSense U2. This repository provides USB transport, NAND-backup
utilities and installation documentation.

Device firmware is built separately by
[openh432-build](https://github.com/highenergymagic/openh432-build).
Bootloader and kernel sources belong to the
[hardware layer](https://github.com/highenergymagic/meta-fractalmicro-H432B).

## Requirements

- Linux x86-64, Git, Python 3 and Docker for the pinned host-tool build.
- An output directory writable by UID/GID `1000:1000`.
- libusb-1.0 and a glibc-compatible Linux host to run the USB executable;
  the build container uses glibc 2.41.
- USB device access permissions for live operations.

The host-tool builder supports x86-64 only. This is separate from the BSP
image builder, which also supports native ARM64. Windows and macOS are
not supported host-tool platforms.

## Build and test

```sh
git clone https://github.com/highenergymagic/openh432-tools.git
cd openh432-tools
python3 scripts/build.py test
python3 scripts/build.py build
./out/target/release/openh432-usb --help
```

The launcher pins the container, package snapshot and Rust toolchain.
Container setup requires network access; compilation and tests run offline
without USB access. Python utilities require no third-party Python packages.

## Operation

Run live commands on the Linux host, outside the build container. The CLI
uses line-oriented output and provides waiting commands so an operation can
be prepared before entering device recovery.

Start with the [installation guide](docs/installation.md). Recovery flashing
replaces the stock CE kernel slot; it is not a temporary RAM boot.
These tools are a developer workflow, not an unattended installer.
Complete restoration to stock Windows CE is not a qualified procedure.

The runtime A/B selector and `h432b-bootstate-check` utility are built by the
BSP, not this host-tool repository. Existing slot-B maintenance scripts are
not an A/B updater; read the installation guide before modifying eligible slots.

## Documentation

- [Installation](docs/installation.md): stock CE conversion and NAND deployment.
- [Command reference](docs/commands.md): syntax, device modes and side effects.
- [Backup and recovery](docs/recovery.md): capture, verification and recovery limits.
- [Validation](docs/status.md): tested operations and outstanding qualification.

Report reproducible tool problems through
[repository issues](https://github.com/highenergymagic/openh432-tools/issues).
Do not attach firmware, raw device dumps, credentials or identifying logs.

## Licence

Host tools and documentation are MIT-licensed. Firmware and operating-system
components retain their upstream licences. No vendor firmware or device
backups are distributed here.

OpenH432 is an independent Fractal Microsystems project, not endorsed by HIMS.
