from __future__ import annotations

import os
from pathlib import Path

TZ = "Asia/Tokyo"

def workspace_dir() -> Path:
    raw = os.environ.get("OPENCLAW_WORKSPACE") or os.path.expanduser(
        "~/.openclaw/workspace"
    )
    return Path(raw).expanduser().resolve()


def tasks_root() -> Path:
    raw = os.environ.get("OC_TASKS_ROOT") or os.path.expanduser("~/Documents/ai_tasks")
    root = Path(raw).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def requests_root() -> Path:
    return tasks_root()


def runtime_dir() -> Path:
    path = workspace_dir() / ".pipeline-runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def index_path() -> Path:
    return requests_root() / "index.json"


def inbox_path(session_key: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "._-+@" else "_" for ch in session_key)
    return runtime_dir() / "inbox" / f"{safe}.json"


OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
PLANNER_MODEL = os.environ.get(
    "OC_PLANNER_MODEL", "qwen3.5:9b"
)
VISION_MODEL = os.environ.get("OC_VISION_MODEL", "qwen2.5vl:7b")
LOG_ROTATE_BYTES = int(os.environ.get("OC_LOG_ROTATE_BYTES", str(20 * 1024 * 1024)))
SIMILAR_THRESHOLD = float(os.environ.get("OC_SIMILAR_THRESHOLD", "0.22"))
