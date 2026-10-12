#!/bin/sh
# SPDX-License-Identifier: MIT
# Run on the target. Migrate/update one inactive kernel+verity root pair.
set -eu
test "$#" = 6 || {
    echo "Usage: $0 A|B KERNEL VERITY_IMAGE KERNEL_SHA256 IMAGE_SHA256 --confirm-replace-inactive-slot" >&2
    exit 2
}
slot=$1
kernel=$2
image=$3
kernel_sha=$4
image_sha=$5
test "$6" = --confirm-replace-inactive-slot
test "$(id -u)" = 0
case "$slot" in
    A) kernel_id=0; root_id=3; suffix=a; other=B ;;
    B) kernel_id=1; root_id=4; suffix=b; other=A ;;
    *) exit 2 ;;
esac
for digest in "$kernel_sha" "$image_sha"; do
    test "${#digest}" = 64
    case "$digest" in *[!0-9a-f]*) exit 2 ;; esac
done
test -f "$kernel" && test -f "$image"
test "$(stat -c %s "$kernel")" -le 16760832
test "$(stat -c %s "$kernel")" -gt 2048
test "$(stat -c %s "$image")" -le 209637376
test "$(stat -c %s "$image")" -gt 8192
check_hash() {
    actual=$(sha256sum < "$2")
    test "${actual%% *}" = "$1" || { echo "Hash mismatch: $2" >&2; return 1; }
}
check_hash "$kernel_sha" "$kernel"
check_hash "$image_sha" "$image"
active=
for arg in $(cat /proc/cmdline); do
    case "$arg" in rauc.slot=*) test -z "$active"; active=${arg#rauc.slot=} ;; esac
done
test "$active" = "$other" || { echo "Target must be the inactive slot" >&2; exit 1; }
test "$(fw_printenv -n BOOT_${other}_LEFT)" = 3
test "$(cat /sys/class/ubi/ubi0/mtd_num)" = 1
test "$(cat /sys/class/mtd/mtd1/name)" = linux-ubi
test "$(cat /sys/class/mtd/mtd1/offset)" = 4194304
test "$(cat /sys/class/mtd/mtd1/size)" = 531628032
test "$(cat /sys/class/ubi/ubi0/eraseblock_size)" = 126976
test "$(cat /sys/class/ubi/ubi0_${kernel_id}/name)" = "kernel_$suffix"
test "$(cat /sys/class/ubi/ubi0_${kernel_id}/type)" = static
test "$(cat /sys/class/ubi/ubi0_${root_id}/name)" = "systembase_$suffix"
test "$(cat /sys/class/ubi/ubi0_${root_id}/type)" = static
test "$(cat /sys/class/ubi/ubi0_${root_id}/reserved_ebs)" = 1651
test ! -e "/sys/class/block/ubiblock0_$root_id"
mkdir /run/openh432-slot-update.lock
trap 'rmdir /run/openh432-slot-update.lock' EXIT
trap 'exit 1' HUP INT TERM
# A power interruption from here leaves the target ineligible. The active pair
# and factory loader are not touched. Never reactivate after a failed write.
fw_setenv BOOT_${slot}_LEFT 0
ubiupdatevol "/dev/ubi0_$kernel_id" "$kernel"
check_hash "$kernel_sha" "/dev/ubi0_$kernel_id"
ubirmvol /dev/ubi0 -n "$root_id"
ubimkvol /dev/ubi0 -n "$root_id" -N "systembase_$suffix" -S 1651 -t static --skipcheck
ubiupdatevol "/dev/ubi0_$root_id" "$image"
sync
check_hash "$image_sha" "/dev/ubi0_$root_id"
for number in "$kernel_id" "$root_id"; do
    test "$(cat /sys/class/ubi/ubi0_$number/upd_marker)" = 0
    test "$(cat /sys/class/ubi/ubi0_$number/corrupted)" = 0
done
fw_setenv BOOT_${slot}_LEFT 3
fw_setenv BOOT_ORDER "$slot $other"
fw_printenv BOOT_ORDER BOOT_A_LEFT BOOT_B_LEFT
echo "Slot $slot installed and read back. Reboot separately to qualify the pair."
