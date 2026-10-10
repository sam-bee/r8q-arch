#!/bin/sh
# Bounded runtime helpers for the deliberately ordered QCA6390 bring-up.
set -eu

SYSFS_ROOT=${R8Q_WIFI_SYSFS_ROOT:-/sys}
ENDPOINT_TRIES=${R8Q_WIFI_ENDPOINT_TRIES:-200}
PHY_TRIES=${R8Q_WIFI_PHY_TRIES:-300}
SLEEP_BIN=${R8Q_WIFI_SLEEP_BIN:-/usr/bin/sleep}
LOGGER_BIN=${R8Q_WIFI_LOGGER_BIN:-/usr/bin/logger}
PCI_VENDOR=${R8Q_WIFI_PCI_VENDOR:-0x17cb}
PCI_DEVICE=${R8Q_WIFI_PCI_DEVICE:-0x1101}

log() {
    "$LOGGER_BIN" -t r8q-wifi -- "$*" 2>/dev/null || :
}

die() {
    echo "r8q-wifi: $*" >&2
    log "ERROR: $*"
    exit 1
}

find_endpoint() {
    for path in "$SYSFS_ROOT"/bus/pci/devices/*; do
        test -f "$path/vendor" || continue
        test -f "$path/device" || continue
        vendor=$(tr -d '\r\n' < "$path/vendor") || continue
        device=$(tr -d '\r\n' < "$path/device") || continue
        test "$vendor:$device" = "$PCI_VENDOR:$PCI_DEVICE" || continue
        printf '%s\n' "${path##*/}"
        return 0
    done
    return 1
}

find_phy() {
    endpoint=$1
    for path in "$SYSFS_ROOT"/class/ieee80211/phy*; do
        test -e "$path" || continue
        test -e "$path/device" || continue
        phy_device=$(readlink -f "$path/device" 2>/dev/null || :)
        case "$phy_device" in
            */$endpoint|*/$endpoint/*) ;;
            *) continue ;;
        esac
        printf '%s\n' "${path##*/}"
        return 0
    done
    return 1
}

wait_endpoint() {
    i=0
    while test "$i" -lt "$ENDPOINT_TRIES"; do
        endpoint=$(find_endpoint 2>/dev/null || :)
        if test -n "$endpoint"; then
            log "QCA6390 endpoint=$endpoint"
            return 0
        fi
        i=$((i + 1))
        "$SLEEP_BIN" 0.1
    done
    die "QCA6390 PCI endpoint did not enumerate within ${ENDPOINT_TRIES} attempts"
}

wait_phy() {
    i=0
    while test "$i" -lt "$PHY_TRIES"; do
        endpoint=$(find_endpoint 2>/dev/null || :)
        phy=
        test -n "$endpoint" && phy=$(find_phy "$endpoint" 2>/dev/null || :)
        if test -n "$phy"; then
            log "ath11k registered $phy"
            return 0
        fi
        i=$((i + 1))
        "$SLEEP_BIN" 0.1
    done
    die "ath11k did not register an ieee80211 phy within ${PHY_TRIES} attempts"
}

disable_aspm() {
    endpoint=$(find_endpoint 2>/dev/null || :)
    test -n "$endpoint" || die "cannot disable ASPM: QCA6390 endpoint is absent"
    link_dir="$SYSFS_ROOT/bus/pci/devices/$endpoint/link"
    if ! test -d "$link_dir"; then
        log "ASPM sysfs controls unavailable for endpoint=$endpoint; leaving kernel default"
        return 0
    fi

    changed=0
    for name in l0s_aspm l1_aspm; do
        path="$link_dir/$name"
        test -e "$path" || continue
        test -w "$path" || die "cannot disable ASPM: $name is not writable"
        printf '0\n' > "$path" || die "cannot disable ASPM: write failed for $name"
        changed=1
    done
    if test "$changed" = 1; then
        log "ASPM disabled for endpoint=$endpoint"
    else
        log "ASPM sysfs controls unavailable for endpoint=$endpoint; leaving kernel default"
    fi
}

case "${1:-}" in
    wait-endpoint) wait_endpoint ;;
    wait-phy) wait_phy ;;
    disable-aspm) disable_aspm ;;
    *) die "usage: $0 {wait-endpoint|wait-phy|disable-aspm}" ;;
esac
