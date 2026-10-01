from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .paths import TZ, index_path, requests_root

STAGES = (
    "ask_similar",
    "planning",
    "awaiting_approval",
    "replanning",
    "vision",
    "executing",
    "done",
)


def now() -> datetime:
    return datetime.now(ZoneInfo(TZ))


def stamp(dt: datetime | None = None) -> str:
    return (dt or now()).strftime("%Y%m%d%H%M%S")


def iso(dt: datetime | None = None) -> str:
    return (dt or now()).isoformat(timespec="seconds")


def load_index() -> dict[str, Any]:
    path = index_path()
    if not path.exists():
        return {"sessions": {}, "requests": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_index(data: dict[str, Any]) -> None:
    path = index_path()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def request_dir(request_id: str) -> Path:
    return requests_root() / request_id


def state_path(request_id: str) -> Path:
    return request_dir(request_id) / "state.json"


def record_path(request_id: str) -> Path:
    return request_dir(request_id) / f"{request_id}.md"


def load_state(request_id: str) -> dict[str, Any]:
    path = state_path(request_id)
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(state: dict[str, Any]) -> None:
    request_id = state["id"]
    path = state_path(request_id)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    index = load_index()
    found = False
    for item in index["requests"]:
        if item["id"] == request_id:
            item.update(_index_row(state))
            found = True
            break
    if not found:
        index["requests"].append(_index_row(state))
    if state.get("session_key"):
        index["sessions"][state["session_key"]] = {
            "request_id": request_id,
            "stage": state.get("stage"),
        }
    save_index(index)


def _index_row(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": state["id"],
        "dir": str(request_dir(state["id"])),
        "summary": (state.get("summary") or "")[:240],
        "created_at": state.get("created_at"),
        "stage": state.get("stage"),
        "session_key": state.get("session_key"),
    }


def session_request(session_key: str) -> dict[str, Any] | None:
    if not session_key:
        return None
    index = load_index()
    binding = index.get("sessions", {}).get(session_key)
    if not binding:
        return None
    request_id = binding.get("request_id")
    if not request_id or not state_path(request_id).exists():
        return None
    state = load_state(request_id)
    if state.get("stage") == "done":
        return None
    return state


def unbind_session(session_key: str) -> None:
    if not session_key:
        return
    index = load_index()
    index.get("sessions", {}).pop(session_key, None)
    save_index(index)


def unique_id() -> str:
    base = stamp()
    candidate = base
    n = 2
    while request_dir(candidate).exists():
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def create_request(
    *,
    text: str,
    session_key: str,
    sender: str = "",
    channel: str = "slack",
    media: list[dict[str, Any]] | None = None,
    kind: str = "new",
) -> dict[str, Any]:
    request_id = unique_id()
    root = request_dir(request_id)
    for sub in ("input", "vision", "output"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    copied = _copy_media(root / "input", media or [])
    state = {
        "id": request_id,
        "created_at": iso(),
        "updated_at": iso(),
        "session_key": session_key,
        "sender": sender,
        "channel": channel,
        "kind": kind,
        "stage": "planning",
        "summary": text.strip().replace("\n", " ")[:240],
        "has_images": any(_is_image(item) for item in copied),
        "media": copied,
        "similar": [],
        "parent_id": None,
        "vision_done": False,
        "approved_plan": None,
        "last_user_text": text.strip(),
    }
    save_state(state)
    record_path(request_id).write_text(
        _initial_markdown(state, text),
        encoding="utf-8",
    )
    return state


def attach_media(request_id: str, media: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not media:
        return []
    state = load_state(request_id)
    copied = _copy_media(request_dir(request_id) / "input", media)
    existing = {item.get("stored") for item in state.get("media") or []}
    for item in copied:
        if item.get("stored") not in existing:
            state.setdefault("media", []).append(item)
    state["has_images"] = any(_is_image(item) for item in state.get("media") or [])
    state["updated_at"] = iso()
    save_state(state)
    return copied


def append_markdown(request_id: str, heading: str, body: str) -> None:
    path = record_path(request_id)
    block = f"\n\n## {heading} ({iso()})\n\n{body.rstrip()}\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(block)
    state = load_state(request_id)
    state["updated_at"] = iso()
    save_state(state)


def set_stage(request_id: str, stage: str, **extra: Any) -> dict[str, Any]:
    if stage not in STAGES:
        raise ValueError(f"unknown stage: {stage}")
    state = load_state(request_id)
    state["stage"] = stage
    state["updated_at"] = iso()
    state.update(extra)
    save_state(state)
    return state


def _is_image(item: dict[str, Any]) -> bool:
    ctype = (item.get("contentType") or "").lower()
    name = (item.get("stored") or item.get("path") or "").lower()
    if ctype.startswith("image/"):
        return True
    return name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".heic"))


def _copy_media(dest: Path, media: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dest.mkdir(parents=True, exist_ok=True)
    copied: list[dict[str, Any]] = []
    for index, item in enumerate(media, start=1):
        src = item.get("path") or item.get("url")
        if not src:
            continue
        src_path = Path(str(src)).expanduser()
        if not src_path.exists() or not src_path.is_file():
            copied.append(
                {
                    "source": str(src),
                    "stored": None,
                    "contentType": item.get("contentType"),
                    "missing": True,
                }
            )
            continue
        name = f"{index:02d}_{src_path.name}"
        target = dest / name
        if src_path.resolve() != target.resolve():
            shutil.copy2(src_path, target)
        copied.append(
            {
                "source": str(src_path),
                "stored": str(target),
                "contentType": item.get("contentType") or "",
                "missing": False,
            }
        )
    return copied


def _initial_markdown(state: dict[str, Any], text: str) -> str:
    media_lines = []
    for item in state.get("media") or []:
        media_lines.append(f"- `{item.get('stored') or item.get('source')}`")
    media_block = "\n".join(media_lines) if media_lines else "- （添付なし）"
    return (
        f"# リクエスト {state['id']}\n\n"
        f"- 受付: {state['created_at']}\n"
        f"- 経路: {state.get('channel') or 'unknown'}\n"
        f"- 送信者: {state.get('sender') or 'unknown'}\n"
        f"- 種別: {state.get('kind')}\n"
        f"- 画像あり: {'yes' if state.get('has_images') else 'no'}\n\n"
        f"## リクエスト内容\n\n{text.strip() or '（本文なし・添付のみ）'}\n\n"
        f"## 入力ファイル\n\n{media_block}\n"
    )
