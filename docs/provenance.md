# Source provenance

The Rust recovery transport and RAM diagnostic client were extracted from
the project's original `u2open-libusb` host tool. Python NAND capture,
inventory and console support originate in the same project's bring-up
utilities. New host code is published under MIT.

Public tools add strict validation and explicit write confirmation. Hardware
qualification applies to the exact version and operation tested. Firmware remains in the BSP layer. This repository does not contain
vendor executable code, CE images, disassembly output or device captures.

USB identifiers, protocol constants and image-layout checks describe the
interfaces implemented by the hardware and BSP. They do not authenticate
a device or firmware image.

The container locks the base digest, Debian package snapshot, Rust and
libusb versions. Compilation uses no downloaded Rust crates. Build records
identify the container used. Repeat builds and hardware qualification are
separate claims; see [status](status.md).
