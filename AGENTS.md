# Host-tool development

- This repository owns host transport, backup tooling and operator documentation,
  not bootloader firmware, kernel patches or OS policy.
- Use the pinned Docker builder through scripts/build.py. Builds/tests have no
  USB access and never install firmware.
- Never commit firmware binaries, vendor files, backups, device logs or credentials.
- Fail closed on ambiguous devices, malformed images and incomplete backups.
- NAND writes require explicit operator confirmation; never retry a commit after
  disconnect or infer success from USB acknowledgement alone.
- Unit tests, transport hardware tests, complete conversion and stock restoration
  are separate qualification claims. Keep docs/status.md accurate.
- New host code is MIT. Preserve existing copyright/license notices.
- Audit the exact Git index before public pushes.

## Public documentation

Write task-oriented reference documentation, not a development journal.
Lead with availability, configuration, interfaces and known limitations.
Keep normal-runtime support distinct from opt-in diagnostic qualification.
Put exact artifact/test evidence in validation records; retain superseded
investigation narratives in Git history and private notes. Check claims against
recipes and service policy, and run the build repository's documentation audit.

## Checkpoint completion

A hardware checkpoint includes integration into the standard NAND kernel and
systembase, not only a diagnostic recipe. Share driver/configuration sources
between runtime and diagnostics. Build the normal artifacts, verify integration
and available device behavior, update the support matrix, then publish all
affected repositories with matching manifest pins. Report any untested combined
behavior or deployment that remains; a successful build is not a device test.
Keep only genuinely unqualified experiments isolated, with an explicit reason.
