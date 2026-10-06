# Command reference

Run `openh432-usb --help` for argument syntax. No arguments prints help
without opening USB. Errors exit nonzero. Waiting commands default to
120 seconds and require a positive integer timeout.

## Recovery transport

- `list`: enumerate exactly one `0547:2720` recovery candidate. The
  identity is shared by other Samsung development hardware; it is not
  cryptographic proof of a supported U2. Confirm the physical model.
- `auth`, `wait-auth`: open the bulk interface and perform its protocol
  handshake. This is synchronization, not user authentication.
- `version`, `wait-version`: ask EBOOT for its version record.
- `check-carrier IMAGE`: offline structural validation of this BSP's
  single-record, bounded CE carrier. No device is opened.
- `stage-os`, `wait-stage-os`: validate and transfer a carrier to RAM.
  Neither boots it nor commits it to NAND.
- `flash-os`, `wait-flash-os`: validate, transfer, then ask EBOOT to program
  its OS/NK slot. Require a final `--confirm-replace-ce` argument.
  No EBOOT replacement command is implemented.

The carrier validator checks size, record checksums, load/entry addresses,
ECEC/ROMHDR pointers, NK module table and low-address U-Boot link marker.
Only trusted artifacts built for this board should be supplied; structural
validation is not a signature check.

Programming progress reports EBOOT acknowledgements, not independent readback.
The tool does not retry a partially completed flash, commit an unidentified
previous staging buffer, or automatically reboot after an error.

## U-Boot diagnostics

The development U-Boot endpoint is `1d50:6152`.

- `wait-probe`: wait for the expected protocol response.
- `probe-shell 'COMMAND'`: execute one explicit U-Boot command. This is
  privileged access: a shell command can modify hardware or persistent data.
  Only use commands you understand.
- `time-boot`: begin with the U-Boot shell connected, press plain Reset,
  and measure disconnect-to-fresh-shell time. This is not a Linux boot timer.

Errors and truncated command output are reported as failures. The host wait
bound is 180 seconds; a timeout does not cancel a target command. probe-result
reads an existing result without sending a new command. Do not blindly resend
an operation after a timeout.

## Legacy RAM loader transport

`ram-stage-loader FILE` writes a high-address loader through the initial
bootstrap shell and verifies CRC32. `ram-launch-loader FILE` verifies the
same staged bytes before requesting execution. These commands require
protocol revision 51.

`ram-upload`, `ram-status` and `ram-boot` are for the older revision-52
RAM upload protocol only. They are retained for development, not as the
recommended installation interface. The newer fastboot loader uses the
standard host fastboot tool instead.

A successful launch request is not confirmation of a running loader/kernel.
RAM-only loaders do not become persistent merely because they execute.

## Python tools

- `capture-nand.py`: capture qualified NAND regions through the Linux
  development USB console. It reads NAND and writes private host backup files.
- `inventory-nand-backup.py`: offline coverage/checksum verification and
  physical eraseblock inventory. It never opens USB or writes NAND.
- `watch-console.py`: wait for the development Linux console and run
  diagnostic commands. Its default checks are read-only. Explicit
  `--command` and `--command-file` execute privileged shell input;
  they are not confined to read-only operations.

Console discovery rejects multiple matching devices. Use only one host
client at a time. Do not expose these privileged physical interfaces
through a network.

## Linux host permissions

The tools need access to the relevant USB device or ACM tty. The documented
development method is a single explicit `sudo` or `doas` invocation.
No broad world-writable udev rule or automatic driver replacement is installed.

Windows recovery-driver behavior has not been qualified for this public tool.
A Windows sync driver and a Linux kernel's `cdc_subset` message are not
evidence that factory recovery is a COM port.
