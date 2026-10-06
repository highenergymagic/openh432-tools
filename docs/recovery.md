# Backup and recovery

Recovery mode, a backup file and a tested restore procedure are three
different things. The project currently has the first two, not a qualified
complete return-to-stock procedure.

## What to preserve

- Documents and settings exported from Windows CE before conversion.
- A separate copy of the internal SD contents.
- Original firmware and updater materials appropriate to the exact unit.
- NAND main data and OOB, with offsets, checksums and bad-block information.
- Source commits, build records and hashes of every installed artifact.

Keep backups private; they may contain personal data and proprietary firmware.
Do not attach them to public issues or commit them to a repository.

The first bootstrap replaces the CE NK slot. Capturing NAND afterward does
not undo that loss or turn the capture into a stock backup. Label backups
with when they were taken and which modifications had already occurred.

## Capturing NAND

Prerequisites: Linux is already running in RAM with the qualified
read-only full-device MTD view named `u2-nand-raw-readonly`, 512 MiB main
data, 2048-byte pages and 64-byte OOB. The kernel needs the appropriate raw
NAND support, and the RAM image needs `nanddump`, gzip and base64.
The USB console must identify as `OpenH432-RAM` / `H432-RAM-TEST`.
These are development protocol identifiers, not security credentials or
unique per-device serial numbers.

The default partitioned kernel does not necessarily provide this view.
Do not rename a partition or remove geometry checks to make the tool proceed.
A general capture-image build is still an installer qualification task.

Close other console clients, then run on the Linux host:

```sh
sudo python3 scripts/capture-nand.py --region raw --output /private/path/u2-backup
sudo python3 scripts/inventory-nand-backup.py /private/path/u2-backup
```

Use a new private directory outside the checkout. The capture is chunked,
includes OOB and bad blocks, and compares the host transfer hash with the
device's hash. Files are created owner-only. Existing or partial captures
are not silently overwritten or resumed; preserve them and use a new
directory after investigating a failure.

The offline inventory requires complete, contiguous coverage unless
`--allow-partial` is explicitly requested. Partial inspection never
promotes a capture to a complete backup. A complete result proves the
recorded geometry, coverage and integrity, not that restoration will work.
It also cannot prove that the captured bytes were the factory originals.

For preserving only the boot prefix on an already partitioned kernel,
`--region boot` expects a 4 MiB `factory-boot` view. That is not a full
backup. Region names and geometry are deliberately strict.

## If an operation fails

- Before a NAND commit: the OS staging command has only transferred data
  to RAM. It does not execute the image. Reset discards that staging state.
- During/after a NAND commit: assume the NK slot may be partially changed.
  Do not automatically repeat the write or assume the previous OS survives.
- If normal boot fails but recovery enumerates: preserve the failure output
  and verify the exact carrier before planning another operation.
- If factory recovery no longer enumerates: this USB tool has no lower-level
  recovery capability. Further writes are not a diagnosis.

The retained EBOOT path has been used to replace the OpenH432 bootstrap.
That does not establish complete restoration of CE partitions, applications
or settings.

## Why there is no raw restore command

The factory prefix and the Linux NAND pool use different ECC/OOB conventions.
Blindly replaying a raw dump through the Linux data driver, ignoring bad-block
positions, or substituting a downloaded EBOOT can make recovery worse.

A supported restore workflow needs matching device geometry, an identified
backup, a qualified writer for each region, protected boot boundaries,
readback verification and interruption tests. Until these are demonstrated,
this repository intentionally provides no automated raw restore or
factory-bootloader replacement command.
