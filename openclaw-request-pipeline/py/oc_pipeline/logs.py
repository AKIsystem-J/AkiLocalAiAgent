from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .paths import LOG_ROTATE_BYTES, TZ
from .store import request_dir


def _stamp() -> str:
    return datetime.now(ZoneInfo(TZ)).strftime("%Y-%m-%d %H:%M:%S")


def current_log(request_id: str) -> Path:
    root = request_dir(request_id)
    existing = sorted(root.glob(f"{request_id}_[0-9][0-9][0-9][0-9].log"))
    if existing:
        latest = existing[-1]
        if latest.stat().st_size < LOG_ROTATE_BYTES:
            return latest
        next_n = int(latest.stem.rsplit("_", 1)[-1]) + 1
    else:
        next_n = 1
    return root / f"{request_id}_{next_n:04d}.log"


def append_log(request_id: str, message: str, *, level: str = "INFO") -> str:
    path = current_log(request_id)
    line = f"[{_stamp()}] [{level}] {message.rstrip()}\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        if path.stat().st_size >= LOG_ROTATE_BYTES:
            nxt = request_dir(request_id) / (
                f"{request_id}_{int(path.stem.rsplit('_', 1)[-1]) + 1:04d}.log"
            )
            nxt.touch(exist_ok=True)
    return str(path)
