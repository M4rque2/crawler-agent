# crawler-agent MacOS 开发调试 Quick Guide

这份文档面向没有工程背景的同学，目标是让你在 MacOS 上把 crawler-agent 跑起来，并知道后续开发、调试任务时应该看哪些文件。

请按顺序操作。不要跳步。遇到报错时，先看本文末尾的“常见问题排查”。

## 0. 先理解这个项目在做什么

crawler-agent 会通过 Android 模拟器打开手机 App，截图观察当前界面，把截图和任务说明发给模型，让模型决定下一步点击、滑动、输入或提取信息，然后 crawler-agent 再通过 ADB 控制模拟器执行这些动作。

所以它至少需要四类东西：

1. 一台可以被电脑控制的 Android 设备。这里推荐 Android Studio 自带的 Android 虚拟机。
2. `adb` 命令。crawler-agent 靠它截图、点击、滑动、打开 App。
3. 一个可用的模型推理服务。这里推荐在 `lpai-llm.lixiang.com` 订阅 `Qwen3_5-397B-A17B`。
4. Python 运行环境。crawler-agent 本身是 Python 程序。

## 1. 打开 MacOS 终端

后面很多步骤都需要输入命令。

打开方式：

1. 按 `Command + Space`。
2. 输入 `Terminal` 或 `终端`。
3. 回车打开。

本文里的命令都在终端里执行。复制命令时，一次只复制一个代码块，粘贴后按回车。

如果你已经拿到了这个项目代码，先进入项目目录：

```bash
cd /Users/zhangchi1/Code/crawler-agent
```

如果你的项目放在别的位置，把上面的路径换成你自己的项目路径。

## 2. 安装和检查 Python 环境

先检查 Mac 上有没有 Python 3：

```bash
python3 --version
```

正常情况会看到类似：

```text
Python 3.11.8
```

只要是 Python 3.10、3.11、3.12 这类版本，一般都可以继续。

如果提示 `command not found: python3`，先安装 Python。最简单的方法是安装 Homebrew 后执行：

```bash
brew install python
```

进入项目目录后，创建一个只给本项目使用的 Python 虚拟环境：

```bash
cd /Users/zhangchi1/Code/crawler-agent
python3 -m venv .venv
```

启用虚拟环境：

```bash
source .venv/bin/activate
```

启用成功后，终端命令行前面通常会出现 `(.venv)`。

安装项目依赖：

```bash
python -m pip install -r requirements.txt
```

验证依赖是否安装成功：

```bash
python -c "import PIL, requests; print('Python dependencies OK')"
```

正常输出：

```text
Python dependencies OK
```

以后每次重新打开终端跑 crawler-agent，都要先进入项目目录并启用虚拟环境：

```bash
cd /Users/zhangchi1/Code/crawler-agent
source .venv/bin/activate
```

## 3. 安装 ADB

### 3.1 ADB 是什么

ADB 全称是 Android Debug Bridge。你可以把它理解成“Mac 控制 Android 手机或模拟器的遥控器”。

crawler-agent 使用 ADB 做这些事情：

- 截取模拟器当前屏幕。
- 点击屏幕某个位置。
- 滑动页面。
- 输入文字。
- 按返回键、Home 键。
- 打开指定 App。

如果没有 ADB，crawler-agent 无法控制 Android 模拟器。

### 3.2 ADB 和 Android Studio 能不能合并安装

可以合并。

更准确地说：

- ADB 属于 Android SDK Platform-Tools。
- Android Studio 安装过程中通常会安装 Android SDK，也通常会带上 Android SDK Platform-Tools。
- 所以安装 Android Studio 后，大概率本机已经有了 `adb` 文件。
- 但是，终端不一定能直接找到 `adb`，因为它所在目录还没有加入 `PATH`。

因此推荐做法是：

1. 安装 Android Studio。
2. 确认 Android SDK Platform-Tools 已安装。
3. 把 Platform-Tools 目录加入 MacOS 的 `PATH`。
4. 用 `adb devices` 验证。

如果你只想安装 ADB，不想装 Android Studio，也可以从 Android 官方 Platform-Tools 页面单独下载。但本项目还需要 Android 虚拟机，所以推荐直接安装 Android Studio。

官方参考：

- [Android SDK Platform-Tools](https://developer.android.com/tools/releases/platform-tools)
- [Android Studio command-line tools](https://developer.android.com/tools)

### 3.3 安装 Android Studio

1. 打开 [Android Studio 下载页](https://developer.android.com/studio)。
2. 下载 Mac 版本。
3. 打开下载好的 `.dmg` 文件。
4. 把 Android Studio 拖到 `Applications`。
5. 从 `Applications` 打开 Android Studio。
6. 第一次打开时，按 Setup Wizard 的默认推荐配置继续安装。

如果安装过程中看到这些组件，建议都保留：

- Android SDK
- Android SDK Platform-Tools
- Android Emulator
- Android SDK Build-Tools

安装完成后，Android SDK 通常在这个目录：

```text
/Users/你的用户名/Library/Android/sdk
```

对当前这台机器，通常是：

```text
/Users/zhangchi1/Library/Android/sdk
```

ADB 通常在：

```text
/Users/zhangchi1/Library/Android/sdk/platform-tools/adb
```

### 3.4 把 ADB 加入 PATH

`PATH` 可以理解为“终端查找命令的目录清单”。把 ADB 加入 `PATH` 后，你在任何目录输入 `adb`，终端都能找到它。

在终端执行：

```bash
echo 'export ANDROID_HOME="$HOME/Library/Android/sdk"' >> ~/.zshrc
echo 'export PATH="$ANDROID_HOME/platform-tools:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

验证终端能不能找到 ADB：

```bash
which adb
```

正常输出类似：

```text
/Users/zhangchi1/Library/Android/sdk/platform-tools/adb
```

再验证 ADB 版本：

```bash
adb version
```

正常输出类似：

```text
Android Debug Bridge version 1.0.41
Version 36.0.0-...
```

如果这里提示 `adb not found` 或 `command not found: adb`，说明 `PATH` 没配好，回到本节重新检查。

## 4. 创建 Android 虚拟机

### 4.1 为什么需要 Android 虚拟机

crawler-agent 面向手机 GUI 自动化。调试时最稳定的方式是使用 Android Studio 自带的虚拟机，也叫 AVD，完整名称是 Android Virtual Device。

用虚拟机的好处：

- 不需要真实手机。
- 分辨率、系统版本、设备型号更统一。
- 截图、点击、滑动行为更容易复现。
- 出问题时可以重启、清数据、重新创建。

### 4.2 先确认 Mac 芯片

点击屏幕左上角 Apple 图标，选择 `About This Mac` 或 `关于本机`。

如果看到 `Chip: Apple M1/M2/M3/M4...`，说明是 Apple Silicon Mac，推荐创建 `arm64-v8a` 系统镜像。

如果是 Intel Mac，`arm64-v8a` 镜像可能不可用或运行很慢。本文仍以 Apple Silicon Mac 为主，因为本项目推荐使用 ARM v8 指令集模拟器。

### 4.3 打开 Device Manager

打开 Android Studio。

如果在欢迎页：

1. 点击 `More Actions`。
2. 选择 `Virtual Device Manager` 或 `Device Manager`。

如果已经打开了某个 Android Studio 项目：

1. 看右侧工具栏是否有 `Device Manager`。
2. 或者从顶部菜单找 `Tools` -> `Device Manager`。

### 4.4 创建 Pixel 9 ARM v8 实例

在 Device Manager 里：

1. 点击 `Create Device`。
2. 左侧选择 `Phone`。
3. 设备型号选择 `Pixel 9`。
4. 点击 `Next`。

选择系统镜像时重点看两列：

- API Level：选择较新的稳定版本即可。
- ABI：必须优先选择 `arm64-v8a`。

如果有多个镜像，推荐优先级是：

1. `Google Play` + `arm64-v8a`
2. `Google APIs` + `arm64-v8a`

地图、定位、登录、依赖 Google 服务的 App，通常更适合使用带 Google Play 或 Google APIs 的镜像。

如果镜像右侧显示 `Download`，先点击下载，等待完成后再继续。

### 4.5 地图类应用必须注意 Software GPU

在最后的配置页面，点击 `Show Advanced Settings`。

找到类似下面的配置：

```text
Emulated Performance
Graphics
```

地图类应用建议选择：

```text
Software
```

有些 Android Studio 版本会显示成：

```text
Software - GLES 2.0
```

或类似名称。

这里不要选 `Automatic` 或 `Hardware` 作为地图任务的默认配置。地图类 App 经常使用复杂的地图瓦片、WebView、OpenGL 渲染或定位视图，硬件图形模式在某些 Mac 和模拟器组合上可能出现这些问题：

- 地图黑屏。
- 地图瓦片不加载。
- 截图和真实界面不一致。
- 模型看到的图像不完整。
- 点击位置看起来正确，但实际页面状态异常。

普通非地图任务可以尝试 `Automatic` 或 `Hardware`，但地图类任务优先用 `Software`。

最后建议把虚拟机命名为容易识别的名字，例如：

```text
Pixel_9_arm64_software_gpu
```

点击 `Finish`。

官方 AVD 参考：

- [Create and manage virtual devices](https://developer.android.com/studio/run/managing-avds)
- [Configure Android Emulator acceleration](https://developer.android.com/studio/run/emulator-acceleration)

### 4.6 启动虚拟机

回到 Device Manager，找到刚才创建的虚拟机，点击右侧三角形运行按钮。

等待模拟器启动到 Android 桌面。

第一次启动可能比较慢，等待几分钟是正常的。

启动完成后，在终端执行：

```bash
adb devices
```

正常输出类似：

```text
List of devices attached
emulator-5554	device
```

只要看到一行 `emulator-xxxx    device`，说明 ADB 已经能控制模拟器。

再测试一条简单命令：

```bash
adb shell wm size
```

正常输出类似：

```text
Physical size: 1080x2424
```

再测试截图能力：

```bash
adb exec-out screencap -p > /tmp/crawler-agent-test.png
open /tmp/crawler-agent-test.png
```

如果弹出的图片就是模拟器当前屏幕，说明 ADB、模拟器、截图链路都正常。

到这里，Android 侧依赖基本完成。

## 5. 配置模型推理服务

### 5.1 需要拿到三个信息

打开：

```text
https://lpai-llm.lixiang.com
```

登录后订阅一个模型推理服务。推荐模型：

```text
Qwen3_5-397B-A17B
```

你需要从平台拿到三个信息：

1. `url`：模型服务请求地址，通常是一个以 `https://` 开头的接口地址。
2. `model-name`：模型名称，推荐填 `Qwen3_5-397B-A17B`，但以平台实际展示为准。
3. `api-key`：访问密钥，通常是一串较长的 token。

注意：`api-key` 是密码级别的信息，不要发到群里，不要截图公开，不要提交到 Git。

### 5.2 创建 model_config.json

项目里已经有模板文件：

```text
model_config.json.example
```

如果还没有 `model_config.json`，在项目目录执行：

```bash
cp model_config.json.example model_config.json
```

用文本编辑器打开：

```bash
open -e model_config.json
```

把里面这三个字段替换成你从平台拿到的信息：

```json
{
  "endpoint_url": "把平台给你的 url 填在这里",
  "api_key": "把平台给你的 api-key 填在这里",
  "model_name": "Qwen__Qwen3_5-397B-A17B"
}
```

编辑时特别注意：

- 双引号 `"` 不要删。
- 每一行末尾的逗号 `,` 不要乱删，也不要在最后一行多加逗号。
- `endpoint_url`、`api_key`、`model_name` 都不能为空。
- 如果平台给的 URL 已经包含 `/v1/chat/completions`，就完整照抄。
- 如果平台只给了基础地址，需要按平台文档确认最终 chat completions 地址。

保存后，验证 JSON 格式是否正确：

```bash
python -m json.tool model_config.json > /tmp/model_config_checked.json
```

如果没有任何报错，说明 JSON 格式正确。

如果报错，常见原因是少了双引号、少了逗号、多了逗号，或复制了中文引号。

## 6. 第一次运行 crawler-agent

运行前确认三件事：

1. Android 模拟器已经启动，并停留在桌面或目标 App 附近。
2. `adb devices` 能看到 `emulator-xxxx    device`。
3. `model_config.json` 已经填好。

进入项目目录并启用 Python 虚拟环境：

```bash
cd /Users/zhangchi1/Code/crawler-agent
source .venv/bin/activate
```

先跑一个已有任务，例如：

```bash
bash tasks/xhs_search/run_task.sh
```

运行时你会在终端看到类似信息：

```text
[TASK ROOT] tasks/xhs_search/2026-...
[PREFLIGHT] Checking device state...
STEP 0
[MODEL OUTPUT]
[ACTION RAW]
```

这说明 crawler-agent 已经在做完整流程：

1. 检查设备状态。
2. 截图。
3. 请求模型。
4. 解析模型动作。
5. 通过 ADB 执行动作。
6. 保存日志和截图。

如果你只是想快速测试整体链路，可以把任务脚本里的 `--max-steps` 改小，例如改成 `5`，避免第一次跑太久。

## 7. 看日志和调试结果

每次任务运行都会生成一个带时间戳的目录，例如：

```text
tasks/xhs_search/2026-06-24_15-30-00/
```

里面通常有：

```text
run_YYYY-mm-dd HH-MM-SS.log
screenshot/
screenshot_anno/
llm-tracer/
output.jsonl
```

这些文件的含义：

- `run_*.log`：终端完整日志。排查报错优先看它。
- `screenshot/`：每一步原始截图。
- `screenshot_anno/`：带点击或滑动标注的截图。
- `llm-tracer/`：每次请求模型的输入和输出，适合排查模型为什么做了某个动作。
- `output.jsonl`：模型执行 `extract` 时保存的结构化结果。

非技术同学排查问题时，建议按这个顺序看：

1. 打开 `screenshot/`，确认模型看到的画面是否正常。
2. 打开 `screenshot_anno/`，确认点击位置是否明显不对。
3. 打开 `run_*.log`，搜索 `[ERROR]`、`[WARN]`。
4. 打开 `llm-tracer/`，看模型输出是不是格式错误或理解错任务。

## 8. 推荐的任务开发方式

所有具体任务建议放在 `tasks/` 目录下。

每个任务单独创建一个子目录。目录名建议用英文小写和下划线，不要用空格，例如：

```text
tasks/xhs_search/
tasks/xhs_note_collection/
tasks/byd_flash_charge/
tasks/your_new_task/
```

一个任务目录至少包含两个文件：

```text
tasks/your_new_task/
  task_prompt.md
  run_task.sh
```

### 8.1 创建新任务目录

例如要创建一个叫 `demo_map_search` 的任务：

```bash
mkdir -p tasks/demo_map_search
```

复制一个已有任务脚本作为起点：

```bash
cp tasks/xhs_search/run_task.sh tasks/demo_map_search/run_task.sh
```

创建任务说明文件：

```bash
touch tasks/demo_map_search/task_prompt.md
open -e tasks/demo_map_search/task_prompt.md
```

### 8.2 task_prompt.md 应该写什么

`task_prompt.md` 是给模型看的任务说明。它越清楚，模型越不容易乱点。

建议包含这些内容：

1. 目标：这次任务最终要得到什么。
2. 起点：从哪个 App 或哪个页面开始。
3. 操作范围：允许点击、搜索、打开详情页、滑动等。
4. 禁止事项：不要登录、不要下单、不要发评论、不要点赞、不要修改设置。
5. 提取字段：需要保存哪些信息。
6. 结束条件：什么时候可以停止。

示例：

```markdown
# Task

打开目标 App，搜索“充电站”，进入搜索结果列表。

请浏览前 10 个结果，并对每个结果提取：

- 名称
- 地址
- 距离
- 评分
- 当前页面可见的其他重要信息

禁止操作：

- 不要登录账号
- 不要下单
- 不要付款
- 不要评论、点赞、收藏
- 不要修改系统设置或 App 设置

结束条件：

- 成功提取 10 条结果后终止
- 如果页面明确没有更多结果，也可以终止
```

### 8.3 run_task.sh 应该怎么改

打开：

```bash
open -e tasks/demo_map_search/run_task.sh
```

一般只需要确认这几行：

```bash
python run_agent.py \
    --model-config "model_config.json" \
    --system-prompt-path "system_prompt.md" \
    --task-prompt-path "${TASK_DIR}/task_prompt.md" \
    --trace-dir "${TRACE_DIR}" \
    --max-steps 120 \
    --history-length 6
```

常用参数解释：

- `--model-config`：模型配置文件，通常就是 `model_config.json`。
- `--system-prompt-path`：通用系统提示词，通常不用改。
- `--task-prompt-path`：当前任务提示词，通常指向本目录的 `task_prompt.md`。
- `--trace-dir`：日志、截图、模型请求记录保存在哪里。
- `--max-steps`：最多执行多少步。调试时可以先用 `5` 或 `10`，正式跑再调大。
- `--history-length`：给模型看最近几步历史。一般先保持 `6`。

运行新任务：

```bash
bash tasks/demo_map_search/run_task.sh
```

### 8.4 调试任务时的推荐节奏

不要一开始就让任务跑 100 多步。建议这样调：

1. 先把 `--max-steps` 改成 `5`。
2. 运行任务。
3. 看 `screenshot/` 和 `screenshot_anno/`。
4. 如果模型第一步就理解错了，先改 `task_prompt.md`。
5. 如果点击位置错了，看是否是截图异常、地图黑屏、坐标缩放问题或模拟器分辨率问题。
6. 前 5 步稳定后，把 `--max-steps` 改成 `20`。
7. 20 步稳定后，再跑完整任务。

每次只改一个东西。不要同时改提示词、模型配置、模拟器配置和代码，否则很难判断到底是哪一处带来的变化。

## 9. 依赖检查总清单

正式开始开发前，逐条执行下面命令。

检查 Python：

```bash
python3 --version
```

启用项目虚拟环境：

```bash
cd /Users/zhangchi1/Code/crawler-agent
source .venv/bin/activate
```

检查 Python 依赖：

```bash
python -c "import PIL, requests; print('Python dependencies OK')"
```

检查 ADB 路径：

```bash
which adb
```

检查 ADB 版本：

```bash
adb version
```

检查模拟器是否连接：

```bash
adb devices
```

检查模拟器分辨率：

```bash
adb shell wm size
```

检查截图：

```bash
adb exec-out screencap -p > /tmp/crawler-agent-test.png
open /tmp/crawler-agent-test.png
```

检查模型配置 JSON 格式：

```bash
python -m json.tool model_config.json > /tmp/model_config_checked.json
```

如果这些命令都正常，依赖问题基本解决。

## 10. 常见问题排查

### 10.1 `zsh: command not found: adb`

原因：终端找不到 ADB。

处理：

```bash
echo 'export ANDROID_HOME="$HOME/Library/Android/sdk"' >> ~/.zshrc
echo 'export PATH="$ANDROID_HOME/platform-tools:$PATH"' >> ~/.zshrc
source ~/.zshrc
which adb
```

如果还是找不到，检查这个文件是否存在：

```bash
ls "$HOME/Library/Android/sdk/platform-tools/adb"
```

如果文件不存在，打开 Android Studio -> SDK Manager -> SDK Tools，安装或重新安装 Android SDK Platform-Tools。

### 10.2 `adb devices` 看不到设备

先确认 Android 模拟器已经启动到桌面。

然后执行：

```bash
adb kill-server
adb start-server
adb devices
```

如果仍然没有设备，重启模拟器。

### 10.3 `adb devices` 看到多个设备

输出类似：

```text
List of devices attached
emulator-5554	device
emulator-5556	device
```

多个设备会让 crawler-agent 不知道控制哪一个。最简单处理方式是只保留一个模拟器运行，关掉其他模拟器或拔掉真实手机。

### 10.4 地图黑屏或地图不加载

优先检查虚拟机 GPU 设置。

处理：

1. 关闭当前模拟器。
2. 打开 Android Studio -> Device Manager。
3. 找到虚拟机，点击编辑按钮。
4. 打开 Advanced Settings。
5. 把 Graphics 改成 `Software` 或 `Software - GLES 2.0`。
6. 保存。
7. 重新启动模拟器。

如果还是异常，可以在 Device Manager 里对该虚拟机执行 `Cold Boot Now`。必要时执行 `Wipe Data`，但它会清掉模拟器里的 App 数据。

### 10.5 `model_config.json` 报 JSON 错误

执行：

```bash
python -m json.tool model_config.json
```

如果报错，通常是：

- 少了英文双引号。
- 多了中文引号。
- 少了逗号。
- 最后一行多了逗号。
- 复制 API Key 时带了多余空格或换行。

建议重新从 `model_config.json.example` 复制一份，再只替换三个字段。

### 10.6 模型请求失败，日志里有 401 或 Unauthorized

通常是 `api_key` 错了，或者 key 没有权限访问这个模型。

检查：

- `api_key` 是否完整复制。
- `model_name` 是否和平台展示完全一致。
- 当前账号是否已经订阅 `Qwen3_5-397B-A17B`。
- `endpoint_url` 是否填成了平台提供的完整接口地址。

### 10.7 模型请求失败，日志里有 404

通常是 `endpoint_url` 或 `model_name` 错了。

处理：

- 回到 `lpai-llm.lixiang.com` 查看服务详情。
- 确认 URL 是否需要包含 `/v1/chat/completions`。
- 确认模型名大小写、下划线、横线是否完全一致。

### 10.8 模型一直乱点或没有按任务做

优先改 `task_prompt.md`，不要急着改代码。

检查提示词是否说清楚：

- 要打开哪个 App。
- 要找什么信息。
- 一次要提取几条。
- 哪些操作禁止做。
- 什么情况下应该停止。

然后把 `--max-steps` 改小，先用 5 到 10 步调试。

### 10.9 模型看到的截图不对

打开最新运行目录里的 `screenshot/`。

如果截图本身就是黑屏、花屏、停在锁屏页或不是目标 App，问题在模拟器或 ADB 侧。

如果截图正常，但 `screenshot_anno/` 里的点击位置不合理，可能是模型理解错误、坐标输出异常或任务提示词不够明确。

## 11. 最推荐的日常开发流程

每次开始开发：

```bash
cd /Users/zhangchi1/Code/crawler-agent
source .venv/bin/activate
adb devices
```

确认模拟器在线后，进入你的任务目录：

```bash
ls tasks
```

修改任务提示词：

```bash
open -e tasks/你的任务名/task_prompt.md
```

小步运行：

```bash
bash tasks/你的任务名/run_task.sh
```

看结果：

```bash
open tasks/你的任务名
```

如果要新建任务，就在 `tasks/` 下创建新子目录。不要把多个不同任务混在同一个目录里。

推荐结构：

```text
tasks/
  demo_map_search/
    task_prompt.md
    run_task.sh
    2026-06-24_15-30-00/
      run_2026-06-24 15-30-00.log
      screenshot/
      screenshot_anno/
      llm-tracer/
      output.jsonl
```

这样每个任务的提示词、运行脚本、日志和截图都在同一个地方，后续复盘最方便。
