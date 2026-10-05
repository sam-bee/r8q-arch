#!/usr/bin/env bash
# Build mainline kernel Image + r8q DTB.
# Usage: KSRC=/path/to/linux OUT=/path/to/out [JOBS=N] [R8Q_BOOT_MODE=arch|debug] ./scripts/build_kernel.sh [clean]
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
R8Q_USER_HOME="$(realpath "$HOME")"
JOBS="${JOBS:-$(nproc)}"
R8Q_BOOT_MODE="${R8Q_BOOT_MODE:-arch}"
if [[ ! "$JOBS" =~ ^[1-9][0-9]*$ ]]; then
    echo "JOBS must be a positive integer" >&2
    exit 1
fi
case "$R8Q_BOOT_MODE" in
    arch|debug) ;;
    *) echo "R8Q_BOOT_MODE must be arch or debug" >&2; exit 1 ;;
esac

: "${KSRC:?Set KSRC to the mainline kernel source tree}"
: "${OUT:?Set OUT to the kernel build directory}"

KSRC="$(realpath "$KSRC")"
OUT="$(realpath -m "$OUT")"

if [[ ! -f "$KSRC/Makefile" ]]; then
    echo "KSRC does not look like a Linux kernel tree: $KSRC" >&2
    exit 1
fi

case "$OUT" in
    /|"$R8Q_USER_HOME"|"$REPO"|"$KSRC")
        echo "Refusing unsafe OUT directory: $OUT" >&2
        exit 1
        ;;
esac

# A clean build must never remove an ancestor of either source checkout.
if [[ "$KSRC" == "$OUT/"* || "$REPO" == "$OUT/"* || "$R8Q_USER_HOME" == "$OUT/"* ]]; then
    echo "Refusing OUT directory containing a source checkout: $OUT" >&2
    exit 1
fi
case "$OUT" in
    "$REPO"/out|"$REPO"/out/*) ;;
    "$REPO"/*)
        echo "Use $REPO/out or an output directory outside this checkout" >&2
        exit 1
        ;;
esac

BUSYBOX="$REPO/initramfs/bin/busybox"
if [[ ! -x "$BUSYBOX" ]]; then
    echo "Missing executable static aarch64 BusyBox: $BUSYBOX" >&2
    exit 1
fi
if ! readelf -h "$BUSYBOX" | grep -q 'Machine:.*AArch64'; then
    echo "Initramfs BusyBox must be an aarch64 ELF executable: $BUSYBOX" >&2
    exit 1
fi
if readelf -l "$BUSYBOX" | grep -q 'INTERP'; then
    echo "Initramfs BusyBox must be statically linked: $BUSYBOX" >&2
    exit 1
fi
mkdir -p "$OUT"

export ARCH=arm64 LLVM=1

if [[ "${1:-}" == "clean" ]]; then
    rm -rf "$OUT"
    mkdir -p "$OUT"
fi

cd "$KSRC"

# Install the r8q device tree sources into the kernel tree.
for target in arch/arm64/boot/dts/qcom/sm8250-samsung-common.dtsi \
              arch/arm64/boot/dts/qcom/sm8250-samsung-r8q.dts \
              drivers/input/touchscreen/fts5cu56a.c; do
    if [[ -L "$target" ]]; then
        echo "Refusing symlinked source destination: $KSRC/$target" >&2
        exit 1
    fi
done
cp "$REPO"/dts/sm8250-samsung-common.dtsi \
   "$REPO"/dts/sm8250-samsung-r8q.dts \
   arch/arm64/boot/dts/qcom/

# Patch 0004 adds only Kconfig/Makefile entries; the driver is a separate file.
cp "$REPO/patches/fts5cu56a.c" drivers/input/touchscreen/fts5cu56a.c

# Apply the r8q kernel patches (idempotent; skips ones already applied).
# 0002 (zap via dma_alloc) is required for GPU acceleration — see INSTALLATION.md §9.
for p in "$REPO"/patches/*.patch; do
    if patch -p1 -N --fuzz=0 --dry-run < "$p" > /dev/null 2>&1; then
        echo "Applying $(basename "$p")"
        patch -p1 --fuzz=0 < "$p"
    elif patch -p1 -R --fuzz=0 --dry-run < "$p" > /dev/null 2>&1; then
        echo "Skipping $(basename "$p") (already applied)"
    else
        echo "Patch does not apply and is not already applied: $p" >&2
        exit 1
    fi
done

make O="$OUT" defconfig

scripts/kconfig/merge_config.sh \
    -O "$OUT" \
    -m "$OUT/.config" \
    "$REPO/config/r8q_bringup.config"

# These paths are checkout-specific, so don't hard-code them in the
# version-controlled Kconfig fragment.
# Kconfig's ROOT_UID/GID identify host owners to map to root in the archive.
scripts/config \
    --file "$OUT/.config" \
    --set-str INITRAMFS_SOURCE \
    "$REPO/initramfs $REPO/initramfs/irfs.devnodes" \
    --set-val INITRAMFS_ROOT_UID "$(id -u)" \
    --set-val INITRAMFS_ROOT_GID "$(id -g)"

# Prove the kernel/USB path before attempting an Arch root mount.
if [[ "$R8Q_BOOT_MODE" == debug ]]; then
    R8Q_CMDLINE="$(scripts/config --file "$OUT/.config" --state CMDLINE)"
    scripts/config --file "$OUT/.config" --set-str CMDLINE "$R8Q_CMDLINE r8q.debug=1"
fi

make O="$OUT" olddefconfig

make O="$OUT" -j"$JOBS" Image.gz dtbs
make O="$OUT" -j"$JOBS" modules

ls -la \
    "$OUT/arch/arm64/boot/Image" \
    "$OUT/arch/arm64/boot/Image.gz" \
    "$OUT/arch/arm64/boot/dts/qcom/sm8250-samsung-r8q.dtb"
