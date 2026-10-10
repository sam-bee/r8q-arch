#!/bin/sh
# Controlled private-release loader for the parent-validated v10 amp and v8
# Q6AFE/card closure; it never loads broad sound families or CDSP/SLPI.
set -eu

ROOT=${R8Q_AUDIO_ROOT:-/opt/r8q-audio/7.1.2-r8q-rtc2}
TABLE="$ROOT/module-load-order.tsv"
HASHES="$ROOT/module-hashes.sha256"
EXPECTED_RELEASE=7.1.2-r8q-rtc2
EXPECTED_VERMAGIC='7.1.2-r8q-rtc2 SMP preempt mod_unload aarch64'
ADSP_FW=${R8Q_ADSP_FIRMWARE:-/usr/lib/firmware/qcom/sm8250/Samsung/r8q/adsp.mbn}
FIRMWARE_ROOT=${R8Q_FIRMWARE_ROOT:-/usr/lib/firmware}
CARD_ID=${R8Q_CARD_ID:-CS35L41}
PCM_NODE=${R8Q_PCM_NODE:-pcm0p}
MARKER=${R8Q_AUDIO_MARKER:-/run/r8q-audio-loaded.modules}
ADSP_TIMEOUT=${R8Q_ADSP_TIMEOUT:-30}
Q6_TIMEOUT=${R8Q_Q6_TIMEOUT:-20}
CARD_TIMEOUT=${R8Q_CARD_TIMEOUT:-10}

die() { echo "r8q-audio: $*" >&2; exit 1; }
need() { test -r "$1" || die "missing $1"; }
valid_timeout() {
    case "$1" in ''|*[!0-9]*) return 1 ;; esac
    test "$1" -ge 1 && test "$1" -le 300
}
valid_timeout "$ADSP_TIMEOUT" || die 'R8Q_ADSP_TIMEOUT must be an integer from 1 to 300'
valid_timeout "$Q6_TIMEOUT" || die 'R8Q_Q6_TIMEOUT must be an integer from 1 to 300'
valid_timeout "$CARD_TIMEOUT" || die 'R8Q_CARD_TIMEOUT must be an integer from 1 to 300'

verify_exact_file() {
    path=$1
    expected=$2
    need "$path"
    test "$(/usr/bin/sha256sum "$path" | awk '{print $1}')" = "$expected" || \
        die "firmware hash mismatch: $path"
}

test "$(uname -r)" = "$EXPECTED_RELEASE" || die "wrong kernel release: $(uname -r)"
need "$TABLE"
need "$HASHES"
need "$ADSP_FW"
verify_exact_file "$FIRMWARE_ROOT/cirrus/cs35l40-bot-dsp1-spk-prot.wmfw" \
    e3c60f841f3d9043f3a942befe9cdebd1da3dd0a0dfac54dbf4713d07a5e77f9
verify_exact_file "$FIRMWARE_ROOT/cirrus/cs35l40-bot-dsp1-spk-prot.bin" \
    07dfd71538a8d3e504dfab965c65a6f2f5bb775a4503f74d5ddcd7c987b6b7bf
verify_exact_file "$FIRMWARE_ROOT/cirrus/cs35l40-rcv-dsp1-spk-prot.wmfw" \
    e3c60f841f3d9043f3a942befe9cdebd1da3dd0a0dfac54dbf4713d07a5e77f9
verify_exact_file "$FIRMWARE_ROOT/cirrus/cs35l40-rcv-dsp1-spk-prot.bin" \
    ce13ce5b8eee57a41388624ec82202167c9f1c65510424a0dd3393636e1c9210
verify_exact_file "$FIRMWARE_ROOT/r8q/cs35l40-bot-factory.cal" \
    f684a440245784cc8e0f304de98dcbf7cbda60fbf17afa5377e5c6cdbf76d6ef
verify_exact_file "$FIRMWARE_ROOT/r8q/cs35l40-rcv-factory.cal" \
    3a6fa4fd99d1eece341b0c7bd1ab1a670a9ef3209d09977e6c2139b0a1c90984
tr '\000' '\n' </proc/device-tree/compatible | grep -qx 'samsung,r8q' || \
    die 'machine is not samsung,r8q'
(cd "$ROOT" && /usr/bin/sha256sum --quiet -c module-hashes.sha256) || \
    die 'private module hash check failed'

# Validate every object before the first insmod.  This guards against stale
# modules even when the module-hash file itself was copied correctly.
TAB=$(printf '\t')
while IFS="$TAB" read -r order module source hash private why; do
    [ "$order" = order ] && continue
    [ -n "$order" ] || continue
    path="$ROOT/$private"
    need "$path"
    test "$(/usr/bin/modinfo -F vermagic "$path")" = "$EXPECTED_VERMAGIC" || \
        die "vermagic mismatch: $private"
    expected_name=$(printf '%s' "$module" | tr '-' '_')
    test "$(/usr/bin/modinfo -F name "$path")" = "$expected_name" || \
        die "module-name mismatch: $private"
done < "$TABLE"

mkdir -p "$(dirname "$MARKER")"
touch "$MARKER"

already_owned() {
    name=$1
    /usr/bin/grep -Fxq "$name" "$MARKER" 2>/dev/null
}

load() {
    name=$1
    path=$2
    if test -d "/sys/module/$name"; then
        if already_owned "$name"; then
            return 0
        fi
        # Infrastructure may have been loaded by the exact RTC2 boot image;
        # final Q6/codec/card objects fail closed unless this loader owns them.
        case "$name" in
            q6afe|q6afe_dai|cs_dsp|snd_soc_wm_adsp|snd_soc_cs35l41_lib|\
            snd_soc_cs35l41|snd_soc_cs35l41_i2c|r8q_cs35l41_card)
                die "final audio module already loaded outside private marker: $name" ;;
            *)
                echo "r8q-audio: retaining already-loaded infrastructure $name" >&2
                printf '%s\n' "$name" >> "$MARKER"
                return 0 ;;
        esac
    fi
    /usr/bin/insmod "$ROOT/$path" || die "insmod failed: $name"
    printf '%s\n' "$name" >> "$MARKER"
}

wait_for_adsp() {
    deadline=$(( $(date +%s) + ADSP_TIMEOUT ))
    while test "$(date +%s)" -lt "$deadline"; do
        for dev in /sys/class/remoteproc/remoteproc*; do
            test -r "$dev/name" && test -r "$dev/state" || continue
            name=$(tr -d '\000' <"$dev/name")
            state=$(tr -d '\000' <"$dev/state")
            case "$name" in
                adsp|adsp*|qcom,adsp*)
                    test "$state" = running && return 0 ;;
            esac
        done
        sleep 1
    done
    echo 'r8q-audio: ADSP remoteproc did not reach running:' >&2
    for dev in /sys/class/remoteproc/remoteproc*; do
        test -r "$dev/name" || continue
        echo "  $dev $(tr -d '\000' <"$dev/name") $(tr -d '\000' <"$dev/state")" >&2
    done
    return 1
}

driver_has_device() {
    driver=$1
    dir="/sys/bus/platform/drivers/$driver"
    test -d "$dir" || return 1
    for child in "$dir"/*; do
        test -L "$child" || continue
        case "$child" in
            */bind|*/unbind|*/module|*/subsystem|*/uevent) continue ;;
        esac
        return 0
    done
    return 1
}

wait_for_q6() {
    deadline=$(( $(date +%s) + Q6_TIMEOUT ))
    while test "$(date +%s)" -lt "$deadline"; do
        driver_has_device q6afe-dai && \
        driver_has_device q6asm-dai && \
        driver_has_device q6routing && return 0
        sleep 1
    done
    echo 'r8q-audio: Q6 provider devices did not bind:' >&2
    for driver in q6afe-dai q6asm-dai q6routing; do
        ls -la "/sys/bus/platform/drivers/$driver" 2>/dev/null || true
    done
    return 1
}

apr_service_present() {
    number=$1
    dev="/sys/bus/aprbus/devices/aprsvc:service:4:$number"
    test -d "$dev" || return 1
    test -L "$dev/driver" || return 1
    test -e "$dev/driver" || return 1
}

wait_for_apr_services() {
    deadline=$(( $(date +%s) + Q6_TIMEOUT ))
    while test "$(date +%s)" -lt "$deadline"; do
        apr_service_present 3 && apr_service_present 4 && \
        apr_service_present 7 && apr_service_present 8 && return 0
        sleep 1
    done
    echo 'r8q-audio: expected APR service:4:3/:4/:7/:8 driver links did not appear' >&2
    for dev in /sys/bus/aprbus/devices/aprsvc:service:4:*; do
        test -e "$dev" || continue
        ls -ld "$dev" "$dev/driver" 2>/dev/null || true
    done
    return 1
}

wait_for_card() {
    deadline=$(( $(date +%s) + CARD_TIMEOUT ))
    while test "$(date +%s)" -lt "$deadline"; do
        for card in /sys/class/sound/card*; do
            test -d "$card" || continue
            id="$card/id"
            test -r "$id" && test "$(tr -d '\000' <"$id")" = "$CARD_ID" || continue
            card_name=${card##*/}
            card_num=${card_name#card}
            test -d "/proc/asound/$card_name/$PCM_NODE" && return 0
        done
        sleep 1
    done
    echo 'r8q-audio: expected r8q/CS35L41/Samsung ALSA card did not appear' >&2
    test -r /proc/asound/cards && cat /proc/asound/cards >&2 || true
    return 1
}

while IFS="$TAB" read -r order module source hash private why; do
    [ "$order" = order ] && continue
    [ -n "$order" ] || continue
    load "$module" "$private"
    case "$module" in
        qcom_q6v5_pas) wait_for_adsp || die 'ADSP readiness timeout' ;;
        q6asm_dai)
            wait_for_q6 || die 'Q6 provider readiness timeout'
            wait_for_apr_services || die 'APR service readiness timeout' ;;
        r8q_cs35l41_card) wait_for_card || die 'ALSA card readiness timeout' ;;
    esac
done < "$TABLE"

echo 'r8q-audio: controlled module load and readiness gates passed'
