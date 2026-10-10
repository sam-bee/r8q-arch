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

Mu-Silicium contains a baseline mainline DTB exposed via `DtPlatformDxe`.
The build wrapper enables the "Device Tree"
FREEFORM block in `$MUSIL/Platforms/Samsung/r8qPkg/r8q.fdf` and copies this DTB.
Keep Mu's separate `Resources/DTBs/r8q.dtb`: that downstream Android device
tree bootstraps UEFI and must not be replaced with the mainline DTB.
The RTC configuration loads `/EFI/BOOT/R8Q-RTC.DTB` from the same ESP as the
kernel, using the built-in `dtb=` argument and EFI stub loader. Deploy that
file with every matching kernel Image. This allows Linux DT changes without
rebuilding Mu. UEFI Secure Boot must be disabled for the external DTB loader.

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

## 5. Deploy the kernel Image and DTB to the ESP

Still in mass-storage mode, use the already verified `ESP` explicitly. For an
initial empty ESP, copy and verify both files:

```bash
S20_ESP_MNT=$(mktemp -d)
sudo mount "$ESP" "$S20_ESP_MNT"
sudo mkdir -p "$S20_ESP_MNT/EFI/BOOT"
sudo cp "$OUT/arch/arm64/boot/Image" "$S20_ESP_MNT/EFI/BOOT/BOOTAA64.EFI"
sudo cp "$OUT/arch/arm64/boot/dts/qcom/sm8250-samsung-r8q.dtb" "$S20_ESP_MNT/EFI/BOOT/R8Q-RTC.DTB"
sync
sudo cmp "$OUT/arch/arm64/boot/Image" "$S20_ESP_MNT/EFI/BOOT/BOOTAA64.EFI"
sudo cmp "$OUT/arch/arm64/boot/dts/qcom/sm8250-samsung-r8q.dtb" "$S20_ESP_MNT/EFI/BOOT/R8Q-RTC.DTB"
sudo umount "$S20_ESP_MNT"
rmdir "$S20_ESP_MNT"
gsettings set org.gnome.desktop.media-handling automount "$S20_AUTOMOUNT_OLD"
gsettings set org.gnome.desktop.media-handling automount-open "$S20_AUTOMOUNT_OPEN_OLD"
```

For the first RTC update to an existing ESP, the helper retains the old EFI
kernel and refuses to overwrite existing backups or an external DTB:

```bash
ESP="$ESP" ./scripts/deploy-esp.sh "$OUT/arch/arm64/boot/Image" \
  "$OUT/arch/arm64/boot/dts/qcom/sm8250-samsung-r8q.dtb"
```

Later updates must preserve both previous files before replacing either.

## 6. Prepare the first Arch root filesystem locally

Verify the generic AArch64 archive's signature against the fingerprint on the
[Arch Linux ARM download page](https://archlinuxarm.org/about/downloads), then
pin its SHA256. The current first-boot helper creates a fresh staging tree at
`out/arch-preparation-20261009/rootdir`; it does not select a disk or write to
the phone. It needs the host's `bsdtar` and OpenSSL and runs as root to preserve
archive ownership, ACLs, and extended attributes:

```bash
pkexec /usr/bin/python3 scripts/prepare-arch-rootfs.py \
  /absolute/path/to/verified-ArchLinuxARM-aarch64.tar.gz \
  THE_VERIFIED_ARCHIVE_SHA256
```

It prepares USB NCM, local USB networking, SSH, and tty1 root autologin. The
temporary root password is `root`. Stock module trees are moved out of the
module search path, and sleep targets are masked. Optional hardware and GUI
services remain disabled until the first SSH boot works. Numeric archive
ownership is retained, including the `alarm` home directory; only top-level
root ownership and generated configuration files are normalized.

Prepare and review an ext4 `archroot` candidate for the exact USERDATA extent,
and rebuild the kernel in normal `arch` mode. Deployment **replaces USERDATA**
and updates CACHE with that kernel. Bind each write to a fresh observed Mu USB
parent and reviewed LU0/GPT/PIT mapping, use a candidate-specific one-shot
writer, and verify readback. Preserve BOOT, VBMETA, and the remaining partitions.

Do not run the legacy `scripts/install-arch.sh` for this route: its global
PARTLABEL scan does not establish the target phone or partition identity.

## 7. Boot

After both image writes and readback checks pass, exit mass storage and let the phone boot. You should see the panel show the
switch-root message, then systemd, then a root shell (autologin). On the PC an
NCM network device appears:

```bash
DEV=<the new cdc_ncm netdev>
sudo ip addr add 172.16.42.2/24 dev "$DEV"
sudo ip link set "$DEV" up
ssh root@172.16.42.1            # password: root
# After recording the first-boot results and exiting SSH:
sudo ip addr del 172.16.42.2/24 dev "$DEV"
```

## 8. USB internet and clock bootstrap

The minimal image deliberately starts with only the local USB link: phone
`usb0` is `172.16.42.1/24`, and the laptop uses `172.16.42.2/24`. On every
boot/reconnect, identify the fresh Samsung `r8q-mainline` / `r8q0001`
`cdc_ncm` device and record its current interface name and MAC. The gadget
startup script now sets fixed locally administered addresses before binding:
phone `4e:e0:a2:98:8c:90`, host `aa:dd:21:b3:df:6a`. Older installed versions
generated new addresses each boot; deploy the updated script before relying
on a persistent host MAC match.

The project laptop has NetworkManager and `dnsmasq`. The saved profile
`r8q-usb-internet` is bound to the currently verified interface and MAC,
`ipv4.method shared`, `ipv4.never-default yes`, `ipv6.method disabled`, and
`connection.autoconnect yes`. Its fixed host MAC lets NetworkManager activate
the same profile when the phone reappears. To configure it on a freshly
verified interface, or activate it for the first time:

```bash
DEV=<fresh cdc_ncm interface, after USB identity verification>
MAC=<current MAC for $DEV>
# On a new laptop, create the profile once before the modify/up commands:
# nmcli connection add type ethernet con-name r8q-usb-internet \
#   ifname "$DEV" 802-3-ethernet.mac-address "$MAC" \
#   ipv4.method shared ipv4.addresses 172.16.42.2/24 \
#   ipv4.never-default yes ipv6.method disabled connection.autoconnect yes
nmcli connection modify r8q-usb-internet \
  connection.interface-name "$DEV" 802-3-ethernet.mac-address "$MAC" \
  ipv4.method shared ipv4.addresses 172.16.42.2/24 \
  ipv4.never-default yes ipv6.method disabled connection.autoconnect yes
nmcli connection up r8q-usb-internet ifname "$DEV"
ssh root@172.16.42.1 'ping -c2 172.16.42.2'
# After the phone drop-in is reloaded, verify upstream access:
ssh root@172.16.42.1 'ping -c2 archlinux.org'
```

Verify both fixed MACs after a fresh phone boot, including the phone's
`/sys/class/net/usb0/address`. Test USB enumeration and automatic SSH access
on a restart and power-on with the cable left attached. A network profile can
activate only after the USB device enumerates; initial attachment recovery
needs a separate controller/gadget test.

If `nmcli` or `dnsmasq` is missing on the laptop, stop and ask the operator;
do not install a desktop dependency as part of this step. The phone-side
internet settings are persistent in
`/etc/systemd/network/20-usb0.network.d/50-usb-internet.conf`:

```ini
[Network]
DNS=172.16.42.2

[Route]
Gateway=172.16.42.2
Metric=1000
```

After creating or changing that drop-in, run `networkctl reload` and
`networkctl reconfigure usb0` on the phone. Preserve the existing
`/etc/resolv.conf` symlink. Verify internet and time independently; the NTP
service is already enabled:

```bash
busctl get-property org.freedesktop.timedate1 \
  /org/freedesktop/timedate1 org.freedesktop.timedate1 NTPSynchronized
timedatectl timesync-status
timedatectl show-timesync
test -e /run/systemd/timesync/synchronized
stat /var/lib/systemd/timesync/clock
curl -4 --fail --connect-timeout 5 --max-time 15 -I https://archlinuxarm.org/
```

Expect `NTPSynchronized` to return `b true`, a responding NTP server and
nonzero packet count, and HTTPS success. Compare the phone's UTC date with the
laptop's synchronised clock. The original kernel selected Mu's dummy EFI RTC
as `rtc0`; that clock returned an invalid date and broke `timedatectl show`.
The RTC configuration disables that driver and uses the PM8150 counter as
`rtc0`. Firmware protects its counter registers from writes. The upstream
`qcom,uefi-rtc-info` path adds a UTC offset without changing those registers.
Mu's EFI variable store is volatile, so `r8q-rtc.service` restores its exact
`RTCInfo` record from `/var/lib/r8q-rtc/rtcinfo.state` before binding the driver
and saves it again on shutdown. Patch 0009 flushes small pending offset changes
when the driver is unbound. Install the helper and service from the rootfs
overlay, preserve the device's machine-id guard and state, and enable the unit.

The first bootstrap requires a verified NTP date and raw PMIC counter sample
before switching to the offset DTB. It creates a 12-byte Qualcomm payload
(four-byte GPS offset plus eight reserved zero bytes), with EFI attributes 7,
and saves the hashed record on the root filesystem. This phone's bootstrap
and guarded deployment are recorded in `project-log/2026-10-09/17-native-rtc-fix.md`
at the project root. Do not reuse another device's offset. A fresh rootfs needs
its own bootstrap; `hwclock --systohc` alone cannot initialise an absent RTCInfo
variable because the driver has not yet registered.

After the initial bootstrap, verify the restored clock and normal offset API:

```bash
systemctl is-enabled r8q-rtc.service
systemctl is-active r8q-rtc.service
cat /sys/class/rtc/rtc0/name /sys/class/rtc/rtc0/hctosys
hwclock --show --utc --noadjfile --rtc=/dev/rtc0
timedatectl status
```

Verify the date after a restart and a power-off with timesyncd temporarily
masked before considering offline retention proven. Restore and enable
timesyncd afterwards. NTP also saves a timestamp for later boots; see the
[systemd-timesyncd documentation](https://github.com/systemd/systemd/blob/main/man/systemd-timesyncd.service.xml).
Future package/key bootstrap must wait for verified NTP and use a full update;
do not run an isolated `pacman -Sy` in this step.

The older `scripts/host-tether.sh` plus full-overlay route, including
`Gateway=172.16.42.14`, is a separate legacy flow and is not combined with
this saved NetworkManager sharing profile. To stop the current sharing session
while retaining the profile for future attachment:

```bash
nmcli connection down r8q-usb-internet
```

## 9. GPU acceleration (Adreno 650) + sway

Prereq: the kernel was built **with the [`patches/`](patches/) applied**
(`build_kernel.sh` does this) and its complete RTC2 module closure is installed
on the rootfs — at minimum `msm.ko` and its DRM/Qualcomm/CEC dependencies under
`/lib/modules/$KV/`.

**a) Userspace + generic firmware** (on the phone, over SSH):

```bash
pacman -S i2c-tools mesa vulkan-freedreno vulkan-tools linux-firmware-qcom sway foot grim seatd
systemctl enable --now seatd
```

That installs the phone-side `i2ctransfer` tool used by the guarded USB route
service, provides `/lib/firmware/qcom/a650_sqe.fw` and `a650_gmu.bin`, and adds
the tools used by the bounded render smoke test.

**b) The zap shader — from this phone's signed APNHLOS FAT filesystem.**
Samsung's TrustZone only authenticates a **Samsung-signed** zap; the generic
`qcom/sm8250/a650_zap.mbn` from linux-firmware is rejected (`-22`) and the GPU
then silently drops every render write. For the verified SM-G7810 TGY HZE1
stock, the source is the phone's APNHLOS filesystem (label `apnhlos`), not
`SUPER`, `vendor`, or the separate MODEM filesystem. The local HZE1 provenance
is `s20-backup/stock-HZE1/heimdall-hze1/NON-HLOS.bin`, whose
108294656-byte prefix has SHA-256
`40f5e2f7a8b8ae6158c267650908af6fd9f5e84a9ea34099720613e983a6518f`.

Do not assume a partition number on another phone. Resolve the live device by
its partition label, verify the model and FAT type, and compare the HZE1 prefix
hash before reading files. Mount it read-only:

```bash
tr -d '\0' < /proc/device-tree/model; echo
lsblk -o NAME,PATH,SIZE,TYPE,PARTLABEL,FSTYPE,MOUNTPOINTS
APNHLOS=$(readlink -f /dev/disk/by-partlabel/apnhlos)
lsblk -n -o PARTLABEL "$APNHLOS"          # want apnhlos
blkid "$APNHLOS"                         # want TYPE="vfat"
head -c 108294656 "$APNHLOS" | sha256sum  # want the HZE1 prefix hash above
mkdir -p /mnt/apnhlos
mount -o ro,nodev,nosuid,noexec "$APNHLOS" /mnt/apnhlos
find /mnt/apnhlos -type f -iname 'a650_zap.*' -print
```

The verified extraction contained the MDT and the three segments actually
present in that FAT directory. Preserve these exact four files and do not
guess a different segment count:

| Stock file | Bytes | SHA-256 |
| --- | ---: | --- |
| `a650_zap.mdt` | 6860 | `56e59374363696bac7bef2b89efc2d3d9cbb78474b4e3ef0111ebd786274d67d` |
| `a650_zap.b00` | 148 | `ec9b9d5a67456384809624b14a00d15d36297e5f2e75728504cd872bc95e0947` |
| `a650_zap.b01` | 6712 | `426cf7e5bcaf2308e0602440055486c7171b1eb340a8d76a43690dbe43dcf752` |
| `a650_zap.b02` | 1676 | `a415e5452fa8f597670a6e51010e97bfabca7d20fbce8044caed64d9d5873113` |

Install the MDT under the filename requested by the kernel, while retaining
the sibling names:

```text
/lib/firmware/qcom/sm8250/a650_zap.mbn    <- the stock a650_zap.mdt, renamed
/lib/firmware/qcom/sm8250/a650_zap.b00
/lib/firmware/qcom/sm8250/a650_zap.b01
/lib/firmware/qcom/sm8250/a650_zap.b02
```

Copy the four files from the path printed by `find`, then unmount the source:

```bash
umount /mnt/apnhlos
```

**c) Ordered driver startup.** Install the exact RTC2 module closure separately.
The [`rootfs/`](rootfs/) overlay supplies these load controls:

- `etc/modprobe.d/r8q-gpu.conf` — blacklists `msm` and its DRM/Qualcomm
  dependency aliases so udev cannot coldplug a partial closure, plus
  `options msm separate_gpu_kms=1 r8q_zap_dyn=1 r8q_zap_secvid=0`.
  `r8q_zap_dyn=1` is **required**: it loads the zap into dynamically allocated
  RAM; pointing it at the DT carveout makes Samsung's TZ **hard-reset the SoC**.
- `etc/systemd/system/r8q-gpu.service` — has `Requires=` and `After=` on the
  USB route service and an active-state `ExecStartPre` guard, then explicitly
  loads `msm` with the three required parameters. Do not add an
  `After=multi-user.target` edge; that creates a display/startup cycle.
- `root/.bash_profile` — tty1 autologin waits for `renderD128`, then starts
  **sway** with the vulkan (turnip) renderer: render node `renderD128`,
  scanout on simpledrm `card0`.

Start the service manually for the first validation boot. Enable it for future
boots only after the rendering smoke test below passes:

```bash
systemctl start r8q-gpu.service
```

**d) Verify actual hardware rendering before enabling the service.** A render
node or `vulkaninfo` alone is not proof: require a compositor to submit a real
Wayland client surface and capture the resulting image. From a user session
(UID 1000), run a short headless Sway smoke test using the Adreno render node:

```bash
export XDG_RUNTIME_DIR=/run/user/1000
unset WAYLAND_DISPLAY DISPLAY
export WLR_BACKENDS=headless
export WLR_HEADLESS_OUTPUTS=1
export WLR_RENDERER=vulkan
export WLR_RENDER_DRM_DEVICE=/dev/dri/renderD128
export LIBSEAT_BACKEND=seatd
sway -d 2>/tmp/r8q-sway-gpu-smoke.log
```

Sway chooses its own Wayland socket. In another shell for the same user, set
`XDG_RUNTIME_DIR` to the same directory and `WAYLAND_DISPLAY` to the socket
reported by `Running compositor on wayland display` in that Sway log. Then
create a client surface and capture it:

```bash
foot --title r8q-gpu-smoke sh -c \
  'printf "R8Q Adreno 650 GPU surface\n"; sleep 20' &
sleep 2
grim -t png /tmp/r8q-gpu-smoke.png
file /tmp/r8q-gpu-smoke.png
grep -Ei 'vulkan|turnip|FD650|Adreno|renderD128|llvmpipe|softpipe|pixman|software|failed|error' \
  /tmp/r8q-sway-gpu-smoke.log
```

Pass requires Sway to report the Turnip/Adreno 650 renderer on `renderD128`,
no software renderer or zap-auth failure, and `grim` to produce a valid PNG
containing the client surface. After this headless proof, a separate DRM-mode
session may validate the split pairing by setting
`WLR_BACKENDS=drm,libinput`, `WLR_DRM_DEVICES=/dev/dri/card0`, and retaining
`WLR_RENDER_DRM_DEVICE=/dev/dri/renderD128`; this is the panel check and is
not implied by the headless result.

The bounded panel smoke test has passed on the current phone: the DRM backend
selected simpledrm at 1080x2400 on `DSI-1` for scanout, Turnip used the Adreno
render node, and real `foot` plus Vulkan-cube client surfaces were captured as
PNG files and visually checked. `vkcube` completed 1800 frames with exit status
0. This establishes the split rendering path for the tested run; it is not a
long-soak result. After a reboot with GPU/touch startup enabled, the render
smoke test passed again and Sway's libinput backend recognized the Zinitix
touchscreen with events enabled. Physical tap coordinates remain untested.
`vulkaninfo --summary` currently fails while querying `VK_KHR_display`; the
Sway/Turnip and Vulkan-cube rendering tests succeed despite that display-query
failure. GPU and touch services now start automatically after USB recovery.

Only after the proof succeeds:

```bash
systemctl enable r8q-gpu.service
```

```bash
ssh root@172.16.42.1 'ls /dev/dri; dmesg | grep -Ei "zap|adreno|render"'
```

Do not claim panel success from the headless test. Rules of the road: **never
`rmmod msm`** (GMU/IOMMU teardown wedges the kernel — load once per boot), and
never write the SECVID registers from the kernel (the hypervisor traps them;
that is what `r8q_zap_secvid=0` keeps disabled).

## 10. Wi-Fi (QCA6390 over PCIe)

No kernel config changes are needed — ATH11K(+PCI), MHI, QRTR, `PCIE_QCOM`,
`PCI_PWRCTRL_PWRSEQ` and `POWER_SEQUENCING_QCOM_WCN` are all in `arm64`
defconfig. The DT nodes are in [`dts/`](dts/) and the firmware comes from
`linux-firmware`.

On the minimal RTC2 image, install only the following Wi-Fi policy files from
the overlay, before adding modules or starting NetworkManager. Run these on the
phone after transferring those files; the existing verified USB route unit and
its pinned GPI/GENI modules must already be in place.

```bash
install -Dm644 rootfs/etc/modprobe.d/r8q-wifi-blacklist.conf /etc/modprobe.d/r8q-wifi-blacklist.conf
install -Dm644 rootfs/etc/systemd/system/r8q-wifi.service /etc/systemd/system/r8q-wifi.service
install -Dm755 rootfs/usr/local/sbin/r8q-wifi-up.sh /usr/local/sbin/r8q-wifi-up.sh
install -Dm644 rootfs/etc/systemd/system/NetworkManager.service.d/10-r8q-usb-route.conf \
  /etc/systemd/system/NetworkManager.service.d/10-r8q-usb-route.conf
install -Dm644 rootfs/etc/NetworkManager/conf.d/10-r8q.conf /etc/NetworkManager/conf.d/10-r8q.conf
systemctl daemon-reload
```

**a) Modules and firmware on the phone.** Install the Wi-Fi dependency closure
under `/lib/modules/$(uname -r)/`, with matching kernel config, exports and
vermagic, and run `depmod -a`. Do not replace the pinned GPI/GENI modules or add
the battery driver for this step. One dependency is easy to miss:

```bash
ssh root@172.16.42.1 'ls /lib/firmware/ath11k/QCA6390/hw2.0/'   # amss.bin board-2.bin m3.bin
ssh root@172.16.42.1 'modinfo qrtr-mhi | head -2'               # MUST be present
```

If `qrtr-mhi.ko` is missing, install it and re-run `depmod -a`. Without it
nothing binds to the MHI `IPCR` channel, QMI never starts, and ath11k stops
dead at `Wait for device to enter SBL or Mission mode` with no further output —
which looks like a firmware failure but is not one.

For the minimal `7.1.2-r8q-rtc2` image, complete a full package upgrade before
adding NetworkManager, `iw`, or `wireless-regdb`. This kernel lacks Landlock, so
the verified phone bootstrap used one temporary pacman configuration under
`/run` while retaining package signature checks; `/etc/pacman.conf` stayed
unchanged. Keep this workaround phone-specific and do not install a blanket
legacy overlay.

**b) Overlay + service.** The [`rootfs/`](rootfs/) overlay ships:

- `etc/modprobe.d/r8q-wifi-blacklist.conf` — keeps udev from coldplugging the
  Wi-Fi stack at ~9 s. The USB route service already owns the GPI/GENI bring-up;
  this Wi-Fi unit therefore has no battery or touch dependency.
- `etc/systemd/system/r8q-wifi.service` — requires the completed
  `r8q-usb-route.service` and checks it is active before loading, in order:
  `phy-qcom-qmp-pcie` (the PCIe **phy is a module**; without it `1c00000.pcie`
  silently defers) → `pwrseq-qcom-wcn` → `pci-pwrctrl-pwrseq` → bounded wait for
  the discovered endpoint → `qrtr-mhi` → `ath11k_pci` → bounded wait for an
  endpoint-associated PHY. It does not assume a fixed BDF or PHY name.
- `etc/systemd/system/NetworkManager.service.d/10-r8q-usb-route.conf` — holds
  NetworkManager behind the same route guard, so its `nl80211` probe cannot
  autoload `cfg80211`/`rfkill` first. The blacklist includes those modules.
- `etc/NetworkManager/conf.d/10-r8q.conf` — see (c).

```bash
ssh root@172.16.42.1 'systemctl enable --now r8q-wifi.service'
ssh root@172.16.42.1 'dmesg | grep ath11k'   # want: fw_version ..., "renamed from wlan0"
```

**c) NetworkManager, so you can connect from the GNOME UI.** Install it *before*
starting it, and put the config in place first — the config is what keeps NM off
`usb0`, and `usb0` is the SSH connection you are typing over:

```bash
pacman -Syu --needed networkmanager iw wireless-regdb
install -Dm644 rootfs/etc/NetworkManager/conf.d/10-r8q.conf \
               /etc/NetworkManager/conf.d/10-r8q.conf   # usb0 unmanaged, resolved DNS
systemctl enable --now NetworkManager
systemctl disable NetworkManager-wait-online.service    # else it stalls boot
nmcli device status      # want: wlp1s0 managed, usb0 "unmanaged"
```

The drop-in sets `dns=systemd-resolved`, leaves `usb0` with networkd, and sends
Wi-Fi DHCP DNS to resolved. Wi-Fi connections use route metric 50 versus the
USB fallback's 1000. It deliberately disables NetworkManager's connectivity
probe: a failed external probe previously added 20000 to the Wi-Fi metric and
kept USB preferred despite successful association. `wifi.cloned-mac-address=stable`
gives the QCA6390 a stable per-profile address even though this phone reports
`board_id 0xff` and no calibration address. `wifi.powersave=2` keeps incoming
SSH responsive during hardware bring-up.

Package gotchas:

- If `nmcli` dies with `libnm.so.0: version 'libnm_1_xx_0' not found`, you did a
  partial upgrade (`pacman -Sy networkmanager` against an older `libnm`). Fix with
  a complete `pacman -Syu`. The daemon runs regardless, but every client — `nmcli`,
  gnome-control-center, the GNOME shell menu — is broken until the versions match.
- On the current RTC2 image, the full upgrade was completed with a temporary
  `/run` pacman configuration because the phone kernel lacks Landlock. Keep the
  default `/etc/pacman.conf` unchanged; do not turn the temporary workaround
  into a persistent global overlay.
- Do package installs over a transient link with
  `systemd-run --unit=install --collect pacman -S ...` so an SSH drop cannot
  abort the transaction half-way.

Then join a network from **Settings → Wi-Fi** on the phone itself, or over SSH:

```bash
nmcli device wifi list
nmcli device wifi connect 'YOUR-SSID' password 'YOUR-PASSPHRASE'
```

NM stores the connection in `/etc/NetworkManager/system-connections/` for
automatic reconnection. The current RTC2 run recovered USB automatically on one
USB-only baseline boot and two consecutive Wi-Fi-enabled reboots. Both wireless
boots associated, obtained DHCP, and passed Wi-Fi-bound DNS, ping and HTTPS
checks; `usb0` remained unmanaged. Wireless key SSH passed separately.
The initial failed boot had loaded `cfg80211` before the strict USB route
wrapper; the deployed NM gate and full alias blacklist prevent that race.
Longer soak, power-removal and suspend remain untested.

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
this in the `[options]` section of `/etc/pacman.conf` once:

```
NoUpgrade = usr/lib/firmware/qcom/sm8250/a650_zap.mbn usr/lib/firmware/qcom/sm8250/a650_zap.b00 usr/lib/firmware/qcom/sm8250/a650_zap.b01 usr/lib/firmware/qcom/sm8250/a650_zap.b02
```

pacman will drop the upstream file as `.pacnew` instead. Verify at any time with
`sha256sum /usr/lib/firmware/qcom/sm8250/a650_zap.*` against your saved copy.

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
