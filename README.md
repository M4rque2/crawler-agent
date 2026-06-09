# GUI Agent

## Why This Repo Exists

Mobile-Agent is an early-stage research and engineering project for understanding and building GUI agents, with an initial focus on Android devices for crawling jobs.

### why not claude code, codex

We assume the reader is already familiar with coding agents such as Claude Code, Codex, Gemini CLI, or similar tools. Those agents are strong when the task can be solved by reading files, editing code, running commands, and checking tests. They can sometimes be forced into a GUI-agent style workflow by giving them computer-use tools: take a screenshot, inspect the interface, click, type, observe again, and continue.

But that is not what coding agents naturally optimize for. When they can solve a problem by writing code, calling an API, changing a file, or using a command-line shortcut, they usually will. That is often the right behavior for software engineering, but it is different from doing work through a graphical interface the way a human user does.

### why not GUI Agent
GUI agents are AI systems designed around that human-like interaction loop: observe the screen, understand the visible state, choose a UI action, execute it, then observe again. The interface is not a fallback when code access is unavailable; it is the primary environment.

Recent progress in multimodal models has made GUI agents more practical, but most current systems still target predefined task completion. A common objective is something like "send a message to Linda": the agent follows a mostly fixed sequence of steps toward one terminal goal. In programming terms, this often behaves like traversing a directed acyclic graph (DAG) of expected states and actions.

### spider agent
Our target is different. We want a crawler-style GUI agent that not only performs a specific operation, but also explores pages systematically and achieves meaningful coverage across the interface. This is closer to traversing an N-ary tree with branching paths, revisits, and coverage control. Existing agent infrastructure is hard to push into this behavior through prompt tuning alone, so this repository is built to develop the missing runtime and evaluation components for traversal-oriented mobile GUI agents.

## What We Done

Current completed foundations in this repository:

- **Action space.** We have implemented a practical action schema for mobile control, including click, swipe, type, system button operations, open app, and wait.
- **Observing system (`agent_io.py`).** We have implemented device interaction and observation utilities around ADB, including screenshot capture, UI hierarchy dump, device state checks, and action execution helpers.
- **Basic agent loop (`agent.py`).** We have implemented the core loop: observe screen, build messages, call multimodal model, parse structured response, execute one action, and continue step by step.
- **Log system for analysis.** We have implemented run logs and per-step artifacts (screenshots, annotated screenshots, and LLM traces) for debugging and post-run analysis.

## What Is Pending / What We Will Do

Current priority work items:

- **Action expectation and mismatch detection.** After each action, the agent should predict what observable change is expected in the next state (for example, page transition, popup disappearance, scroll displacement, or focus change). If the observed result does not match the expected result, the system should immediately raise attention and enter recovery mode. This is conceptually related to ReAct and Reflexion, but implemented inside one agent loop rather than split across separate executor and reflector agents.
- **Memory system.** We currently use chat history as memory only. A complete memory system is still missing and needs to be designed and implemented.
- **Automatic self-evolution system.** We plan to build a Hermes-like optimization loop so the agent can autonomously improve on common recurring tasks.
- **Advanced observe system.** In autonomous-driving style systems, observation often targets around 10 Hz refresh, while current multimodal inference is usually slower than 1 Hz. This means action updates can take several seconds per turn, which is not enough for high-frequency app interactions (for example short-video and game-like scenarios). We need an adaptive screenshot system to bridge this gap.
- **Coordinate scaling impact and necessity.** It is still unresolved whether coordinate scaling (for example normalized 0-1000 to device pixels) improves real task performance in our runtime. We need controlled A/B evaluation across app types (static pages, feeds, short-video, game-like pages), with metrics such as action success rate, no-op rate, correction/retry rate, and end-task completion. We should keep scaling only where it provides measurable benefit and avoid it where absolute-coordinate execution is more stable.

## Current Industrial Status

The industrial picture is moving quickly, but a rough pattern is visible.

OpenAI has official computer-use support. Its API documentation describes a `computer` tool where the model looks at screenshots, returns UI actions such as clicking, typing, or scrolling, and the client executes those actions in a browser or computer environment ([OpenAI Computer Use](https://developers.openai.com/api/docs/guides/tools-computer-use)). OpenAI also ships Codex workflows that can be steered from a phone, but the phone is used as a remote control and review surface for Codex work running elsewhere, not as evidence of a phone-GUI-use model that directly operates Android or iOS apps ([Work with Codex from anywhere](https://openai.com/index/work-with-codex-from-anywhere/)). I have not found an official OpenAI phone-use product comparable to the Android-focused systems below.

Anthropic is not only focused on coding. Claude has an official computer-use tool that provides screenshot, mouse, keyboard, and desktop automation capability through an agent loop ([Claude Computer Use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool)). This is important prior work, though it is framed around desktop environments rather than mobile phone control.

Google also has an official Gemini Computer Use capability. The Gemini API documentation describes browser-control agents that use screenshots and generate UI actions such as mouse clicks and keyboard input ([Gemini Computer Use](https://ai.google.dev/gemini-api/docs/computer-use)). This is strong evidence that Google is active in GUI automation, but the documented focus is browser/computer use rather than phone-use automation.

Chinese AI companies and labs appear especially active in mobile and general GUI agents:

- **Alibaba / Qwen ecosystem:** GUI-Owl and Mobile-Agent-v3 target GUI automation across desktop and mobile environments, with reported results on AndroidWorld and OSWorld ([Mobile-Agent-v3 / GUI-Owl](https://arxiv.org/abs/2508.15144)).
- **ByteDance:** UI-TARS is an open-source multimodal GUI agent line for automated GUI interaction; the project describes UI-TARS-1.5 and UI-TARS-2 as agent models for GUI, game, code, and tool-use tasks ([UI-TARS](https://github.com/bytedance/UI-TARS)).
- **OpenCUA / Meituan-related work:** OpenCUA provides open foundations for computer-use agents, including AgentNet data/tooling. Its repository also acknowledges contributions from the Meituan EvoCUA team for vLLM integration ([OpenCUA](https://github.com/xlang-ai/OpenCUA)).
- **Zhipu / Z.ai:** AutoGLM explicitly focuses on web browser and Android GUI scenarios as foundation-agent environments for real-world GUI interaction ([AutoGLM](https://www.zhipuai.cn/v1/autoglm)).

So the corrected view is: the top-tier U.S. labs are active in computer and browser use, while the strongest public emphasis on phone-use and Android GUI agents currently seems to come from Chinese teams and open research projects.

Smartphone GUI agents still appear less researched and less mature than desktop or browser agents. That gap is the main reason this repository starts with mobile, and especially Android. Phones contain many of the repetitive GUI workflows we actually want to automate, but they also add constraints that make the problem harder: small screens, touch gestures, app switching, mobile keyboards, permissions, dynamic layouts, and deeply stateful apps.

This project will focus on that smartphone-agent gap.

## Expected Agent Loop

The current runtime loop in this repository is:

1. Preflight device state (wake, unlock, return to home page).
2. Capture a screenshot from the Android device.
3. Build multimodal messages from instruction plus recent step history.
4. Invoke an OpenAI-compatible multimodal endpoint.
5. Parse one structured turn response (`navigate` / `extract` / `quit`).
6. If `navigate`, execute one UI action (tap/swipe/type/open/wait/system key).
7. Save step artifacts (raw screenshot, annotated screenshot, LLM traces, run log).
8. Continue until `quit` or step limit.

App opening is action-driven: the agent opens apps when the model emits `action=open`.

## Current Runtime Architecture

Current core modules:

- `run_agent.py`: runner entrypoint; parses args, creates task log directories, enables dual logging (stdout + file), creates model client, and starts the loop.
- `agent.py`: message construction and main agent loop orchestration.
- `agent_io.py`: ADB actions, state preflight helpers, action execution, and response parsing.
- `llm_client.py`: OpenAI-compatible multimodal client and LLM trace logging.
- `logs.py`: per-run task directory creation and tee-style logging setup.
- `app_name_to_package.py`: app alias to package mapping utilities used by `open` action.

The architecture is intentionally modular, but the end-to-end flow is already wired and runnable.

## Repository Structure

Current top-level structure includes:

```text
Mobile-Agent/
  README.md
  run_agent.py
  agent.py
  agent_io.py
  llm_client.py
  logs.py
  app_name_to_package.py
  app_name_to_package.json
  research_notes/      # Investigation notes, empirical findings, and future implementation TODOs
  tasks/               # Task prompts + run scripts + per-run artifacts
  references/          # Third-party reference implementations for study
```

Per-run artifacts are created under task run directories (often via `--trace-dir`) with this layout:

```text
<task-run-root>/
  run_YYYY-mm-dd HH-MM-SS.log
  screenshot/
  screenshot_anno/
  llm-tracer/
```

## External References

To speed up research and avoid reinventing baseline patterns, we keep third-party references under `references/` for local study.

- `references/gui-agent/`: mobile and GUI-agent implementations used to study action schemas, prompting, device control, tracing, and benchmark integration.
- `references/coding-agent/`: coding-agent frameworks used to study planning loops, tool use conventions, recovery behavior, and execution harness patterns that may transfer to GUI-agent systems.
- `references/claw-agent/`: ClawGUI-related references and supporting materials.

Current coding-agent references include:

- `references/coding-agent/claude-code/`
- `references/coding-agent/DeepSeek-TUI/`

These reference folders are for analysis and design inspiration. We should extract ideas into our own architecture and docs instead of copying code directly.

## Research Notes

We keep investigation notes, empirical findings, unresolved design questions, and future implementation TODOs under `research_notes/`.

These notes are lightweight records from real runs and framework research. They are meant to preserve evidence and design direction without immediately changing runtime behavior.


## License

See [LICENSE](LICENSE).
