# LLM Memory Gap and Missing-Content Parse Error Hint

## Case Summary
In this XHS note collection run, we intentionally performed a manual back navigation after the model had already emitted a click action.
This introduced a state mismatch between:
- what the model believed happened, and
- what the device UI state actually was.

Observed behavior:
- The model produced reasonable reasoning text about the failed tap attempt.
- The model did not produce a valid action JSON in assistant `content`.
- Framework parsing then failed because it expects a top-level JSON object in output text.

## Evidence from This Case
Run/log folder:
- tasks/xhs_note_collection/2026-05-27_08-55-21

Relevant trace:
- llm-tracer/llm_trace_20260527_085610_010362_c49535d5.json

Key response shape in that trace:
- `message.content`: null
- `message.reasoning`: "The previous tap on the top-left note card did not successfully open the detail"
- `message.tool_calls`: []

Related runtime error in run log:
- "Failed to parse model response: No top-level JSON object found in model output: The previous tap on the top-left note card did not successfully open the detail"

## Why It Happened (Current Understanding)
1. The framework has no independent persistent memory/state reconciliation layer.
2. It mainly relies on multi-turn chat context (images + prior assistant outputs) as working memory.
3. In non-stream mode, client fallback currently uses `reasoning` when `content` is null.
4. The parser expects JSON from the returned text; plain reasoning text is not parseable as required protocol output.

## Research Note
Treat this as a protocol-robustness gap under state drift conditions:
- State drift can be introduced by manual intervention, delayed UI effects, or action non-determinism.
- A model may provide valid internal reasoning but no executable action payload.
- Without a guard, reasoning text can be misrouted into the JSON parser path.

## TODO Candidates (Record Only, Not Implemented Yet)
- Add a strict output gate before parsing:
  - If `content` is null and `tool_calls` is empty, classify as invalid assistant action turn.
- Add explicit fallback policy:
  - Prefer controlled retry or a safe default action request instead of parsing raw reasoning text.
- Add state reconciliation hook:
  - Detect likely external/manual UI interventions and request a re-plan turn.
- Consider lightweight memory/state object:
  - Track expected UI transition after each action and compare with next screenshot cues.
- Improve telemetry:
  - Log a dedicated error type for "reasoning-only response" vs generic JSON parse failure.

## Notes
This document is intentionally a problem record and design hint only.
No behavior changes are applied yet.
