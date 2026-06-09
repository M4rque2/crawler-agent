# Coordinate Scaling History and Resolution Note

## Context

This note records the current investigation result for:

- why MobileAgent uses coordinate scaling rules,
- which versions use 0-1000 normalized action coordinates,
- what primary evidence supports the convention,
- how this repository currently handles screenshot size and action coordinates.

## Current Conclusion

This is no longer considered an unresolved research question.

The strongest conclusion is:

1. The 0-1000 coordinate convention is a Qwen-style visual grounding/action convention, not an actual 1000x1000 screenshot resolution.
2. Qwen-VL official documentation describes grounding coordinates as normalized values in the 0-1000 range.
3. GUI-Owl 1.5 official documentation says GUI-Owl 1.5 outputs relative coordinates (0-1000) by default for both mobile and computer use.
4. Mobile-Agent-v3.5 official mobile/computer runners scale those relative coordinates to real screen pixels before execution.
5. Therefore, it is reasonable to treat the 0-1000 action space as inherited from the Qwen VL grounding family and carried into GUI-Owl / Mobile-Agent GUI action protocols.

The papers and reports still do not appear to include a dedicated theory section explaining "why exactly 1000 instead of another normalization base." However, the official documentation and implementation evidence are now strong enough for engineering purposes:

- use 0-1000 as the model-facing action coordinate space when following the upstream Mobile-Agent-v3.5 / GUI-Owl 1.5 protocol;
- scale to actual device or computer pixels at the executor boundary;
- do not describe the screenshot itself as literally 1000x1000 unless the runtime truly sends such an image.

## Primary Evidence

### 1. Qwen-VL uses normalized grounding coordinates

The Qwen-VL README documents visual grounding boxes using normalized coordinates in the 0-1000 range. This provides the historical model-family basis for using 1000-space coordinates in GUI grounding/action tasks.

Source:

```text
https://github.com/QwenLM/Qwen-VL
```

Observed meaning:

- Qwen VL models are trained/instructed to express spatial locations in a normalized coordinate frame.
- The 0-1000 space is a model-facing representation, independent of the original image pixel size.

### 2. GUI-Owl 1.5 explicitly outputs 0-1000 relative coordinates

The Mobile-Agent-v3.5 README states:

```text
GUI-Owl 1.5 outputs relative coordinates (0-1000) by default.
```

It states this in both the mobile and computer deployment sections.

Source:

```text
https://github.com/X-PLUG/MobileAgent/tree/main/Mobile-Agent-v3.5
```

Observed meaning:

- For GUI-Owl 1.5, 0-1000 relative coordinates are the official default output protocol.
- This applies to GUI automation across mobile and computer environments.

### 3. Mobile-Agent-v3.5 code scales 0-1000 coordinates to pixels

The official Mobile-Agent-v3.5 mobile and computer runners convert normalized coordinates into actual pixels with the pattern:

```python
x = coordinate_x / 1000 * width
y = coordinate_y / 1000 * height
```

Observed locations in the local reference checkout:

- `references/gui-agent/MobileAgent/Mobile-Agent-v3.5/mobile_use/run_gui_owl_1_5_for_mobile.py`
- `references/gui-agent/MobileAgent/Mobile-Agent-v3.5/computer_use/run_gui_owl_1_5_for_pc.py`
- `references/gui-agent/MobileAgent/Mobile-Agent-v3.5/android_world_v3.5/android_world/agents/mobile_agent_v3.py`

Observed meaning:

- The model outputs relative coordinates.
- The executor maps them to the current screenshot or screen resolution.
- The scaling boundary is part of the intended framework design.

### 4. Mobile-Agent-v3 also documents and implements the same mapping

Mobile-Agent-v3 README says models such as Qwen-VL-2 / Qwen-VL-3 may output relative coordinates from 0 to 1000, and the `qwen-vl` coordinate type maps those coordinates to the actual device resolution.

Observed locations in the local reference checkout:

- `references/gui-agent/MobileAgent/Mobile-Agent-v3/README.md`
- `references/gui-agent/MobileAgent/Mobile-Agent-v3/mobile_v3/run_mobileagentv3.py`

Observed meaning:

- The 0-1000 convention predates v3.5 in the Mobile-Agent tree.
- v3.5 makes it the explicit default for GUI-Owl 1.5.

## Why 1000x1000 Should Be Read As Action Space

The phrase:

```text
The screen's resolution is 1000x1000.
```

is best interpreted as shorthand for:

```text
Use normalized action coordinates in a 0-1000 coordinate frame.
```

It should not be interpreted as:

- the physical phone resolution,
- the computer display resolution,
- the actual screenshot size sent to the model,
- proof that the image was resized to 1000x1000 pixels.

The practical rationale for 0-1000 is:

- resolution independence across phones, browsers, and desktops;
- aspect-ratio independence when combined with per-axis scaling;
- integer output with enough precision for UI actions;
- consistency with Qwen VL visual grounding data and prompting conventions.

## Version History Summary

1. Mobile-Agent-v1/v2 did not primarily use the 0-1000 GUI-Owl-style action protocol:
   - v1 mainly used normalized ratio-to-screen conversion;
   - v2 mainly executed absolute pixel coordinates from action space.
2. Mobile-Agent-v3 explicitly supports 0-1000 coordinates for Qwen-style VL models and maps them to actual device resolution.
3. Mobile-Agent-v3.5 / GUI-Owl 1.5 documents 0-1000 relative coordinates as the default output convention.

## Local Runtime Update

As of the current local implementation, this repository follows the upstream-compatible 0-1000 action-coordinate path again:

- `agent.py` prompts the model to output normalized action coordinates in `[0, 1000]`.
- `llm_client.py:image_to_data_url()` sends the screenshot at its original pixel resolution instead of resizing it with `smart_resize`.
- `agent_io.py:rescale_coordinates()` scales model coordinates with `x / 1000 * width` and `y / 1000 * height`.
- `agent.py` logs both `[ACTION RAW]` normalized model output and `[ACTION SCALED]` executed device-pixel action.
- `agent.py` executes and annotates only the scaled device-pixel action.

The local implementation is intentionally strict: coordinate-bearing actions outside `[0, 1000]` are rejected instead of guessed as absolute pixels. This avoids the old mixed-coordinate failure mode.

The current screenshot path still differs from some upstream Qwen-style examples because it sends original-resolution screenshots rather than applying `smart_resize`. That is acceptable as long as the model-facing action coordinate frame remains normalized 0-1000 and is not described as screenshot pixels.

## Historical Local Inconsistency

The old local runtime had a mismatch:

- ADB captured screenshots at physical device resolution.
- The LLM request resized screenshots with Qwen-style `smart_resize`, preserving aspect ratio rather than producing 1000x1000 images.
- The prompt said "The screen's resolution is 1000x1000."
- The executor accepted both normalized 0-1000 coordinates and absolute-looking coordinates.

For one XHS run, this caused mixed coordinate behavior:

```text
Step 1 model output: [496, 939]
Executed action:     [714, 2929]
```

This was treated as normalized 0-1000 and scaled to a 1440x3120 screenshot.

```text
Step 2 model output:  [793, 1648]
Step 2 model output2: [229, 1648]
Executed action:      [793, 1648] -> [229, 1648]
```

Here `y=1648` violated the 0-1000 normalized protocol, but because it was still inside the physical screenshot height, the executor treated it as absolute pixels.

The lesson is not that 0-1000 is unjustified. The lesson is that the prompt, screenshot path, model expectation, executor scaling, and logs must agree on one coordinate protocol.

## Engineering Decision

There are two valid runtime policies:

### A. Upstream-compatible GUI-Owl / Qwen VL protocol

Use this when relying on GUI-Owl 1.5 or Qwen-style GUI grounding behavior.

- Prompt: "Use normalized action coordinates in [0, 1000] on both axes."
- Screenshot: may be resized for model input, but the action coordinate frame remains 0-1000.
- Executor: scale `x / 1000 * width`, `y / 1000 * height`.
- Logs: record raw normalized coordinates and executed pixel coordinates.

### B. Absolute-pixel local protocol

Use this when the target model is better at direct pixel actions for the exact screenshot sent.

- Prompt: include the actual screen resolution.
- Screenshot: send original resolution or clearly state the image size used for coordinates.
- Executor: execute coordinates directly.
- Logs: record screenshot size and executed coordinates.

The current local repository is following policy A. Policy B remains a possible future experiment for models that are demonstrably better at direct pixel actions.

## Resolved Status

The prior "unresolved" status is closed.

Resolved conclusion:

```text
The 0-1000 action space is an upstream Qwen-style normalized grounding/action convention.
GUI-Owl 1.5 explicitly uses it by default.
Mobile-Agent-v3.5 implements it by scaling normalized coordinates to real pixels.
This local repository currently follows that upstream protocol with strict normalized-coordinate validation.
```
