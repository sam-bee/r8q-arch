#!/usr/bin/env bash
#
# Embed our kernel-built DTB into Mu-Silicium and build the UEFI boot image.
# The DTB (with the display fix: dispcc protected-clocks + framebuffer MDSS_GDSC
# power-domain) supplies the firmware's baseline DTB. The RTC kernel can also
# load /EFI/BOOT/R8Q-RTC.DTB from the ESP, without rebuilding this firmware.
#
# Env: MUSIL=<Mu-Silicium checkout>  DTB=<out/.../sm8250-samsung-r8q.dtb>
# UEFI_DIAGNOSTIC=1 explicitly allows temporary discovery pages/key waits.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
MUSIL="${MUSIL:?set MUSIL to your Mu-Silicium checkout}"
DTB="${DTB:?set DTB to out/arch/arm64/boot/dts/qcom/sm8250-samsung-r8q.dtb}"
VENV="${VENV:-$REPO/out/.venv}"   # authorized project venv with Mu-Silicium requirements
CLANGPDB_AARCH64_PREFIX="${CLANGPDB_AARCH64_PREFIX:-aarch64-linux-gnu-}"
export CLANGPDB_AARCH64_PREFIX

die() { echo "build-uefi.sh: $*" >&2; exit 1; }

MUSIL="$(realpath -- "$MUSIL")"
DTB="$(realpath -- "$DTB")"
VENV="$(realpath -- "$VENV")"
PYTHON="$VENV/bin/python"
FDT_BOOTSTRAP="$MUSIL/Resources/DTBs/r8q.dtb"
BOOT_POLICY="$MUSIL/Common/Mu/PcBdsPkg/MsBootPolicy/MsBootPolicy.c"

[[ -d "$MUSIL" ]] || die "Mu-Silicium checkout is not a directory: $MUSIL"
[[ -f "$DTB" ]] || die "mainline DTB is missing: $DTB"
[[ -x "$PYTHON" ]] || die "authorized project venv Python is missing: $PYTHON"
command -v "${CLANGPDB_AARCH64_PREFIX}gcc" >/dev/null || \
    die "AArch64 compiler prefix is unavailable: ${CLANGPDB_AARCH64_PREFIX}gcc"
[[ -f "$FDT_BOOTSTRAP" ]] || die "Mu-Silicium Android bootstrap DTB is missing: $FDT_BOOTSTRAP"
[[ -f "$BOOT_POLICY" && -r "$BOOT_POLICY" ]] || die "Mu boot policy source is missing or unreadable: $BOOT_POLICY"
if grep -Fq 'R8Q discovery' "$BOOT_POLICY" && \
    [[ "${UEFI_DIAGNOSTIC:-0}" != 1 ]]; then
    die "temporary Mu discovery pages are applied; reverse the diagnostic patch for unattended boot, or set UEFI_DIAGNOSTIC=1 for a deliberate diagnostic build"
fi

BOOTSTRAP_SHA="$(sha256sum -- "$FDT_BOOTSTRAP" | awk '{print $1}')"
DTB_SHA="$(sha256sum -- "$DTB" | awk '{print $1}')"

"$PYTHON" "$SCRIPT_DIR/prepare-uefi-dtb.py" --musil "$MUSIL" --dtb "$DTB"

[[ "$(sha256sum -- "$FDT_BOOTSTRAP" | awk '{print $1}')" == "$BOOTSTRAP_SHA" ]] || \
    die "Mu-Silicium Android bootstrap DTB changed unexpectedly: $FDT_BOOTSTRAP"
[[ "$(sha256sum -- "$DTB" | awk '{print $1}')" == "$DTB_SHA" ]] || \
    die "mainline DTB changed unexpectedly: $DTB"

( cd "$MUSIL" && "$PYTHON" build_uefi.py -d r8q )
OUTPUT="$MUSIL/Mu-r8q.img"
[[ -f "$OUTPUT" && ! -L "$OUTPUT" ]] || die "build completed without the expected output: $OUTPUT"
[[ "$(sha256sum -- "$FDT_BOOTSTRAP" | awk '{print $1}')" == "$BOOTSTRAP_SHA" ]] || \
    die "Mu-Silicium Android bootstrap DTB changed during build: $FDT_BOOTSTRAP"
[[ "$(sha256sum -- "$DTB" | awk '{print $1}')" == "$DTB_SHA" ]] || \
    die "mainline DTB changed during build: $DTB"
echo "[+] built $OUTPUT (embeds the validated mainline DTB); inspect it before any device operation"
