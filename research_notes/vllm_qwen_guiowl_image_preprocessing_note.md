# vLLM Qwen / GUI-Owl Image Preprocessing Note

## Context

This note records the current investigation around image resolution handling for:

- `Qwen/Qwen3.5-397B-A17B`
- `mPLUG/GUI-Owl-1.5-8B-Instruct`
- this repository's agent screenshot path when vLLM is the assumed backend inference engine.

The practical question was whether the agent code should resize/compress screenshots before sending them to the model, or whether vLLM/model-side preprocessing should own that behavior.

## Current Conclusion

When vLLM is the backend engine, this repository should send the original screenshot image to the backend and should not implement model-specific image resizing in the agent code path.

Reasoning:

1. Image preprocessing is model-specific.
2. Qwen-family VL models use processor-specific pixel budgets and effective visual-token block sizes.
3. vLLM uses the model's Hugging Face multimodal processor path and can receive processor options such as `--mm-processor-kwargs`.
4. Those settings may change across model families and releases.
5. Agent-side resizing risks using stale assumptions, such as applying Qwen2.5-style `28x28` logic to a Qwen3/Qwen3.5-style model.

Therefore:

- The agent should pass the original screenshot pixels to the vLLM/OpenAI-compatible backend.
- vLLM/model processor should handle resizing, patching, and image-token budgeting.
- ADB execution should scale normalized model actions to actual device display pixels, independent of any image preprocessing.

## Qwen3.5-397B-A17B Findings

Model card:

```text
https://huggingface.co/Qwen/Qwen3.5-397B-A17B
```

Config:

```text
https://huggingface.co/Qwen/Qwen3.5-397B-A17B/blob/main/config.json
```

Observed findings:

- The model card presents this as an image-text-to-text model and shows use with an OpenAI-compatible vLLM server.
- The model uses a Qwen3.5 VL-style multimodal processor path.
- The config includes vision settings equivalent to:

```text
patch_size = 16
spatial_merge_size = 2
```

So the effective visual-token block size is:

```text
16 * 2 = 32
```

Meaning one visual token corresponds roughly to a `32x32` input-pixel block after the processor's patching/merging logic.

The important engineering implication is that Qwen3.5-style image preprocessing is not the same as Qwen2/Qwen2.5's commonly discussed `28x28` effective visual-token block.

## GUI-Owl-1.5 Findings

Model card:

```text
https://huggingface.co/mPLUG/GUI-Owl-1.5-8B-Instruct
```

Config:

```text
https://huggingface.co/mPLUG/GUI-Owl-1.5-8B-Instruct/blob/main/config.json
```

Observed findings:

- The model is based on Qwen3-VL.
- The config reports:

```text
model_type = qwen3_vl
architectures = ["Qwen3VLForConditionalGeneration"]
patch_size = 16
spatial_merge_size = 2
```

So GUI-Owl-1.5 also has an effective visual-token block size of:

```text
32x32 pixels
```

The model card recommends vLLM deployment with explicit multimodal processor kwargs:

```bash
PIXEL_ARGS='{"size": {"longest_edge": 3072000, "shortest_edge": 65536}}'

vllm serve $CKPT \
    --max-model-len 32768 \
    --mm-processor-kwargs "$PIXEL_ARGS" \
    --limit-mm-per-prompt "image=5"
```

This corresponds to a recommended image pixel budget of approximately:

```text
min_pixels = 65,536
max_pixels = 3,072,000
factor ~= 32
```

In visual-token terms:

```text
65,536 / (32 * 32) = 64 visual tokens
3,072,000 / (32 * 32) = 3000 visual tokens
```

## Difference From Old Local smart_resize Logic

Older Qwen2/Qwen2.5-style code often used:

```python
factor = 28
```

with pixel budgets such as:

```text
min_pixels = 4 * 28 * 28
max_pixels = 1280 * 28 * 28
```

That is appropriate for Qwen2/Qwen2.5-style effective visual-token block accounting, but it is not the natural setting for Qwen3, Qwen3.5, or GUI-Owl-1.5.

For Qwen3/Qwen3.5/GUI-Owl-1.5, a model-side processor should use `32x32`-style accounting, and GUI-Owl-1.5 specifically documents its recommended vLLM processor kwargs.

This is the main reason the agent code should avoid baking in `factor=28`, `factor=32`, or model-specific pixel limits.

## Recommended Codebase Policy

### Image Path

Do:

- capture the screenshot at original device resolution;
- send that original screenshot to the backend inference server;
- let vLLM and the model processor resize/repatch/rebudget the image.

Do not:

- locally resize the screenshot just because a previous model used a specific factor;
- assume all Qwen-family VL models share the same effective visual-token block size;
- mix image resize dimensions into ADB action execution.

### Action Path

The action path is separate from the image preprocessing path.

The model should output normalized coordinates in the agreed protocol, currently:

```text
0-1000 coordinate space
```

The agent should convert those coordinates to the actual device display size:

```python
x_device = x_norm / 1000 * device_width
y_device = y_norm / 1000 * device_height
```

The `device_width` and `device_height` should come from ADB display resolution, not from the image size seen by the model after preprocessing.

## Infra Checklist

If vLLM serves GUI-Owl-1.5, ask the infra team to confirm whether they use the model card's recommended argument:

```bash
--mm-processor-kwargs '{"size": {"longest_edge": 3072000, "shortest_edge": 65536}}'
```

If vLLM serves Qwen3.5-397B-A17B, ask whether any `--mm-processor-kwargs` override is set. If no override is set, vLLM should use the model processor defaults.

Either way, this choice belongs to the inference server/model deployment layer, not to the local mobile agent loop.

## Final Engineering Rule

For this repository:

```text
Send original screenshots to vLLM.
Let vLLM/model processor handle image resolution.
Scale action coordinates using device display resolution.
Keep image preprocessing and ADB action execution as separate concerns.
```
