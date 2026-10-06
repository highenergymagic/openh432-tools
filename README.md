# OpenH432 host tools

Command-line tools for developing and installing OpenH432 on the HIMS
BrailleSense U2. This repository provides the Linux-host USB transport,
NAND-backup utilities and operator documentation.

OpenH432 is a Fractal Microsystems project to extend the life of existing
braille notetakers with Linux. It is independent of HIMS.

**Developer preview:** these tools are not an unattended installer. The
underlying transport has been used during hardware bring-up; this extracted,
hardened version has not yet been qualified on a device. Returning a converted
device to its complete original Windows CE state is not a tested workflow.

## Start here

- [Installation guide](docs/installation.md): from stock Windows CE through
  bootstrap, RAM Linux, backup and persistent NAND boot, with qualification gates.
- [Backup and recovery](docs/recovery.md): what can be preserved, what a backup
  proves and which restore steps remain untested.
- [CLI reference](docs/commands.md): commands, side effects and USB identities.
- [Validation status](docs/status.md): tests versus hardware qualification.

The tools use plain line-oriented output rather than a graphical interface,
color-only status or animated progress. Waiting commands let an operator start
the tool before pressing the device's recovery keys.

## Build

Supported build host: Linux x86-64 with Docker, Python 3 and Git. The container
pins its base image, package snapshot and Rust version. Build output must be
writable by UID/GID 1000:1000. The launcher uses Docker directly or through
`doas`/`sudo`.

```sh
git clone https://github.com/highenergymagic/openh432-tools.git
cd openh432-tools
python3 scripts/build.py test
python3 scripts/build.py build
./out/target/release/openh432-usb --help
```

Container setup requires network access; compilation and tests run offline,
without USB devices. No build or test command flashes anything. The host
executable needs the libusb-1.0 runtime and a compatible glibc (the current
builder uses glibc 2.41). Windows and macOS hosts are not supported yet.

Python backup and console scripts run on the Linux host with Python 3; no
third-party Python packages are required. Do not run USB operations inside
the isolated build container.

## First connection

Connect only one U2. From this repository, start the handshake waiter with
the host privileges needed to open the USB device:

```sh
sudo ./out/target/release/openh432-usb wait-auth 120
```

Use `doas` instead of `sudo` where appropriate. Hold Previous/left-media,
press Reset, and keep the key held through reset. The factory recovery
endpoint is `0547:2720`, not a serial port. A successful handshake does not
write NAND and does not establish that an image is safe to install.

Read the installation guide before using any flashing command. Flashing
replaces the CE kernel slot; it is not merely a temporary RAM boot.

## Repository boundaries

- [openh432-build](https://github.com/highenergymagic/openh432-build) builds
  pinned firmware and operating-system artifacts.
- [meta-fractalmicro-H432B](https://github.com/highenergymagic/meta-fractalmicro-H432B)
  owns the loader firmware, kernel and board support.
- [meta-fractalmicro-openh432](https://github.com/highenergymagic/meta-fractalmicro-openh432)
  owns OS policy and image composition.
- This repository owns host-side transport, backup verification and installation
  documentation. It contains no vendor firmware, compiled firmware or backups.

## License

MIT for the host tools and documentation. Firmware and operating-system
components retain their respective upstream licenses.
