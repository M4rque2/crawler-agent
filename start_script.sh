#!/usr/bin/env bash
set -euo pipefail

TASK_DIR="tasks"

python run_agent.py \
    --model-config "model_config.json" \
    --system-prompt-path "system_prompt.md" \
    --task-prompt-path "$TASK_DIR/task_prompt.md" \
    --trace-dir "$TASK_DIR/traces/latest" \
    --max-steps 120 \
    --history-length 6
