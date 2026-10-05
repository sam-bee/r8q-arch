#!/usr/bin/env bash
# Build mainline kernel Image + r8q DTB.
# Usage: KSRC=/path/to/linux OUT=/path/to/out ./scripts/build_kernel.sh [clean]
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"

: "${KSRC:?Set KSRC to the mainline kernel source tree}"
: "${OUT:?Set OUT to the kernel build directory}"

KSRC="$(realpath "$KSRC")"
mkdir -p "$OUT"
OUT="$(realpath "$OUT")"

if [[ ! -f "$KSRC/Makefile" ]]; then
    echo "KSRC does not look like a Linux kernel tree: $KSRC" >&2
    exit 1
fi

case "$OUT" in
    /|"$HOME"|"$REPO"|"$KSRC")
        echo "Refusing unsafe OUT directory: $OUT" >&2
        exit 1
        ;;
esac

export ARCH=arm64 LLVM=1

if [[ "${1:-}" == "clean" ]]; then
    rm -rf "$OUT"
    mkdir -p "$OUT"
fi

cd "$KSRC"

# Install the r8q device tree sources into the kernel tree.
cp "$REPO"/dts/sm8250-samsung-common.dtsi \
   "$REPO"/dts/sm8250-samsung-r8q.dts \
   arch/arm64/boot/dts/qcom/

# Apply the r8q kernel patches (idempotent; skips ones already applied).
# 0002 (zap via dma_alloc) is required for GPU acceleration — see INSTALLATION.md §9.
for p in "$REPO"/patches/*.patch; do
    if patch -p1 -N --dry-run < "$p" > /dev/null 2>&1; then
        echo "Applying $(basename "$p")"
        patch -p1 < "$p"
    else
        echo "Skipping $(basename "$p") (already applied?)"
    fi
done

make O="$OUT" defconfig

scripts/kconfig/merge_config.sh \
    -O "$OUT" \
    -m "$OUT/.config" \
    "$REPO/config/r8q_bringup.config"

# These paths are checkout-specific, so don't hard-code them in the
# version-controlled Kconfig fragment.
scripts/config \
    --file "$OUT/.config" \
    --set-str INITRAMFS_SOURCE \
    "$REPO/initramfs $REPO/initramfs/irfs.devnodes"

make O="$OUT" olddefconfig

make O="$OUT" -j"$(nproc)" Image.gz dtbs
make O="$OUT" -j"$(nproc)" modules

ls -la \
    "$OUT/arch/arm64/boot/Image" \
    "$OUT/arch/arm64/boot/Image.gz" \
    "$OUT/arch/arm64/boot/dts/qcom/sm8250-samsung-r8q.dtb"

