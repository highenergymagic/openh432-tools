#!/bin/sh
# SPDX-License-Identifier: MIT
# Run on the target, in the explicitly qualified RAM UBI-writer environment.
# Writes only a verified empty systembase_b. No format, creation, attach or reboot.
set -eu
test "$#" = 4 || { echo "Usage: $0 IMAGE IMAGE_SHA256 SYSTEMBASE_A_SHA256 --confirm-write-empty-systembase-b" >&2; exit 2; }
image=$1
image_sha=$2
systembase_a_sha=$3
test "$4" = --confirm-write-empty-systembase-b
case "$image" in /tmp/openh432-stage/*) ;; *) exit 2 ;; esac
for digest in "$image_sha" "$systembase_a_sha"; do
    test "${#digest}" = 64
    case "$digest" in *[!0-9a-f]*) exit 2 ;; esac
done
test -f "$image"
bytes=$(stat -c %s "$image")
test "$bytes" -gt 4096
test "$bytes" -le 209637376
test "$(id -u)" = 0
test "$(cat /sys/class/mtd/mtd0/name)" = factory-boot
test "$(cat /sys/class/mtd/mtd0/size)" = 4194304
test "$(( $(cat /sys/class/mtd/mtd0/flags) & 1024 ))" = 0
test "$(cat /sys/class/mtd/mtd1/name)" = linux-ubi
test "$(cat /sys/class/mtd/mtd1/offset)" = 4194304
test "$(cat /sys/class/mtd/mtd1/size)" = 531628032
test "$(cat /sys/class/mtd/mtd1/writesize)" = 2048
test "$(cat /sys/class/mtd/mtd1/erasesize)" = 131072
test "$(cat /sys/class/mtd/mtd1/ecc_strength)" = 8
test "$(( $(cat /sys/class/mtd/mtd1/flags) & 1024 ))" = 1024
test "$(cat /sys/class/mtd/mtd2/name)" = bbt-reserved
test "$(( $(cat /sys/class/mtd/mtd2/flags) & 1024 ))" = 0
# Resolve the internal SD by controller; MMC numbering follows probe order.
internal_sd=
for candidate in /sys/class/block/mmcblk*; do
    test -e "$candidate/partition" && continue
    case "$(readlink -f "$candidate")" in
        */eb100000.mmc/mmc_host/*/block/mmcblk*)
            test -z "$internal_sd"
            internal_sd=$candidate
            ;;
    esac
done
test -n "$internal_sd"
test "$(cat "$internal_sd/ro")" = 1
test "$(cat /sys/class/ubi/ubi0/mtd_num)" = 1
test "$(cat /sys/class/ubi/ubi0/ro_mode)" = 0
test "$(cat /sys/class/ubi/ubi0/eraseblock_size)" = 126976
test "$(cat /sys/class/ubi/ubi0_3/name)" = systembase_a
test "$(cat /sys/class/ubi/ubi0_4/name)" = systembase_b
for vol in ubi0_3 ubi0_4; do
    test "$(cat /sys/class/ubi/$vol/type)" = static
    test "$(cat /sys/class/ubi/$vol/reserved_ebs)" = 1651
    test "$(cat /sys/class/ubi/$vol/corrupted)" = 0
    test "$(cat /sys/class/ubi/$vol/upd_marker)" = 0
done
test "$(cat /sys/class/ubi/ubi0_4/data_bytes)" = 0
test "$(cat /sys/class/ubi/ubi0_3/data_bytes)" -gt 4096
if grep -Eq 'ubi0|ubiblock0' /proc/mounts; then
    echo "UBI volumes must not be mounted" >&2
    exit 1
fi
printf '%s  %s\n' "$image_sha" "$image" | sha256sum -c -
printf '%s  %s\n' "$systembase_a_sha" /dev/ubi0_3 | sha256sum -c -
echo "Preconditions passed; updating the empty systembase_b volume once."
ubiupdatevol /dev/ubi0_4 "$image"
sync
test "$(cat /sys/class/ubi/ubi0_4/data_bytes)" = "$bytes"
test "$(cat /sys/class/ubi/ubi0_4/upd_marker)" = 0
test "$(cat /sys/class/ubi/ubi0_4/corrupted)" = 0
printf '%s  %s\n' "$image_sha" /dev/ubi0_4 | sha256sum -c -
printf '%s  %s\n' "$systembase_a_sha" /dev/ubi0_3 | sha256sum -c -
echo "SYSTEMBASE_B_READBACK_AND_SYSTEMBASE_A_PRESERVATION_PASS"
