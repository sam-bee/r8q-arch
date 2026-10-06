# Installation

This gets you a booting **Arch Linux ARM** on the r8q, reachable from your PC
over the USB cable (SSH + internet). Read [`PREREQUISITES.md`](PREREQUISITES.md)
first — **this wipes `userdata`.**

Throughout: `$KSRC` = your mainline kernel source, `$OUT` = its build dir
(`O=`), `$MUSIL` = your Mu-Silicium checkout. `KV` is the kernel release (e.g.
`7.1.2`).

---

## 1. Build the kernel (Image + DTB)

Drop the two device-tree files from [`dts/`](dts/) into
`$KSRC/arch/arm64/boot/dts/qcom/` (they carry the display fix).
`build_kernel.sh` also applies the kernel patches from [`patches/`](patches/)
(required for GPU acceleration later — harmless otherwise). Then:

```bash
# arm64 defconfig + our fragment, LLVM=1, bring-up drivers built-in
KSRC=... OUT=... ./scripts/build_kernel.sh
```

For the first kernel test, use `R8Q_BOOT_MODE=debug` with that command. It
embeds `r8q.debug=1` in the forced command line, skips mounting `userdata`,
and starts the initramfs USB NCM/telnet diagnostic path. Rebuild with the
default `R8Q_BOOT_MODE=arch` when the Arch root filesystem is ready.

The kernel is built with:
- an **embedded switch-root initramfs** from [`initramfs/`](initramfs/)
  (`CONFIG_INITRAMFS_SOURCE` = the dir with `init` + `irfs.devnodes`; you also
  need a static aarch64 busybox in `bin/busybox`),
- **`CONFIG_CMDLINE_FORCE`** set to the string in
  [`config/cmdline.txt`](config/cmdline.txt) (the phone has no keyboard, so the
  cmdline is baked in). Keep `simpledrm` **enabled**.

Outputs: `$OUT/arch/arm64/boot/Image` and
`$OUT/arch/arm64/boot/dts/qcom/sm8250-samsung-r8q.dtb`.

## 2. Embed the DTB and build UEFI

The mainline DTB lives **inside the firmware** (Mu-Silicium exposes it to the
kernel via `DtPlatformDxe`). The build wrapper enables the "Device Tree"
FREEFORM block in `$MUSIL/Platforms/Samsung/r8qPkg/r8q.fdf` and copies this DTB.
Keep Mu's separate `Resources/DTBs/r8q.dtb`: that downstream Android device
tree bootstraps UEFI and must not be replaced with the mainline DTB.

```bash
MUSIL=$MUSIL DTB=$OUT/arch/arm64/boot/dts/qcom/sm8250-samsung-r8q.dtb ./scripts/build-uefi.sh
# -> $MUSIL/Mu-r8q.img (current single-model r8q target)
```

If Mu starts but cannot discover the staged EFI kernel, the temporary
[UEFI discovery diagnostic](UEFI-DIAGNOSTICS.md) can report runtime protocol,
file-access and boot statuses before changing the partition layout.

## 3. Flash UEFI to BOOT

Put the phone in **download mode** (power off; VolUp+VolDown; plug USB):

Review the actual image, live PIT and complete selected partition mapping
before flashing. The legacy `scripts/flash.sh` uses implicit tool/partition
names; use an explicitly selected Heimdall binary, numeric PIT IDs and a live
PIT guard. On the reviewed SM-G7810 TGY layout, BOOT is ID23 on LU0 and
VBMETA is ID66 on LU3. VBMETA_SAMSUNG is a separate ID27 on LU0.

Flash the reviewed Mu Android boot container to BOOT, with the reviewed
verification-disabled image to VBMETA when required. The kernel `Image` goes
on CACHE's FAT filesystem in the next steps. Keep stock RECOVERY and SUPER,
and do not upload a PIT or repartition for this route. A successful
`--no-reboot` PIT read leaves a session requiring `--resume`; a freshly
entered Download Mode needs a new handshake. Generate the command from the
reviewed mapping and current session state rather than copying a previous run.

The phone now boots Mu-Silicium UEFI on every power-on.

## 4. Prepare the ESP (once)

Boot the phone into Mu-Silicium **mass-storage** mode by pressing Volume Up
during the three-second boot-manager timeout and selecting **Mass Storage**.
This menu path is supported by the pinned Mu source, but the actual option
presentation and exported handles still need to be confirmed on the SM-G7810.
Mu mass storage has no source-visible CACHE-only or read-only guarantee; its
opaque USB driver may expose whole UFS-LU0 candidates. Treat the exported disk
as write-capable.

Before starting Mu or selecting Mass Storage, temporarily prevent GNOME from
automounting exported partitions. Save both settings and restore them after
unmounting the phone's filesystems:

```bash
S20_AUTOMOUNT_OLD=$(gsettings get org.gnome.desktop.media-handling automount)
S20_AUTOMOUNT_OPEN_OLD=$(gsettings get org.gnome.desktop.media-handling automount-open)
gsettings set org.gnome.desktop.media-handling automount false
gsettings set org.gnome.desktop.media-handling automount-open false
```

After Mass Storage appears, identify the USB physical parent and UFS disk, then
review the exact partition label, start offset, logical sector size, and
capacity against a fresh PIT. Do not select a partition by scanning every
desktop block device for `PARTLABEL=cache`. For the reviewed SM-G7810 TGY
layout only, CACHE is ID32/LU0 with start offset `12013535232` bytes and
capacity `629145600` bytes; do not generalize those values to another model or
PIT. Set `ESP` only after that review:

```bash
lsblk -o NAME,PATH,TYPE,TRAN,PKNAME,SIZE,PARTLABEL,START,LOG-SEC,PHY-SEC,FSTYPE,MOUNTPOINTS
ESP='/dev/REPLACE_WITH_VERIFIED_CACHE_PARTITION'
test -b "$ESP"
udevadm info --query=path --name="$ESP"   # must belong to the phone's USB parent
cat "/sys/class/block/${ESP##*/}/start"  # kernel sectors of 512 bytes; multiply by 512
sudo blockdev --getss "$ESP"       # must match the reviewed logical 4096-byte sector
sudo blockdev --getsize64 "$ESP"   # must match the reviewed CACHE capacity
```

Stop if the placeholder remains or any check disagrees with the reviewed PIT.
For the layout above, the kernel start value is `23463936` in 512-byte units;
that is separate from the device's 4096-byte logical sector size.

During SM-G7810 TGY bring-up, the raw FAT CACHE transfer through Samsung Download
Mode failed. The sparse stock CACHE restore succeeded. Stage the FAT ESP through
Mu mass storage after verifying its runtime mapping. Reformat only the verified
CACHE partition (UFS logical block is 4096):

```bash
sudo mkfs.vfat -F 32 -S 4096 -n R8QESP "$ESP"
```

## 5. Deploy the kernel Image to the ESP

Still in mass-storage mode, use the already verified `ESP` explicitly. The
legacy `scripts/deploy-esp.sh` performs an unguarded global PARTLABEL scan, so
do not run it for this flow:

```bash
S20_ESP_MNT=$(mktemp -d)
sudo mount "$ESP" "$S20_ESP_MNT"
sudo mkdir -p "$S20_ESP_MNT/EFI/BOOT"
sudo cp "$OUT/arch/arm64/boot/Image" "$S20_ESP_MNT/EFI/BOOT/BOOTAA64.EFI"
sync
sudo cmp "$OUT/arch/arm64/boot/Image" "$S20_ESP_MNT/EFI/BOOT/BOOTAA64.EFI"
sudo umount "$S20_ESP_MNT"
rmdir "$S20_ESP_MNT"
gsettings set org.gnome.desktop.media-handling automount "$S20_AUTOMOUNT_OLD"
gsettings set org.gnome.desktop.media-handling automount-open "$S20_AUTOMOUNT_OPEN_OLD"
```

## 6. Install Arch onto userdata

Still in mass-storage mode (this **formats userdata**):

```bash
KV=7.1.2 OUT=$OUT KSRC=$KSRC ./scripts/install-arch.sh
```

It extracts Arch Linux ARM, **moves the kernel module tree aside** (cold-plugging
the full tree hard-resets the SoC — see the note in the script), lays down our
[`rootfs/`](rootfs/) overlay, enables `sshd` + `systemd-networkd` +
`r8q-usb-gadget`, sets root autologin on `tty1`, root password `root`, and
disables the pacman sandbox (our kernel has no Landlock).

## 7. Boot

Exit mass storage and let the phone boot. You should see the panel show the
switch-root message, then systemd, then a root shell (autologin). On the PC an
NCM network device appears:

```bash
DEV=<the new cdc_ncm netdev>
sudo ip addr add 172.16.42.14/24 dev "$DEV"; sudo ip link set "$DEV" up
ssh root@172.16.42.1            # password: root
```

## 8. USB tethering (internet + pacman)

Share the PC's internet to the phone (host NAT is runtime — re-run after a PC
reboot):

```bash
./scripts/host-tether.sh        # enables ip_forward + MASQUERADE for 172.16.42.0/24
```

The phone already has `Gateway=172.16.42.14` + DNS baked into
`rootfs/etc/systemd/network/20-usb0.network`, so once the host NAT is up:

```bash
ssh root@172.16.42.1 'ping -c2 archlinux.org'
# first pacman use on a fresh rootfs:
ssh root@172.16.42.1 'pacman-key --init && pacman-key --populate archlinuxarm && pacman -Sy'
```

## 9. GPU acceleration (Adreno 650) + sway

Prereq: the kernel was built **with the [`patches/`](patches/) applied**
(`build_kernel.sh` does this) and its modules are installed on the rootfs —
at minimum `msm.ko` and its dependencies under `/lib/modules/$KV/`.

**a) Userspace + generic firmware** (on the phone, over SSH):

```bash
pacman -S mesa vulkan-freedreno linux-firmware-qcom sway foot seatd
systemctl enable --now seatd
```

That provides `/lib/firmware/qcom/a650_sqe.fw` and `a650_gmu.bin`.

**b) The zap shader — from YOUR device's stock firmware.** Samsung's TrustZone
only authenticates a **Samsung-signed** zap; the generic
`qcom/sm8250/a650_zap.mbn` from linux-firmware is rejected (`-22`) and the GPU
then silently drops every render write. Get the stock firmware for your model
(e.g. the AP tarball from samfw/frija), pull `a650_zap.mdt` + `a650_zap.b00/.b01/.b02`
out of the `vendor` image (`/vendor/firmware/`), and install them as:

```
/lib/firmware/qcom/sm8250/a650_zap.mbn    <- the stock a650_zap.mdt, renamed
/lib/firmware/qcom/sm8250/a650_zap.b00
/lib/firmware/qcom/sm8250/a650_zap.b01
/lib/firmware/qcom/sm8250/a650_zap.b02
```

**c) Module options + post-boot load.** The [`rootfs/`](rootfs/) overlay ships
these (already in place if you re-ran the overlay):

- `etc/modprobe.d/r8q-gpu.conf` — `blacklist msm` **plus**
  `options msm separate_gpu_kms=1 r8q_zap_dyn=1 r8q_zap_secvid=0`.
  `r8q_zap_dyn=1` is **required**: it loads the zap into dynamically allocated
  RAM; pointing it at the DT carveout makes Samsung's TZ **hard-reset the SoC**.
- `etc/systemd/system/r8q-gpu.service` — loads `msm` after `multi-user.target`
  (never let udev coldplug it). `systemctl enable r8q-gpu.service`.
- `root/.bash_profile` — tty1 autologin waits for `renderD128`, then starts
  **sway** with the vulkan (turnip) renderer: render node `renderD128`,
  scanout on simpledrm `card0`.

**d) Verify** (after a reboot):

```bash
ssh root@172.16.42.1 'ls /dev/dri; dmesg | grep -i zap'
# want: renderD128 present, "r8q: zap region dma_alloc'd at ..." and NO "zap auth failed"
```

Sway should be on the panel. Rules of the road: **never `rmmod msm`** (GMU/IOMMU
teardown wedges the kernel — load once per boot), and never write the SECVID
registers from the kernel (the hypervisor traps them; that is what
`r8q_zap_secvid=0` keeps disabled).

## 10. Wi-Fi (QCA6390 over PCIe)

No kernel config changes are needed — ATH11K(+PCI), MHI, QRTR, `PCIE_QCOM`,
`PCI_PWRCTRL_PWRSEQ` and `POWER_SEQUENCING_QCOM_WCN` are all in `arm64`
defconfig. The DT nodes are in [`dts/`](dts/) and the firmware comes from
`linux-firmware`.

**a) Modules and firmware on the phone.** `make modules_install` must have put
these under `/lib/modules/$KV/`, and one of them is easy to miss:

```bash
ssh root@172.16.42.1 'ls /lib/firmware/ath11k/QCA6390/hw2.0/'   # amss.bin board-2.bin m3.bin
ssh root@172.16.42.1 'modinfo qrtr-mhi | head -2'               # MUST be present
```

If `qrtr-mhi.ko` is missing, install it and re-run `depmod -a`. Without it
nothing binds to the MHI `IPCR` channel, QMI never starts, and ath11k stops
dead at `Wait for device to enter SBL or Mission mode` with no further output —
which looks like a firmware failure but is not one.

**b) Overlay + service.** The [`rootfs/`](rootfs/) overlay ships:

- `etc/modprobe.d/r8q-wifi-blacklist.conf` — keeps udev from coldplugging the
  Wi-Fi stack at ~9 s, which races the touch/battery geni bring-up (SE0 i2c
  timeouts + MAX77705 IRQ storms).
- `etc/systemd/system/r8q-wifi.service` — loads it deliberately instead, in
  order: `phy-qcom-qmp-pcie` (the PCIe **phy is a module**; without it
  `1c00000.pcie` silently defers) → `pwrseq-qcom-wcn` → `pci-pwrctrl-pwrseq` →
  wait for the endpoint → `qrtr-mhi` → `ath11k_pci`.
- `etc/NetworkManager/conf.d/10-r8q.conf` — see (c).

```bash
ssh root@172.16.42.1 'systemctl enable --now r8q-wifi.service'
ssh root@172.16.42.1 'dmesg | grep ath11k'   # want: fw_version ..., "renamed from wlan0"
```

**c) NetworkManager, so you can connect from the GNOME UI.** Install it *before*
starting it, and put the config in place first — the config is what keeps NM off
`usb0`, and `usb0` is the SSH connection you are typing over:

```bash
pacman -S networkmanager wireless-regdb
install -Dm644 rootfs/etc/NetworkManager/conf.d/10-r8q.conf \
               /etc/NetworkManager/conf.d/10-r8q.conf   # usb0 unmanaged, dns=none
systemctl enable --now NetworkManager
systemctl disable NetworkManager-wait-online.service    # else it stalls boot
nmcli device status      # want: wlp1s0 managed, usb0 "unmanaged"
```

Two gotchas:

- If `nmcli` dies with `libnm.so.0: version 'libnm_1_xx_0' not found`, you did a
  partial upgrade (`pacman -Sy networkmanager` against an older `libnm`). Fix with
  `pacman -S libnm`. The daemon runs regardless, but every client — `nmcli`,
  gnome-control-center, the GNOME shell menu — is broken until the versions match.
- Do package installs over a transient link with
  `systemd-run --unit=install --collect pacman -S ...` so an SSH drop cannot
  abort the transaction half-way.

Then join a network from **Settings → Wi-Fi** on the phone itself, or over SSH:

```bash
nmcli device wifi list
nmcli device wifi connect 'YOUR-SSID' password 'YOUR-PASSPHRASE'
```

NM stores the connection in `/etc/NetworkManager/system-connections/`, so it
reconnects on its own after a reboot.

**Debugging note.** If MHI ever stalls again, build `mhi.ko` with
`CONFIG_MHI_BUS_DEBUG=y` and read `/sys/kernel/debug/mhi/*/regdump`. It prints
`BHI_EXECENV` / `BHI_STATUS` / `BHI_ERRCODE` / `BHI_ERRDBG1-3` — PBL's own
verdict on the firmware. `BHI_EXECENV: 0x2` means the chip is already in mission
mode and the fault is above MHI, not in the firmware.

---

## 11. The CPU-wedge workaround (do this before running any desktop)

Without this the phone stops dead under load. It is **not** a display or GPU
fault: **a core enters idle and never comes back out.** RCU reports it plainly,
printing that CPU with an **even** dynticks counter
(`idle=…/1/0x4000000000000000`), i.e. it believes the core is idle, and the same
frozen values are still there in every stall report minutes later. Everything
that needs a global IPI then blocks behind it — which is why the visible
backtraces are usually innocent victims in `kick_all_cpus_sync ← __text_poke`.

The tell is unmistakable once you know it: **the kernel keeps answering ICMP
while userspace stops entirely** — `ping` stays at ~2 ms while `sshd` cannot even
emit its version banner (`Connection timed out during banner exchange`). It
usually degrades to a full hang after that; recovery is the physical VolUp+Power
combo either way.

**a) Disable the deep idle state on every core.** This is a mitigation, not a
cure: cores have been lost with it applied. It does make the failure much rarer,
because power collapse fails far more often than plain WFI does.

```bash
install -Dm644 rootfs/etc/tmpfiles.d/50-r8q-cpuidle.conf \
               /etc/tmpfiles.d/50-r8q-cpuidle.conf
systemd-tmpfiles --create /etc/tmpfiles.d/50-r8q-cpuidle.conf

# verify: no core power-collapses any more
for c in 0 1 2 3 4 5 6 7; do echo -n "cpu$c=$(cat /sys/devices/system/cpu/cpu$c/cpuidle/state1/disable) "; done; echo
#   want: all 1
```

**b) For heavy work, stop the cores idling at all.** What actually correlates
with the wedge is idle-entry rate, not utilisation: a compile idles the cores
~500×/s and kills the phone within a minute, while an 8-core spin loop at 85 °C
runs indefinitely. A `SCHED_IDLE` spinner pinned to each core keeps the idle loop
from ever being entered and costs real work nothing, because SCHED_IDLE only runs
when a CPU would otherwise have had nothing to do.

```bash
install -Dm755 rootfs/usr/local/sbin/r8q-noidle.sh /usr/local/sbin/r8q-noidle.sh
install -Dm644 rootfs/etc/systemd/system/r8q-noidle.service \
               /etc/systemd/system/r8q-noidle.service
systemctl daemon-reload

# around anything heavy (a Rust build will not survive without it):
systemctl start r8q-noidle
cd ~/paru && makepkg -si
systemctl stop r8q-noidle
```

It is deliberately not enabled at boot: no core ever sleeps while it runs. The
in-kernel equivalent, if you would rather pay that permanently, is `nohlt` on the
cmdline — that needs an `Image` rebuild, since `CONFIG_CMDLINE_FORCE=y`.

## 12. KDE Plasma Mobile

```bash
systemd-run --unit=install --collect pacman -S plasma-mobile plasma-settings kscreen sddm
```

**a) Stop PowerDevil from suspending — do this BEFORE the first login.** Suspend
is a hard reset on this device (see the sleep-target masking earlier), and
PowerDevil will happily idle-suspend into it.

```bash
for f in powerdevilrc powermanagementprofilesrc kscreenlockerrc; do
  install -Dm644 rootfs/etc/xdg/$f /etc/xdg/$f
done
```

`powermanagementprofilesrc` deliberately omits the `[*][SuspendSession]` group in
every profile, `powerdevilrc` sets `BatteryCriticalAction=0` (the fuel gauge reads
critical while the pack is fine), and `kscreenlockerrc` disables auto-locking —
with autologin and no hardware keyboard, a lock screen is an easy way to lock
yourself out of the panel. These live in `/etc/xdg` safely:
`plasma-mobile-envmanager` only generates `~/.config/plasma-mobile/{kwinrc,
kdeglobals,ksmserverrc}` and never touches them.

**b) sddm.** There is no Xorg on this device at all, and sddm still defaults its
Wayland greeter to weston, so both settings are required:

```bash
install -Dm644 rootfs/etc/sddm.conf.d/10-r8q.conf /etc/sddm.conf.d/10-r8q.conf
install -Dm644 rootfs/etc/systemd/system/sddm.service.d/r8q-after-gpu.conf \
               /etc/systemd/system/sddm.service.d/r8q-after-gpu.conf
systemctl daemon-reload
systemctl disable gdm && systemctl enable sddm
```

The `r8q-after-gpu.conf` drop-in is load-bearing: KWin picks its render device
once at startup, so if sddm beats `r8q-gpu.service` the session silently runs on
llvmpipe.

**c) Verify it got the GPU.**

```bash
ls -l /proc/$(pgrep -x kwin_wayland)/fd | grep -o '/dev/dri/[a-zA-Z0-9]*' | sort | uniq -c
#   want: 3 /dev/dri/card0   and   8 /dev/dri/renderD128
```

KWin needs no GPU configuration of its own — do **not** port GNOME's
`mutter-device-preferred-primary` udev tag or `MUTTER_DEBUG_MULTI_GPU_FORCE_COPY_MODE`
across. It has a real split display/render-device concept, treats every
`DRM_BUS_PLATFORM` node as compatible and prefers the non-software renderer, and
both of ours are platform-bus. If it ever guesses wrong, force it with
`KWIN_RENDER_NODES=/dev/dri/renderD128`.

Scale is automatic — KWin's phone-panel DPI heuristic yields **2.7** (logical
400x889) for this display, but only because `patches/0006` makes the connector
DSI and the DT carries `width-mm`/`height-mm`. Check with `kscreen-doctor -o`,
which needs `WAYLAND_DISPLAY=wayland-0` in addition to the usual
`XDG_RUNTIME_DIR` / `DBUS_SESSION_BUS_ADDRESS`.

GNOME stays installed; revert with `systemctl disable sddm && systemctl enable gdm`.

## Protect the Samsung zap shader from pacman

`/usr/lib/firmware/qcom/sm8250/a650_zap.mbn` is **owned by `linux-firmware-qcom`**,
and step 9 overwrote it with your Samsung-signed blob. Any upgrade of that package
silently restores the upstream file and the GPU then hangs on its first submit. Add
this to `/etc/pacman.conf` once:

```
NoUpgrade = usr/lib/firmware/qcom/sm8250/a650_zap.mbn
```

pacman will drop the upstream file as `.pacnew` instead. Verify at any time with
`md5sum /usr/lib/firmware/qcom/sm8250/a650_zap.mbn` against your saved copy.

Two more things that bite on a fresh ALARM rootfs:

- `/` and `/usr` may be owned by `alarm` (a tarball-extraction artifact, same as
  `/etc`). `systemd-tmpfiles` then fails during package installs with
  `Detected unsafe path transition / (owned by alarm) → /dev`. Fix once with
  `chown root:root / /usr && chmod 755 /`.
- **Reboot behavior needs to be tested on your device.** This installation
  route places Mu-Silicium in `BOOT` and retains stock `RECOVERY`. On this
  route ordinary power-on selects UEFI; VolUp+Power with USB connected selects
  stock recovery. Do not assume a RECOVERY-based installation when debugging
  the reboot path.
