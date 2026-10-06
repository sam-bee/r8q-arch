# UEFI boot discovery on SM-G7810

Use this temporary diagnostic when Mu starts but cannot boot the EFI kernel
already staged on CACHE. The initial SM-G7810 test reached Mu's menu, but
Internal Storage returned without booting Linux. A complete CACHE readback
matched the staged FAT image. Offline checks passed for both GPT copies,
CACHE's attributes/range, FAT32 structures and the kernel's PE headers.
Those checks do not establish Mu's runtime BlockIo geometry, filesystem
publication or image loading.

The patch adds console pages only to the explicit **Internal Storage** option
(`SSD` load option). Default boot, USB Storage, FFU and Mass Storage retain
their existing behavior. It reports published storage protocols, whole-device
geometry, CACHE recognition, read-mode access to `\EFI\BOOT\BOOTAA64.EFI`
and the existing boot attempt's EFI status. CACHE identification is diagnostic
context; the existing boot filtering and ordering remain in use.

## Build with the existing approved environment

The patch targets Mu-Silicium commit
`07b08388a06f2322150d06607eb26f856ce11786`, whose `Common/Mu` submodule is
`b8d46c71610318e36a661819e1e3c0b8bdda413a`.
Review local changes and preserve the original working Mu image before building.
The wrapper overwrites `$MUSIL/Mu-r8q.img`, so copy each reviewed candidate to
a separate output directory. Use the existing approved project environment;
do not run setup/update or install missing dependencies without operator approval.

```bash
# R8Q_REPO and MUSIL are absolute paths; DTB is the reviewed mainline DTB.
test "$(git -C "$MUSIL" rev-parse HEAD)" = 07b08388a06f2322150d06607eb26f856ce11786
test "$(git -C "$MUSIL/Common/Mu" rev-parse HEAD)" = b8d46c71610318e36a661819e1e3c0b8bdda413a
git -C "$MUSIL/Common/Mu" apply --check "$R8Q_REPO/patches/uefi/0001-msbootpolicy-r8q-discovery.patch"
git -C "$MUSIL/Common/Mu" apply "$R8Q_REPO/patches/uefi/0001-msbootpolicy-r8q-discovery.patch"
MUSIL="$MUSIL" DTB="$DTB" "$R8Q_REPO/scripts/build-uefi.sh"
```

Before flashing, inspect the actual Android container, BootShim/FD, embedded
MsBootPolicy executable, retained Android bootstrap DTB and embedded mainline
DTB. Check the diagnostic strings inside the executable carried by the image,
not just in source or a loose build output. Check the full live PIT mapping,
image hash and BOOT capacity as described in [INSTALLATION.md](INSTALLATION.md).

This diagnostic's firmware mapping is **BOOT ID23 / UFS LU0 only**.
Existing disabled VBMETA ID66/LU3 and staged CACHE ID32/LU0 are retained.
Preserve every other PIT entry, including RECOVERY, SUPER, USERDATA,
EFS/modem calibration and duplicate-name partitions on other logical units.
Do not upload a PIT, repartition, bypass size checks or relock the bootloader.
The new image and complete mapping require review before a flash.

## Read the pages

Enter Mu's boot menu with Volume Up, then select **Internal Storage** with
the volume buttons and Side/Power. Release the buttons. Side/Power advances
the diagnostic pages; Volume Up returns to the menu without starting the
pending boot attempt. Input draining is bounded debounce; UEFI does not expose
portable physical key-release state.

The manual pages temporarily disable the volatile application watchdog so
the operator can record them. The existing kernel boot call retains its own
watchdog handling. Console/API failures abort the manual diagnostic path.

Record the protocol counts, UFS unit and block geometry, CACHE details,
filesystem/file-open statuses, file size and boot result. A fixed Internal
Storage menu entry does not prove a filesystem was found. A successful file
open does not prove `LoadImage` or the kernel succeeded. A boot result can
remain ambiguous between loader and returned application errors.

File inspection uses `EFI_FILE_MODE_READ` and `GetInfo`, with handles closed
afterward. The selected FAT driver does not dirty metadata through these
read operations, but cleanup can flush pre-existing dirty cache state and
issues a block-device flush. The added diagnostic makes no explicit file,
block, partition-table or variable write. Existing firmware driver and
boot-manager behavior still applies.

## Remove the temporary instrumentation

After collecting the results, reverse only this patch and rebuild/review the
next candidate. Leave the separate mainline DTB embedding change in place.

```bash
git -C "$MUSIL/Common/Mu" apply -R --check "$R8Q_REPO/patches/uefi/0001-msbootpolicy-r8q-discovery.patch"
git -C "$MUSIL/Common/Mu" apply -R "$R8Q_REPO/patches/uefi/0001-msbootpolicy-r8q-discovery.patch"
MUSIL="$MUSIL" DTB="$DTB" "$R8Q_REPO/scripts/build-uefi.sh"
```
