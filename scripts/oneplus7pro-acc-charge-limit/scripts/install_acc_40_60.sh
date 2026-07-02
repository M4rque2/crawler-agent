#!/usr/bin/env bash
set -euo pipefail

ADB="${ADB:-adb}"
ACC_SOURCE_URL="${ACC_SOURCE_URL:-https://github.com/VR-25/acc/archive/master.tar.gz}"
PAUSE_CAPACITY="${PAUSE_CAPACITY:-60}"
RESUME_CAPACITY="${RESUME_CAPACITY:-40}"
REMOTE_DIR="/data/local/tmp/pkgsrc_acc_install_$$"

adb_args=()
if [[ -n "${ANDROID_SERIAL:-}" ]]; then
  adb_args=(-s "$ANDROID_SERIAL")
fi

run_adb() {
  "$ADB" ${adb_args+"${adb_args[@]}"} "$@"
}

shell_quote() {
  printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

run_root() {
  local quoted
  quoted="$(shell_quote "$1")"
  run_adb shell "su -c $quoted"
}

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

cleanup() {
  run_adb shell "rm -rf '$REMOTE_DIR'" >/dev/null 2>&1 || true
  if [[ -n "${LOCAL_TMP:-}" && -d "$LOCAL_TMP" ]]; then
    rm -rf "$LOCAL_TMP"
  fi
}
trap cleanup EXIT

need_cmd "$ADB"
need_cmd curl
need_cmd tar

echo "Waiting for device..."
run_adb wait-for-device

echo "Connected device:"
run_adb devices -l | sed -n '2,$p'

echo "Checking root..."
root_id="$(run_adb shell 'su -c id' | tr -d '\r' || true)"
if [[ "$root_id" != uid=0* ]]; then
  echo "Root check failed. Expected 'su -c id' to return uid=0(root)." >&2
  echo "Actual output: $root_id" >&2
  exit 1
fi
echo "$root_id"

LOCAL_TMP="$(mktemp -d)"
echo "Downloading ACC from official upstream..."
curl -L "$ACC_SOURCE_URL" -o "$LOCAL_TMP/acc.tar.gz"
tar -xzf "$LOCAL_TMP/acc.tar.gz" -C "$LOCAL_TMP"
ACC_SRC="$(find "$LOCAL_TMP" -maxdepth 1 -type d -name 'acc-*' | head -n 1)"
if [[ -z "$ACC_SRC" || ! -f "$ACC_SRC/install.sh" ]]; then
  echo "Could not find extracted ACC source with install.sh." >&2
  exit 1
fi

echo "Staging ACC on device..."
run_adb shell "rm -rf '$REMOTE_DIR' && mkdir '$REMOTE_DIR'"
run_adb push "$ACC_SRC/." "$REMOTE_DIR/" >/dev/null

echo "Installing ACC as a Magisk module..."
run_root "installDir=/data/adb/modules /system/bin/sh $REMOTE_DIR/install.sh"

echo "Setting charging policy: resume=${RESUME_CAPACITY}%, pause=${PAUSE_CAPACITY}%..."
run_root "/dev/acc $PAUSE_CAPACITY $RESUME_CAPACITY"

echo "Checking current polarity..."
batt_status="$(run_root "cat /sys/class/power_supply/battery/status 2>/dev/null || true" | tr -d '\r' | tail -n 1)"
current_now="$(run_root "cat /sys/class/power_supply/battery/current_now 2>/dev/null || true" | tr -d '\r' | tail -n 1)"
polarity="${DISCHARGE_POLARITY:-}"

if [[ -z "$polarity" && "$batt_status" =~ ^(Charging|Full)$ && "$current_now" =~ ^-?[0-9]+$ ]]; then
  if (( current_now < 0 )); then
    polarity="+"
  elif (( current_now > 0 )); then
    polarity="-"
  fi
fi

if [[ -n "$polarity" ]]; then
  echo "Setting discharge_polarity=$polarity..."
  run_root "/dev/acc -s dp=$polarity"
else
  echo "Could not infer discharge polarity. If ACC asks for it later, unplug briefly or set DISCHARGE_POLARITY=+/- and rerun."
fi

echo "Restarting ACC daemon..."
run_root "/dev/acc -D restart"

echo "Final verification:"
run_root "/dev/acc -D"
run_root "/dev/acc -s | grep -E '^(pause_capacity|resume_capacity|discharge_polarity)='"
run_root "/dev/acc -i 'level|status|CURRENT_NOW|CHARGING_ENABLED|OP_DISABLE_CHARGE'"

echo "Done."
