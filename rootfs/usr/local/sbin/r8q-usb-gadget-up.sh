#!/bin/sh
# Assemble the NCM USB gadget (g1) and bind the dwc3 UDC. The controller is
# built into the kernel; this script only prepares ConfigFS and the phone-side
# gadget. systemd-networkd owns the usb0 address and no host networking is done.
set -eu

UDC_ROOT=/sys/class/udc
CONFIGFS_ROOT=/sys/kernel/config
G="$CONFIGFS_ROOT/usb_gadget/g1"
EXPECTED_UDC_VENDOR=0x1d6b
EXPECTED_UDC_PRODUCT=0x0104
EXPECTED_PRODUCT=r8q-mainline
EXPECTED_MANUFACTURER=Samsung
EXPECTED_SERIAL=r8q0001
# Stable locally administered unicast addresses for this project's USB link.
# Preserve the proven host identity so NetworkManager can match every boot.
EXPECTED_DEVICE_MAC=4e:e0:a2:98:8c:90
EXPECTED_HOST_MAC=aa:dd:21:b3:df:6a

die() {
    echo "r8q-gadget: ERROR: $*" >&2
    exit 1
}

[ "$(id -u)" -eq 0 ] || die "must run as root"
[ -d "$UDC_ROOT" ] || die "UDC sysfs directory is unavailable"
[ -d "$CONFIGFS_ROOT" ] || die "ConfigFS mountpoint is unavailable"
[ ! -L "$UDC_ROOT" ] || die "UDC sysfs path is a symlink"
[ ! -L "$CONFIGFS_ROOT" ] || die "ConfigFS path is a symlink"

if ! grep -q " $CONFIGFS_ROOT configfs " /proc/mounts 2>/dev/null; then
    mount -t configfs none "$CONFIGFS_ROOT" 2>/dev/null || \
        die "could not mount ConfigFS"
fi
grep -q " $CONFIGFS_ROOT configfs " /proc/mounts 2>/dev/null || \
    die "ConfigFS is not mounted at $CONFIGFS_ROOT"

UDC=
UDC_COUNT=0
for candidate in "$UDC_ROOT"/*; do
    [ -e "$candidate" ] || continue
    [ -d "$candidate" ] || die "UDC entry is not a directory: $candidate"
    UDC=${candidate##*/}
    UDC_COUNT=$((UDC_COUNT + 1))
done
[ "$UDC_COUNT" -eq 1 ] || die "expected exactly one UDC, found $UDC_COUNT"

for target in \
    "$G" "$G/strings" "$G/strings/0x409" \
    "$G/configs" "$G/configs/c.1" "$G/configs/c.1/strings" \
    "$G/configs/c.1/strings/0x409" "$G/functions" "$G/functions/ncm.usb0"; do
    [ ! -L "$target" ] || die "ConfigFS target is a symlink: $target"
done
mkdir -p "$G/strings/0x409" "$G/configs/c.1/strings/0x409" \
         "$G/functions/ncm.usb0"

BOUND=$(cat "$G/UDC" 2>/dev/null) || die "cannot read gadget UDC binding"
if [ -n "$BOUND" ] && [ "$BOUND" != "$UDC" ]; then
    die "gadget is already bound to a different UDC: $BOUND"
fi

read_value() {
    [ ! -L "$1" ] || die "ConfigFS attribute is a symlink: $1"
    [ -f "$1" ] || die "missing ConfigFS attribute: $1"
    # NCM address attributes include a trailing NUL on the current kernel.
    value=$(tr -d '\000' < "$1") || die "cannot read ConfigFS attribute: $1"
    printf '%s' "$value"
}

write_once() {
    path=$1
    value=$2
    current=$(read_value "$path")
    if [ "$current" != "$value" ]; then
        [ -z "$BOUND" ] || die "bound gadget attribute differs at $path: $current"
        printf '%s\n' "$value" > "$path" || die "cannot write ConfigFS attribute: $path"
    fi
    [ "$(read_value "$path")" = "$value" ] || die "ConfigFS write did not stick: $path"
}

write_once "$G/idVendor" "$EXPECTED_UDC_VENDOR"
write_once "$G/idProduct" "$EXPECTED_UDC_PRODUCT"
write_once "$G/strings/0x409/product" "$EXPECTED_PRODUCT"
write_once "$G/strings/0x409/manufacturer" "$EXPECTED_MANUFACTURER"
write_once "$G/strings/0x409/serialnumber" "$EXPECTED_SERIAL"
write_once "$G/configs/c.1/strings/0x409/configuration" ncm
write_once "$G/functions/ncm.usb0/dev_addr" "$EXPECTED_DEVICE_MAC"
write_once "$G/functions/ncm.usb0/host_addr" "$EXPECTED_HOST_MAC"

LINK="$G/configs/c.1/ncm.usb0"
FUNCTION="$G/functions/ncm.usb0"
if [ -e "$LINK" ] || [ -L "$LINK" ]; then
    [ -L "$LINK" ] || die "NCM configuration entry is not a symlink: $LINK"
    [ "$(readlink -f "$LINK")" = "$FUNCTION" ] || \
        die "NCM configuration symlink points somewhere unexpected"
else
    ln -s "$FUNCTION" "$LINK" || die "cannot link NCM function"
fi

[ ! -L "$G/UDC" ] || die "gadget UDC attribute is a symlink"
[ -f "$G/UDC" ] || die "missing gadget UDC attribute"
BOUND=$(cat "$G/UDC" 2>/dev/null) || die "cannot read gadget UDC binding"
if [ -n "$BOUND" ] && [ "$BOUND" != "$UDC" ]; then
    die "gadget is already bound to a different UDC: $BOUND"
fi
if [ -z "$BOUND" ]; then
    printf '%s\n' "$UDC" > "$G/UDC" || die "cannot bind gadget to $UDC"
fi
BOUND=$(cat "$G/UDC" 2>/dev/null) || die "cannot reread gadget UDC binding"
[ "$BOUND" = "$UDC" ] || die "gadget binding did not stick"

echo "r8q-gadget: NCM gadget bound to $UDC"
