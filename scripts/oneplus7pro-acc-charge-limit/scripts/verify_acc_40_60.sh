#!/usr/bin/env bash
set -euo pipefail

ADB="${ADB:-adb}"
EXPECTED_PAUSE="${EXPECTED_PAUSE:-60}"
EXPECTED_RESUME="${EXPECTED_RESUME:-40}"

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

if ! command -v "$ADB" >/dev/null 2>&1; then
  echo "Missing adb. Set ADB=/path/to/adb or install Android platform-tools." >&2
  exit 1
fi

run_adb wait-for-device

root_id="$(run_adb shell 'su -c id' | tr -d '\r' || true)"
if [[ "$root_id" != uid=0* ]]; then
  echo "Root check failed. Expected 'su -c id' to return uid=0(root)." >&2
  echo "Actual output: $root_id" >&2
  exit 1
fi

ACC_CMD="/dev/acc"
if ! run_root "test -x /dev/acc" >/dev/null 2>&1; then
  ACC_CMD="acc"
fi

echo "Module:"
run_root "grep -E '^(id|name|version|versionCode)=' /data/adb/modules/acc/module.prop"

echo
echo "Daemon:"
run_root "$ACC_CMD -D"

echo
echo "Policy:"
policy="$(run_root "$ACC_CMD -s | grep -E '^(pause_capacity|resume_capacity|discharge_polarity)='" | tr -d '\r')"
echo "$policy"

pause="$(printf '%s\n' "$policy" | sed -n 's/^pause_capacity=//p')"
resume="$(printf '%s\n' "$policy" | sed -n 's/^resume_capacity=//p')"

if [[ "$pause" != "$EXPECTED_PAUSE" || "$resume" != "$EXPECTED_RESUME" ]]; then
  echo "Policy mismatch. Expected pause=$EXPECTED_PAUSE resume=$EXPECTED_RESUME." >&2
  exit 1
fi

echo
echo "Battery:"
run_root "$ACC_CMD -i 'level|status|CURRENT_NOW|CHARGING_ENABLED|OP_DISABLE_CHARGE|fastChargeStatus'"

echo
echo "ACC 40-60 verification passed."
