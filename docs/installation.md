# From Windows CE to OpenH432

This is a developer conversion guide, not a supported end-user installation
recipe. It records the demonstrated sequence and identifies the steps that
still need a reusable installer. Stop at any unmet prerequisite; do not infer
success from a USB acknowledgement.

The target is the H432B BrailleSense U2 used by this BSP, not the U2 Mini or
other Sense models. NAND geometry, factory boot contents and board variants
must be checked before provisioning.

## What changes

The factory first-stage loader and EBOOT are retained. An OpenH432 bootstrap
replaces the Windows CE NK image in its existing slot. A temporary Linux
environment then provides backup and storage inspection. Provisioning a Linux
UBI pool destroys the previous CE data in that pool; it does not repartition
the internal SD card. The final bootstrap loads Linux from NAND.

Current NAND boots use a minimal initramfs to mount a separate SquashFS
systembase and start systemd. Writable state is volatile; this is not a
finished accessible desktop, persistent userdata, or dual boot with CE.

## Before you begin

1. Export documents and settings using the working CE system. Back up the
   internal SD contents separately and verify the exported files.
2. Keep stable external power connected. Do not begin while the device is
   needed for communication or everyday accessibility.
3. Obtain the correct original firmware and recovery materials privately.
   Merely possessing an archive is not proof that stock restoration works.
4. Use pinned source revisions from the build repository, record artifact
   SHA-256 hashes, and review the BSP boot contract.
5. Read [backup and recovery](recovery.md). The currently demonstrated path
   first replaces CE's NK slot, then captures NAND from Linux. Such a capture
   cannot contain the original NK bytes already replaced. A complete,
   pre-modification backup and tested stock restore are still gaps.
6. Build the host tool and run its offline tests. Selected public commands are device-tested, but complete conversion and
   all failure paths are not qualified.

If losing CE functionality or lacking a tested return-to-stock procedure is
unacceptable, stop here.

## 1. Confirm factory recovery

On the Linux host:

```sh
sudo ./out/target/release/openh432-usb wait-auth 120
```

Hold Previous/left-media and press Reset. Leave the U2 in recovery until the
tool finishes. Expected identity: USB `0547:2720`, often labelled
`SEC S5PC110X Test B/D` or `Anchor USB EZ-Link Cable`. Recovery can time out.

The normal CE synchronization identity, `045e:00ce`, is not this interface.
A Linux `cdc_subset` probe failure alone does not show that recovery failed;
the tool talks directly to the bulk USB interface. No COM-port driver is used.

A successful `ATUD -> OKUD` exchange confirms communication only. Do not
send a flash command to troubleshoot driver permissions.

## 2. Build and validate the initial bootstrap

Follow the build repository's container setup and checkout instructions.
From its checkout, build the low-address bootstrap and fastboot RAM loader:

```sh
python3 scripts/bsp.py fetch u-boot-h432b u-boot-h432b-fastboot openh432-fastboot-ram
python3 scripts/bsp.py build u-boot-h432b u-boot-h432b-fastboot openh432-fastboot-ram
```

The low-address raw artifact is
`work/build/tmp/deploy/images/h432b/nand51-raw/u-boot.bin`.
It is NOT itself a factory update image.

Package it offline using the carrier packager from the pinned BSP checkout:

```sh
python3 work/layers/meta-fractalmicro-H432B/recipes-bsp/u-boot/files/chain/ce-carrier.py \
  work/build/tmp/deploy/images/h432b/nand51-raw/u-boot.bin \
  work/initial-bootstrap.b000ff
sha256sum work/initial-bootstrap.b000ff
```

If a pinned revision does not contain this packager, stop and update the
composition deliberately; do not substitute an arbitrary script or binary.
The packager checks the physical link address and cold-boot header.

From the tools checkout, validate the resulting file, replacing the example
absolute path with your actual build checkout:

```sh
./out/target/release/openh432-usb check-carrier /path/to/openh432-build/work/initial-bootstrap.b000ff
```

Validation rejects raw binaries, wrong link addresses, corrupt records and the
incorrect ROMHDR pointer pair that can allow recovery boot but break NAND boot.
It does not authenticate the firmware or qualify it on hardware.

## 3. Replace the CE NK slot (destructive, explicit)

This is the first persistent change. It removes the currently installed CE
kernel from its slot. The downloader does not back up that slot first.

Only after the preceding prerequisites and a deliberate decision to proceed:

```sh
sudo ./out/target/release/openh432-usb wait-flash-os \
  /path/to/openh432-build/work/initial-bootstrap.b000ff 120 --confirm-replace-ce
```

Enter recovery when the tool announces that it is waiting. Do not reset,
disconnect USB or remove power during programming. The tool reports staging
and factory NAND acknowledgements line by line. It does not automatically
repeat a failed flash, restore stock, or prove persistent readback.

Successful transfers have launched the installed bootstrap in qualification.
Confirm its shell separately:

```sh
sudo ./out/target/release/openh432-usb wait-probe 120
sudo ./out/target/release/openh432-usb probe-shell 'version'
```

Then test plain Reset and confirm the shell returns. Do not proceed solely
because the recovery-assisted launch worked.

## 4. Boot temporary Linux, without provisioning storage

The initial bootstrap exposes the legacy U-Boot shell protocol. It can stage
the BSP's high-RAM fastboot loader, verify its CRC, then request execution:

```sh
sudo ./out/target/release/openh432-usb ram-stage-loader \
  /path/to/openh432-build/work/build/tmp/deploy/images/h432b/ram53-fastboot-only/u-boot.bin
sudo ./out/target/release/openh432-usb ram-launch-loader \
  /path/to/openh432-build/work/build/tmp/deploy/images/h432b/ram53-fastboot-only/u-boot.bin
```

These commands require the initial bootstrap's exact protocol revision.
They must not be used against an unidentified shell. The high-RAM loader
must NEVER be wrapped as the persistent low-address bootstrap.

Use the standard fastboot host tool as described in the
[BSP fastboot guide](https://github.com/highenergymagic/meta-fractalmicro-H432B/blob/main/docs/fastboot.md)
to boot `openh432-ram-boot.img`. Fastboot flash and erase are not implemented;
fastboot boot does not install Linux to NAND. This standalone recovery bundle
uses the runtime kernel: Linux UBI and internal SD writes are permitted, with
the factory boot and BBT regions protected. It does not automatically mount,
format or provision persistent storage; do not treat it as a read-only backup
configuration.

Once Linux enumerates, use `scripts/watch-console.py` for read-only boot
diagnostics. Only one tool may own the USB console at a time.

## 5. Capture and verify the remaining NAND state

Before formatting anything, boot the BSP's read-only raw NAND capture
configuration and follow [the backup procedure](recovery.md#capturing-nand).
The capture tool expects the named full-device read-only MTD view and exact
page/OOB geometry; it deliberately stops if the running kernel exposes a
different layout.

A full backup includes main data, OOB and physical bad-block positions.
Keep it private and retain a second copy. An after-bootstrap backup protects
the state at capture time, not the already-replaced stock NK image.

**Qualification gate:** if you cannot expose the required read-only view,
capture every physical block, and verify the backup offline, do not provision.
The default partitioned kernel is not automatically a full-device capture
environment. Building a universally usable capture image remains installer
work; do not bypass the name/geometry checks.

## 6. Provision the Linux NAND pool

This phase was demonstrated on the development device but is not automated
by this repository. The old one-device provisioning script is deliberately
not shipped as an installer: it assumed a particular bad-block count and
particular image hashes.

A general implementation must:

- Identify the geometry and bad-block map; reject unsupported variants.
- Verify and preserve the factory prefix and reserved BBT tail, including OOB.
- Verify all image hashes and sizes against a release manifest.
- Open only the BSP's bounded Linux-pool write profile, leaving internal SD read-only.
- Obtain a separate confirmation before replacing CE data in that pool.
- Provision UBI volumes, populate the selected kernel and systembase volumes,
  and verify complete readbacks, filesystem contents and ECC results.
- Leave a usable recovery/bootstrap path if any intermediate step fails.

See the [NAND contract](https://github.com/highenergymagic/meta-fractalmicro-H432B/blob/main/docs/nand.md)
for the current layout. Do not apply a raw desktop partition table to NAND
or assume another unit has the same bad-block count.

**Stop here for an unattended conversion.** There is no supported generic
provisioning command yet. Do not install the NAND-autoboot carrier onto an
unprovisioned pool and expect it to install the OS.

## 7. Enable and verify NAND boot

After the pool is provisioned and verified, the BSP target
`u-boot-h432b-maintenance-chain` builds the persistent NAND bootstrap carrier at
`nand-maintenance-ce-carrier/u-boot-ce.b000ff` within the deploy directory. Validate
and explicitly flash that carrier through the same factory OS route. It
selects `kernel_b`, which must contain `openh432-nand-b.img`, with a matching
`systembase_b` populated from `openh432-systembase-b`. It is not automatic
A/B selection.

Qualification requires raw readback of the installed carrier, comparison of
the factory boot prefix against its backup, and at least two plain-Reset
Linux boots with no uploader or RAM-staging tool running. Check UBI integrity,
ECC status, kernel identity, systemd health and factory-region protections.

These reset tests have passed on the development device. They do not prove
power-loss recovery, endurance, complete stock restoration or support for
every U2. Keep build success, transport success and installation qualification
as separate records.
