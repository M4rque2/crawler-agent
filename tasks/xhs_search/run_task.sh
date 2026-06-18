#!/usr/bin/env bash
set -euo pipefail

TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${TASK_DIR}/../.." && pwd)"
RUN_TS="$(date +"%Y-%m-%d_%H-%M-%S")"
TRACE_DIR="${TASK_DIR}/${RUN_TS}"

cd "${REPO_DIR}"

python run_agent.py \
    --model-config "model_config.json" \
    --system-prompt-path "system_prompt.md" \
    --task-prompt-path "${TASK_DIR}/task_prompt.md" \
    --trace-dir "${TRACE_DIR}" \
    --max-steps 120 \
    --history-length 6
