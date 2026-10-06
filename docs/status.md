# Validation and release status

This repository begins with host utilities used during OpenH432 hardware
bring-up, followed by publication hardening. Those are separate baselines.

## Hardware evidence inherited from bring-up

The predecessor recovery transport has transferred and programmed BSP CE
carriers. Initial bootstrap USB commands, RAM loading, NAND capture and
subsequent persistent Linux boot have been exercised on a development U2.
The device has booted Linux on two successive plain Resets with the factory
first-stage loader and EBOOT preserved.

This evidence does not qualify all U2 variants or a freshly compiled tool.

## Public extraction

The public version adds stricter carrier validation, explicit NAND-write
confirmation, bounded waits, ambiguous-device rejection and stricter backup
verification. It removes blind commit of an earlier RAM staging buffer.
Validation on 2026-10-06 UTC:

- 14 Rust unit tests and 14 Python tests passed in the isolated container.
- Carrier tests include truncation, corruption, range/entry errors, the
  historical cold-load pointer bug and rejection of high-RAM loader addresses.
- CLI tests exercise help, offline validation, explicit write confirmation
  and malformed arguments without any USB device.
- Backup tests cover corruption, gaps, completeness and bad-block markers.
- The offline carrier check accepted the retained hardware-tested NAND carrier
  and a freshly packaged initial bootstrap built from the public BSP artifacts.
- The backup/contract tests also passed with Python optimization enabled.
- Two fresh Cargo output directories produced identical release executables:
  SHA-256 `e125cb41ca03e3a94ef3be1eddf63fad7d75b80de85b9b302310b575ead2bdd4`.
  Both used the same pinned container on one host; this is not independent
  cross-host or container-rebuild reproducibility.
- Rust 1.85.1 and libusb 1.0.28 were built/linked from the pinned host container.

No USB device is passed to the build/test container. No hardware test or
flash is part of this repository extraction.

## Subsequent hardware checks

The hardened Linux executable has since programmed the validated USB-shell
bootstrap and restored the retained NAND-boot carrier on the qualification
device. Subsequent plain Reset reached Linux. RAM staging/CRC verification,
RAM launch and diagnostic shell commands have also been exercised.
The bounded result-only command retrieved an earlier command's output without
resending it.

These checks cover those operations on one already-modified development
device, not the complete stock conversion, all error paths or general recovery.

## Not yet qualified

- Hardware coverage of all public commands and failure paths.
- Complete stock-CE-to-Linux conversion using only public repositories.
- A general pre-modification raw NAND capture path from stock CE.
- Generalized NAND provisioning, resume and interrupted-install recovery.
- Complete original CE restoration, including ECC/OOB and applications.
- Windows/macOS host support, multiple hardware variants, endurance or
  power-loss recovery.

There is no unattended installer or public binary firmware release.
