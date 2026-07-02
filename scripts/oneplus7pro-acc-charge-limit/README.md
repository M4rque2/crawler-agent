# OnePlus 7 Pro ACC Charging Limit Guide

This folder documents how to install Advanced Charging Controller (ACC) on a rooted OnePlus 7 Pro and set a 40%-60% charging policy for always-plugged ADB development.

The target behavior is:

- charging resumes at 40%
- charging pauses at 60%
- USB ADB can stay connected
- ACC starts through Magisk after boot

## Files

- `README.md`: this guide.
- `scripts/install_acc_40_60.sh`: host-side installer for macOS/Linux. Downloads ACC from the official upstream source, installs it through root shell, and sets the policy.
- `scripts/verify_acc_40_60.sh`: host-side verification script.

ACC itself is not vendored here. The installer downloads it from the official upstream repository:

https://github.com/VR-25/acc

## Requirements

- OnePlus 7 Pro connected over USB.
- USB debugging enabled.
- `adb` installed on the computer.
- Phone is rooted.
- Magisk is installed and grants `su` to ADB shell.
- Internet access on the computer, so the installer can download ACC source.

Check the phone first:

```sh
adb devices -l
adb shell 'su -c id'
```

The root check should print something like:

```text
uid=0(root) gid=0(root)
```

If the phone shows a Magisk prompt, approve shell root access on the phone.

## Install ACC And Set 40-60

From this folder's parent project:

```sh
cd /Users/zhangchi1/Code/crawler-agent/oneplus7pro-acc-charge-limit
./scripts/install_acc_40_60.sh
```

If multiple Android devices are connected, specify the target:

```sh
ANDROID_SERIAL=3df37e52 ./scripts/install_acc_40_60.sh
```

The script does this:

1. Confirms `adb` is available.
2. Confirms the connected device has root via `su`.
3. Downloads ACC source from official GitHub.
4. Pushes ACC to `/data/local/tmp/pkgsrc_acc_install_<pid>` on the phone.
5. Runs ACC's installer as root with `installDir=/data/adb/modules`.
6. Sets ACC thresholds with `/dev/acc 60 40`.
7. Sets `discharge_polarity` when it can infer it from the current battery reading.
8. Restarts the ACC daemon.
9. Verifies the daemon and threshold config.

ACC uses the syntax:

```sh
acc pause_capacity resume_capacity
```

So a 40%-60% window is:

```sh
acc 60 40
```

Before reboot, ACC may only be available as `/dev/acc`. After reboot, Magisk should expose it as `acc`.

## Verify

Run:

```sh
./scripts/verify_acc_40_60.sh
```

Expected important lines:

```text
pause_capacity=60
resume_capacity=40
accd ... is running
```

You can also check manually:

```sh
adb shell 'su -c "/dev/acc -D"'
adb shell 'su -c "/dev/acc -s | grep -E \"^(pause_capacity|resume_capacity|discharge_polarity)=\""'
adb shell 'su -c "/dev/acc -i \"level|status|CURRENT_NOW|CHARGING_ENABLED|OP_DISABLE_CHARGE\""'
```

## Reboot Test

After installation, reboot once and verify again:

```sh
adb reboot
adb wait-for-device
adb shell 'su -c "acc -D || /dev/acc -D"'
```

If `acc` is not in `PATH` immediately after boot, use `/dev/acc`.

## Current OnePlus 7 Pro Notes

On the tested OnePlus 7 Pro, charging current was reported as a negative `CURRENT_NOW` value while charging. That means ACC's `discharge_polarity` should be positive:

```sh
adb shell 'su -c "/dev/acc -s dp=+"'
adb shell 'su -c "/dev/acc -D restart"'
```

The installer tries to infer this automatically. If ACC logs say:

```text
discharge_polarity is not set. Unplug and wait, or set it manually.
```

set it manually with the commands above.

## Operational Advice

- Do not keep phones with swollen batteries in service.
- Avoid Warp/Fast chargers for lab devices.
- Prefer a normal USB power source and keep the screen dim/off.
- Add airflow if many phones are racked together.
- Replace old or swollen batteries before using ACC.

At 40%-60%, the phone will still cycle the battery, but it avoids sitting at 100% for long periods, which is the main always-plugged battery aging problem.

## Troubleshooting

### `su -c id` does not return root

Open Magisk on the phone and grant root permission to Shell/ADB. Then retry:

```sh
adb shell 'su -c id'
```

### Installer exits after printing "Installing in /data/adb/modules/acc/..."

Check the install log:

```sh
adb shell 'su -c "tail -200 /data/adb/vr25/acc-data/logs/install.log"'
```

One known issue is staging ACC under a directory named `/data/local/tmp/acc-*`; ACC's cleanup removes paths matching that pattern. The provided installer uses `/data/local/tmp/pkgsrc_acc_install_<pid>` to avoid this.

### ACC daemon is not running

Start or restart it:

```sh
adb shell 'su -c "/dev/acc -D restart"'
adb shell 'su -c "/dev/acc -D"'
```

### Charging does not pause at 60%

First verify the policy:

```sh
adb shell 'su -c "/dev/acc -s | grep -E \"^(pause_capacity|resume_capacity|discharge_polarity)=\""'
```

Then inspect battery control state:

```sh
adb shell 'su -c "/dev/acc -i \"level|status|CURRENT_NOW|CHARGING_ENABLED|OP_DISABLE_CHARGE\""'
```

If the phone is below 60%, charging should remain enabled. It should pause only once it reaches the configured `pause_capacity`.

