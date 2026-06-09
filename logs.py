"""Task log directory helpers for GUI-agent runs.

This module creates the per-task directory layout used by GUI-agent tasks:
- task root directory named by start time
- screenshot/
- screenshot_anno/
- llm-tracer/
"""

from datetime import datetime
from pathlib import Path
import io
import sys


_ORIGINAL_STDOUT = sys.stdout
_ORIGINAL_STDERR = sys.stderr
_LOG_FILE_HANDLE = None


class _TeeTextIO(io.TextIOBase):
    def __init__(self, primary, secondary):
        self._primary = primary
        self._secondary = secondary

    def write(self, s):
        self._primary.write(s)
        self._secondary.write(s)
        return len(s)

    def flush(self):
        self._primary.flush()
        self._secondary.flush()

    def isatty(self):
        try:
            return self._primary.isatty()
        except Exception:
            return False


def _task_start_dir_name(start_time: datetime | None = None) -> str:
    timestamp = start_time or datetime.now()
    return timestamp.strftime("%Y-%m-%d %H-%M-%S")

def make_task_log_dirs(trace_dir: str | None = None, *, start_time: datetime | None = None) -> dict[str, str]:
    if trace_dir:
        task_root = Path(trace_dir)
    else:
        task_root = Path(_task_start_dir_name(start_time))

    screenshot_dir = task_root / "screenshot"
    screenshot_anno_dir = task_root / "screenshot_anno"
    llm_tracer_dir = task_root / "llm-tracer"

    for directory in (task_root, screenshot_dir, screenshot_anno_dir, llm_tracer_dir):
        directory.mkdir(parents=True, exist_ok=True)

    return {
        "task_root": str(task_root),
        "screenshot_dir": str(screenshot_dir),
        "screenshot_anno_dir": str(screenshot_anno_dir),
        "llm_tracer_dir": str(llm_tracer_dir),
    }


def enable_dual_logging(task_root: str, *, start_time: datetime | None = None) -> str:
    """Mirror stdout/stderr to both terminal and a task log file."""
    global _LOG_FILE_HANDLE

    timestamp = _task_start_dir_name(start_time)
    log_path = Path(task_root) / f"run_{timestamp}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    _LOG_FILE_HANDLE = log_path.open("a", encoding="utf-8", buffering=1)
    sys.stdout = _TeeTextIO(_ORIGINAL_STDOUT, _LOG_FILE_HANDLE)
    sys.stderr = _TeeTextIO(_ORIGINAL_STDERR, _LOG_FILE_HANDLE)
    return str(log_path)