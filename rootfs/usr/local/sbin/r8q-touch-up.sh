#!/bin/sh
# Load the dual-sourced touch driver after the USB route owns GPI/GENI.
set -eu

SYSFS_ROOT=${R8Q_TOUCH_SYSFS_ROOT:-/sys}
MODPROBE_BIN=${R8Q_TOUCH_MODPROBE_BIN:-/usr/bin/modprobe}
SLEEP_BIN=${R8Q_TOUCH_SLEEP_BIN:-/usr/bin/sleep}
LOGGER_BIN=${R8Q_TOUCH_LOGGER_BIN:-/usr/bin/logger}
TRIES=${R8Q_TOUCH_TRIES:-100}
INTERVAL=${R8Q_TOUCH_INTERVAL:-0.1}

log() {
    "$LOGGER_BIN" -t r8q-touch -- "$*" 2>/dev/null || :
}

die() {
    echo "r8q-touch: $*" >&2
    log "ERROR: $*"
    exit 1
}

test -d "$SYSFS_ROOT/module/gpi" || die 'pinned GPI module is not loaded'
test -d "$SYSFS_ROOT/module/i2c_qcom_geni" || die 'pinned GENI module is not loaded'
FIFO_PARAM=$SYSFS_ROOT/module/i2c_qcom_geni/parameters/r8q_force_fifo
test -f "$FIFO_PARAM" || die 'GENI FIFO parameter is unavailable'
case "$(cat "$FIFO_PARAM" | tr -d '\r\n')" in
    Y|y|1) ;;
    *) die 'GENI force_fifo is not enabled' ;;
esac

FTS_BIND=$SYSFS_ROOT/bus/i2c/drivers/fts5cu56a/5-0049
ZINITIX_BIND=$SYSFS_ROOT/bus/i2c/drivers/Zinitix-TS/5-0020

has_ready_event() {
    path=$1
    test -e "$path" || return 1
    # A bound I2C driver is not ready for input consumers until the input core
    # has registered an event node below that client.
    for event in "$path"/input/input*/event*; do
        test -e "$event" || continue
        return 0
    done
    return 1
}

wait_for_ready() {
    path=$1
    i=0
    while test "$i" -lt "$TRIES"; do
        if has_ready_event "$path"; then
            return 0
        fi
        i=$((i + 1))
        "$SLEEP_BIN" "$INTERVAL"
    done
    return 1
}

# Prefer the STM controller. A successful modprobe is not enough: only a
# bound driver with its input event proves that this board has that part.
if has_ready_event "$FTS_BIND"; then
    log 'FTS5CU56A already bound with input event'
    exit 0
fi
if "$MODPROBE_BIN" fts5cu56a; then
    log 'requested FTS5CU56A'
else
    log 'FTS5CU56A request failed; trying Zinitix after bounded readiness check'
fi
if wait_for_ready "$FTS_BIND"; then
    log 'FTS5CU56A bound with input event'
    exit 0
fi

# Recheck after the wait in case the input node appeared at the timeout edge.
if has_ready_event "$FTS_BIND"; then
    log 'FTS5CU56A input event appeared at readiness timeout boundary'
    exit 0
fi
if has_ready_event "$ZINITIX_BIND"; then
    log 'Zinitix already bound with input event'
    exit 0
fi
"$MODPROBE_BIN" zinitix || die 'Zinitix module request failed'
wait_for_ready "$ZINITIX_BIND" || die 'neither touch driver and input event became ready'
log 'Zinitix ZT7650 bound'
