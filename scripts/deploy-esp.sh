#!/usr/bin/env bash
# Copy the kernel Image and its external RTC DTB to the verified ESP.
# Phone must be in Mu-Silicium MASS-STORAGE mode.
# The ESP is the phone's `cache` partition, reformatted vfat (label R8QESP).
set -euo pipefail
IMG="${1:?usage: ESP=/dev/verified-cache deploy-esp.sh path/to/Image path/to/DTB}"
DTB="${2:?supply the matching sm8250-samsung-r8q.dtb}"
: "${ESP:?Set ESP to the CACHE partition after verifying the phone USB/PIT mapping}"
[[ -f "$IMG" && -f "$DTB" && -b "$ESP" ]] || { echo "Invalid image, DTB or ESP" >&2; exit 1; }
[[ "$(blkid -s PARTUUID -o value "$ESP")" == 5594c694-c871-4b5f-90b1-690a6f68e0f7 ]] || { echo "Wrong SM-G7810 CACHE PARTUUID" >&2; exit 1; }
[[ "$(blkid -s TYPE -o value "$ESP")" == vfat ]] || { echo "CACHE is not a FAT ESP" >&2; exit 1; }
[[ "$(sudo blockdev --getsize64 "$ESP")" == 629145600 ]] || { echo "Wrong CACHE size" >&2; exit 1; }
[[ -z "$(findmnt -rn -S "$ESP")" ]] || { echo "CACHE is already mounted" >&2; exit 1; }
[[ "$(od -An -tx1 -N4 "$DTB" | tr -d ' \n')" == d00dfeed ]] || { echo "Invalid DTB header" >&2; exit 1; }
MNT="$(mktemp -d)"
cleanup() { sudo umount "$MNT"; rmdir "$MNT"; }
sudo mount -t vfat -o nosuid,nodev,noexec "$ESP" "$MNT"
trap cleanup EXIT
DEST="$MNT/EFI/BOOT"
[[ -f "$DEST/BOOTAA64.EFI" ]] || { echo "Existing EFI kernel is absent" >&2; exit 1; }
[[ ! -e "$DEST/BOOTAA64.PREVIOUS.EFI" ]] || { echo "Preserve or move the existing backup first" >&2; exit 1; }
[[ ! -e "$DEST/BOOTAA64.NEW.EFI" ]] || { echo "Preserve the unfinished candidate first" >&2; exit 1; }
[[ ! -e "$DEST/R8Q-RTC.DTB" ]] || { echo "Preserve the existing external DTB before updating" >&2; exit 1; }
OLD_HASH="$(sha256sum "$DEST/BOOTAA64.EFI" | cut -d ' ' -f1)"
NEW_HASH="$(sha256sum "$IMG" | cut -d ' ' -f1)"
sudo cp "$DEST/BOOTAA64.EFI" "$DEST/BOOTAA64.PREVIOUS.EFI"
[[ "$(sha256sum "$DEST/BOOTAA64.PREVIOUS.EFI" | cut -d ' ' -f1)" == "$OLD_HASH" ]]
sudo cp "$DTB" "$DEST/R8Q-RTC.DTB"
sudo cp "$IMG" "$DEST/BOOTAA64.NEW.EFI"
sync
[[ "$(sha256sum "$DEST/BOOTAA64.NEW.EFI" | cut -d ' ' -f1)" == "$NEW_HASH" ]]
[[ "$(sha256sum "$DEST/R8Q-RTC.DTB" | cut -d ' ' -f1)" == "$(sha256sum "$DTB" | cut -d ' ' -f1)" ]]
sudo mv "$DEST/BOOTAA64.NEW.EFI" "$DEST/BOOTAA64.EFI"
sync
if [[ "$(sha256sum "$DEST/BOOTAA64.EFI" | cut -d ' ' -f1)" != "$NEW_HASH" ]]; then
  sudo cp "$DEST/BOOTAA64.PREVIOUS.EFI" "$DEST/BOOTAA64.EFI"
  sync
  echo "Kernel hash failed; restored the previous kernel" >&2
  exit 1
fi
echo "[+] staged kernel + /EFI/BOOT/R8Q-RTC.DTB; previous EFI kernel retained"
