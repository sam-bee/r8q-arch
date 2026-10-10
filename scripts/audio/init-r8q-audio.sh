#!/bin/sh
# Post-card ALSA/DSP initialization. Loader must have completed first.
set -eu

ROOT=${R8Q_AUDIO_ROOT:-/opt/r8q-audio/7.1.2-r8q-rtc2}
MARKER=${R8Q_AUDIO_MARKER:-/run/r8q-audio-loaded.modules}
STATE_DIR=${R8Q_AUDIO_STATE_DIR:-/run/r8q-audio}
FIRMWARE_ROOT=${R8Q_FIRMWARE_ROOT:-/usr/lib/firmware}
ADSP_FW=${R8Q_ADSP_FIRMWARE:-/usr/lib/firmware/qcom/sm8250/Samsung/r8q/adsp.mbn}
CARD_NUM=''

fail() { echo "r8q-audio-init: $*" >&2; exit 1; }
need() { test -r "$1" || fail "missing $1"; }
exact_hash() {
    path=$1; expected=$2
    need "$path"
    test "$(sha256sum "$path" | awk '{print $1}')" = "$expected" || \
        fail "hash mismatch: $path"
}

# The module loader has already performed these checks; retain them here so a
# manually invoked init cannot bypass the per-device firmware/calibration gate.
test "$(uname -r)" = 7.1.2-r8q-rtc2 || fail "wrong kernel release"
tr '\000' '\n' </proc/device-tree/compatible | grep -qx 'samsung,r8q' || \
    fail 'machine is not samsung,r8q'
need "$MARKER"
for module in qcom_q6v5_pas q6afe q6afe_dai q6asm_dai snd_soc_cs35l41_i2c r8q_cs35l41_card; do
    grep -Fxq "$module" "$MARKER" || fail "loader did not own $module"
done
for card in /sys/class/sound/card*; do
    test -d "$card" || continue
    test -r "$card/id" || continue
    test "$(tr -d '\000' <"$card/id")" = CS35L41 || continue
    card_name=${card##*/}
    test -d "/proc/asound/$card_name/pcm0p" || continue
    CARD_NUM=${card_name#card}
    break
done
test -n "$CARD_NUM" || fail 'CS35L41 pcm0p card is not ready'
need "$ADSP_FW"
exact_hash "$FIRMWARE_ROOT/cirrus/cs35l40-bot-dsp1-spk-prot.wmfw" \
    e3c60f841f3d9043f3a942befe9cdebd1da3dd0a0dfac54dbf4713d07a5e77f9
exact_hash "$FIRMWARE_ROOT/cirrus/cs35l40-bot-dsp1-spk-prot.bin" \
    07dfd71538a8d3e504dfab965c65a6f2f5bb775a4503f74d5ddcd7c987b6b7bf
exact_hash "$FIRMWARE_ROOT/cirrus/cs35l40-rcv-dsp1-spk-prot.wmfw" \
    e3c60f841f3d9043f3a942befe9cdebd1da3dd0a0dfac54dbf4713d07a5e77f9
exact_hash "$FIRMWARE_ROOT/cirrus/cs35l40-rcv-dsp1-spk-prot.bin" \
    ce13ce5b8eee57a41388624ec82202167c9f1c65510424a0dd3393636e1c9210
exact_hash "$FIRMWARE_ROOT/r8q/cs35l40-bot-factory.cal" \
    f684a440245784cc8e0f304de98dcbf7cbda60fbf17afa5377e5c6cdbf76d6ef
exact_hash "$FIRMWARE_ROOT/r8q/cs35l40-rcv-factory.cal" \
    3a6fa4fd99d1eece341b0c7bd1ab1a670a9ef3209d09977e6c2139b0a1c90984

mkdir -p "$STATE_DIR"
# Establish the tested protected path while the driver owns physical mute and
# the analog gain control is held at zero.
for side in Left Right; do
    amixer -q -c "$CARD_NUM" cset name="$side DSP1 Firmware" Protection
    amixer -q -c "$CARD_NUM" cset name="$side PCM Source" DSP
    amixer -q -c "$CARD_NUM" cset name="$side DSP RX1 Source" ASPRX1
    amixer -q -c "$CARD_NUM" cset name="$side DSP RX2 Source" ASPRX1
    amixer -q -c "$CARD_NUM" cset name="$side Analog PCM Volume" 0
    amixer -q -c "$CARD_NUM" cset name="$side Digital PCM Volume" 700
done
# Preload starts HALO and applies both factory calibrations under mute.
for side in Left Right; do
    amixer -q -c "$CARD_NUM" cset name="$side DSP1 Preload Switch" on
done
amixer -q -c "$CARD_NUM" cset name='PRIMARY_TDM_RX_0 Audio Mixer MultiMedia1' on
amixer -c "$CARD_NUM" contents >"$STATE_DIR/alsa-initialized.contents"
cat "/proc/asound/card${CARD_NUM}/id" >"$STATE_DIR/card.id"
printf '%s\n' initialized >"$STATE_DIR/status"
echo 'r8q-audio-init: protected DSP/PCM source, RX routes, preload/calibration, primary MM1, analog gain 0, and digital volume 700 initialized; physical mute remains driver-owned'
