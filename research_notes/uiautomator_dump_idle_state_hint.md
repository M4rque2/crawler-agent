# UIAutomator Dump Idle-State Hint

## Context
While dumping Android UI XML with:

- adb shell uiautomator dump <remote_path>

we observed intermittent failures:

- ERROR: could not get idle state.

## What We Verified
Real-device tests on short-video pages:

- Douyin: no idle-state dump issue observed.
- Weibo short video: no idle-state dump issue observed.
- Bilibili: no idle-state dump issue observed.
- Xiaohongshu short video: idle-state dump issue reproducible.

## Confirmed Fix for This Case
For Xiaohongshu short-video pages, use compressed dump:

- adb shell uiautomator dump --compressed <remote_path>

This resolved the dump failure in our tests.
