# vLLM GUI-Owl Coordinate Drift Investigation

## Status

Unresolved. Use llama.cpp / GGUF inference as the current workaround.

This note records the evidence from several local GUI-Owl-1.5-2B runs where the same Mobile-Agent loop produced usable coordinates with llama.cpp, but bad or inconsistent coordinates with vLLM serving the Hugging Face / ModelScope model.

## Affected Setup

- Agent repo: `D:\Mobile-Agent`
- Task family: `tasks\xhs_note_collection`
- vLLM model path:
  - `/home/marquez/.cache/modelscope/hub/models/iic/GUI-Owl-1___5-2B-Instruct`
- vLLM launch script:
  - `D:\vLLM_models\run_gui_owl_server.sh`
- llama.cpp model:
  - `D:\llama_models\GUI-Owl-1.5-2B-Instruct.Q8_0.gguf`
  - `D:\llama_models\GUI-Owl-1.5-2B-Instruct.mmproj-Q8_0.gguf`

The local agent expects GUI-Owl-style normalized action coordinates:

```text
x_norm, y_norm in [0, 1000]
x_device = x_norm / 1000 * display_width
y_device = y_norm / 1000 * display_height
```

This is implemented at the executor boundary and is believed to match Mobile-Agent-v3.5 / GUI-Owl-1.5 documentation.

## Key Runs

### vLLM, 3MP image budget, bad coordinate drift

Run:

```text
D:\Mobile-Agent\tasks\xhs_note_collection\2026-06-02_17-36-00
```

First action:

```text
Action: Click on the 小红书 app icon to open the application.
Raw coordinate: [193, 450]
Scaled coordinate: [278, 1404] on 1440x3120
```

Observed screenshot:

- The 小红书 icon center is around normalized `[616, 434]`.
- The model's `y` is plausible, but `x=193` lands near the left-side system app folder, not the 小红书 icon.

Trace metadata:

```text
provider: http-openai-compatible
model: GUI-Owl-1.5-2B-Instruct
system_fingerprint: vllm-0.22.0-616d47c3
prompt_tokens: 5378
```

### llama.cpp / GGUF, correct first coordinate

Run:

```text
D:\Mobile-Agent\tasks\xhs_note_collection\2026-06-02_17-55-25
```

First action:

```text
Action: Click on the 小红书 app icon to open the application.
Raw coordinate: [616, 434]
Scaled coordinate: [887, 1354] on 1440x3120
```

This lands on the visible 小红书 icon.

Trace metadata:

```text
provider: http-openai-compatible
model in request: gui-owl:1.5-2b-instruct-q8_0
response model: GUI-Owl-1.5-2B-Instruct
prompt_tokens: 6460
```

The llama.cpp run also initially failed after the first request when context was only 8192 tokens. That separate issue was fixed by increasing llama.cpp context size in:

```text
D:\llama_models\start_gui_owl_llamacpp.ps1
```

### vLLM, larger image budget, out-of-range / pixel-like coordinates

Run:

```text
D:\Mobile-Agent\tasks\xhs_note_collection\2026-06-02_18-16-12
```

The vLLM `longest_edge` value was changed from `3072000` to `16777216`.

First action:

```text
Action: Click the 小红书 app icon to open the application.
Raw coordinate: [1042, 668]
Error: coordinate is outside normalized 0-1000 coordinate space
```

Processor reproduction for the same screenshot and model:

```text
script_3mp:
  size: longest_edge=3072000, shortest_edge=65536
  image_grid_thw: [1, 160, 74]
  resized image estimate: 1184x2560

full_16mp:
  size: longest_edge=16777216, shortest_edge=65536
  image_grid_thw: [1, 196, 90]
  resized image estimate: 1440x3136
```

Under the full 16MP setting, `[1042, 668]` looks like a coordinate in near-original image pixels rather than normalized `[0, 1000]` coordinates.

### Explicit coordinate prompt still ignored

Run:

```text
D:\Mobile-Agent\tasks\traces\latest\run_2026-06-02 18-30-48.log
```

Clean first-turn prompt:

```text
Click the bottom-right corner of the screen at coordinate [990, 990].
```

Clean first-turn response:

```text
Action: Click the red "小红书" app icon to open the app.
Raw coordinate: [1043, 450]
```

The model ignored the explicit coordinate instruction and chose the visible 小红书 icon. Later turns were contaminated by the bad first action in chat history.

## vLLM Launch Script

Current script:

```text
D:\vLLM_models\run_gui_owl_server.sh
```

Relevant settings:

```bash
MAX_MODEL_LEN="${GUI_OWL_MAX_MODEL_LEN:-32768}"
SHORTEST_EDGE="${GUI_OWL_SHORTEST_EDGE:-65536}"
LONGEST_EDGE="${GUI_OWL_LONGEST_EDGE:-3072000}"
IMAGE_LIMIT='{"image":6}'
MAX_NUM_SEQS="${GUI_OWL_MAX_NUM_SEQS:-1}"

PIXEL_ARGS="{\"size\":{\"longest_edge\":$LONGEST_EDGE,\"shortest_edge\":$SHORTEST_EDGE}}"

vllm serve "$MODEL_ID" \
  --max-model-len "$MAX_MODEL_LEN" \
  --mm-processor-kwargs "$PIXEL_ARGS" \
  --limit-mm-per-prompt "$IMAGE_LIMIT" \
  --tensor-parallel-size 1 \
  --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" \
  --max-num-seqs "$MAX_NUM_SEQS" \
  --allowed-local-media-path '/'
```

The script matches the model README's public vLLM recommendation in spirit:

```bash
PIXEL_ARGS='{"size": {"longest_edge": 3072000, "shortest_edge": 65536}}'
IMAGE_LIMIT_ARGS='image=5'

vllm serve $CKPT \
    --max-model-len 32768 \
    --mm-processor-kwargs "$PIXEL_ARGS" \
    --limit-mm-per-prompt "$IMAGE_LIMIT_ARGS" \
    --tensor-parallel-size $MP_SIZE \
    --allowed-local-media-path '/' \
    --port 4243
```

However, the local model's own `preprocessor_config.json` says:

```json
{
  "size": {
    "longest_edge": 16777216,
    "shortest_edge": 65536
  }
}
```

Both tested size regimes have problems:

- `3072000`: model tends to output normalized-looking but wrong coordinates.
- `16777216`: model tends to output out-of-range, pixel-like coordinates.

## Current Hypotheses

These are plausible but not proven:

1. vLLM's Qwen3-VL / GUI-Owl processor path may not match the training/inference path expected by GUI-Owl for GUI action grounding.
2. The image budget strongly changes the visual token grid, which changes grounding behavior and possibly the coordinate frame the model emits.
3. vLLM may be exposing a different chat-template / multimodal placeholder path than llama.cpp for this GGUF conversion, even though both are OpenAI-compatible.
4. The Hugging Face / ModelScope checkpoint may naturally emit pixel-like coordinates under some processor sizes, while the llama.cpp conversion/template nudges it toward the documented 0-1000 coordinate protocol.
5. The agent's system prompt and task wrapper may make non-UI coordinate-only tests unreliable, because the model is asked to generate the next GUI move from the screenshot and can prefer visible UI elements.

## Evidence Against Agent-Side Scaling Being the Root Cause

The agent logs both raw and scaled action coordinates.

For vLLM:

```text
Raw:    [193, 450]
Scaled: [278, 1404] screen=1440x3120
```

For llama.cpp:

```text
Raw:    [616, 434]
Scaled: [887, 1354] screen=1440x3120
```

The scaler applies the same formula in both cases. The bad vLLM coordinate is already wrong before scaling. Therefore, the main issue is upstream of ADB execution.

## Workaround

Use llama.cpp / GGUF inference for local GUI-Owl-1.5-2B runs.

The llama.cpp startup script was updated to make multi-image history feasible:

```text
D:\llama_models\start_gui_owl_llamacpp.ps1
```

Important settings:

```powershell
[int]$ContextSize = 32768
[int]$Parallel = 1
[int]$ImageMinTokens = 1024
```

This avoids the earlier llama.cpp error:

```text
request (...) exceeds the available context size (8192 tokens)
```

## Future Investigation Ideas

1. Run a minimal single-image, single-question grounding benchmark outside the agent loop:

   ```text
   "Return only the coordinate of the center of the red 小红书 icon."
   ```

   Test vLLM at multiple image budgets and compare to llama.cpp.

2. Ask vLLM for both coordinate styles explicitly:

   ```text
   Return {"normalized_0_1000": [...], "image_pixel": [...]}.
   ```

3. Try disabling history images during vLLM tests so bad first actions do not poison later turns.

4. Compare exact rendered chat templates between vLLM and llama.cpp, including placement of image placeholders.

5. Test the official Hugging Face Transformers generation path directly using `AutoProcessor` and `Qwen3VLForConditionalGeneration`, bypassing vLLM.

6. Test whether `--mm-processor-kwargs` should be omitted so vLLM uses `preprocessor_config.json`, then add an output adapter for pixel-like coordinates if needed.

7. Check whether vLLM has a Qwen3-VL-specific issue around `image_grid_thw`, mRoPE, or spatial merge handling for tall phone screenshots.

8. Test smaller model prompts that do not mention opening apps when the task is a pure coordinate test.

## Practical Decision

For now, do not spend more time debugging vLLM coordinate drift in the main task loop.

Use llama.cpp as the local inference engine because it produced correct normalized first-click coordinates in the observed XHS run and is easier to keep within the agent's current 0-1000 coordinate protocol.
