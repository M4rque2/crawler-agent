# Stronger Swipe Calibration and Bounce Feedback Todo

## Context
In the XHS note collection run, the model repeatedly requested horizontal swipes to move between home-screen pages while searching for 小红书. A human observer could see the screen move slightly and then bounce back, which signals that the swipe gesture was too weak or did not cross the page-turn threshold.

The normal agent loop missed this clue because it only captures the next stable screenshot. By then, the animation has already bounced back and the screen looks unchanged. The LLM can infer that progress is not happening, but it cannot see the transient movement that explains why.

## Observed Evidence
- Run log: `./2026-05-27_14-49-31/run_2026-05-27 14-49-32.log`
- Repeated model swipes around `829 1666 -> 373 1666` or similar were intended to page left.
- Human observation: the screen moved a bit, then bounced back; the next screenshot looked unchanged.
- Manual ADB calibration on the same device:
  - `adb shell input swipe 729 1666 373 1666` did not work.
  - `adb shell input swipe 829 1666 273 1666` worked.
- Current device evidence for this issue was collected on a `1440x3120` screen.

## Implementation Todos
- Treat horizontal page swipes as requiring stronger distance than model-provided weak drags.
- Normalize likely page-navigation swipes to larger edge-biased gestures when the model requests a mostly horizontal swipe.
- Preserve the model's intended direction from start/end x coordinates.
- Preserve y coordinate near the model's requested y coordinate.
- Add optional post-action screenshot bursts for swipe actions, for example shortly after action start and again after settling.
- Detect transient movement followed by low final screen change as a likely bounce-back or weak swipe.
- Feed compact action feedback into LLM history, for example:
  - `last swipe moved briefly but bounced back; stronger swipe needed`
  - `last swipe produced no final screen change; likely boundary or weak gesture`
- Consider adaptive retry: if a weak swipe produces no final screen change, retry once with a stronger horizontal distance before spending another LLM turn.
- Record both the original model action and the actual executed strengthened action in trace output.

## Candidate First Heuristic
- If a swipe is mostly horizontal and its horizontal distance is less than about `45%` of screen width, expand it to about `60-70%` of screen width.
- For a left swipe:
  - use a start x near `80-85%` of screen width,
  - use an end x near `15-20%` of screen width.
- For a right swipe:
  - use a start x near `15-20%` of screen width,
  - use an end x near `80-85%` of screen width.
- Keep the y coordinate close to the model-provided y coordinate, clamped away from status/navigation bars when needed.
- Prefer executor-side strengthening over asking the LLM to guess exact ADB gesture distances.

## Test Plan
1. Re-run a controlled home-screen or XHS page swipe with the original weak command.
2. Re-run with the normalized stronger command.
3. Verify the stronger command changes page while the weak command does not.
4. Confirm the trace records:
   - original model action,
   - executed strengthened action,
   - action result summary.
5. Confirm the LLM history can include concise action-result feedback when a swipe bounces back.

## Assumptions
- This note is a development todo only, not the runtime implementation.
- The current manual evidence is from a `1440x3120` device.
- Future implementation should live primarily in the executor/action-observation layer, not only in prompt wording.
