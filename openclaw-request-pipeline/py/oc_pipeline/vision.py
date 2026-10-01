from __future__ import annotations

import base64
import fcntl
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .logs import append_log
from .paths import OLLAMA_URL, PLANNER_MODEL, VISION_MODEL
from .store import append_markdown, load_state, request_dir, save_state, set_stage

VISION_PROMPT = """あなたは書類・画像の構造化抽出器です。
画像の内容だけを根拠に、次のJSONだけを出力してください。前後に説明文やコードフェンスを付けないでください。

{
  "source_file": "ファイル名",
  "document_type": "receipt|invoice|table|form|photo|screenshot|other",
  "title": "",
  "date": "",
  "vendor": "",
  "items": [
    {"label": "", "value": "", "unit": "", "class": "amount|qty|date|text|other"}
  ],
  "amounts": [
    {"label": "", "value": 0, "currency": "JPY"}
  ],
  "notes": "",
  "raw_text": ""
}

数値は半角。読めない欄は空文字か null。推測で埋めない。
"""


def _ollama_chat(payload: dict[str, Any], timeout: int = 180) -> dict[str, Any]:
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", raw, re.S)
    if match:
        data = json.loads(match.group(0))
        if isinstance(data, dict):
            return data
    return {"parse_error": True, "raw_text": raw}


def _unload(model: str) -> None:
    payload = {"model": model, "keep_alive": 0}
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except (urllib.error.URLError, TimeoutError):
        return


def _usable_result(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("error") or data.get("parse_error"):
        return None
    return data


def _image_files(request_id: str) -> list[Path]:
    input_dir = request_dir(request_id) / "input"
    if not input_dir.exists():
        return []
    files = []
    for path in sorted(input_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in {
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".gif",
            ".bmp",
        }:
            files.append(path)
    return files


def analyze_request(request_id: str) -> dict[str, Any]:
    state = load_state(request_id)
    set_stage(request_id, "vision")
    files = _image_files(request_id)
    vision_dir = request_dir(request_id) / "vision"
    vision_dir.mkdir(parents=True, exist_ok=True)
    lock_path = vision_dir / ".vision.lock"
    lock_fp = lock_path.open("w")
    try:
        fcntl.flock(lock_fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return {"ok": False, "error": "vision already running", "state": state}
    lock_fp.write(str(request_id))
    lock_fp.flush()
    try:
        return _analyze_locked(request_id, state, files, vision_dir)
    finally:
        try:
            fcntl.flock(lock_fp.fileno(), fcntl.LOCK_UN)
            lock_fp.close()
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass


def _analyze_locked(
    request_id: str,
    state: dict[str, Any],
    files: list[Path],
    vision_dir: Path,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    append_log(request_id, f"vision start model={VISION_MODEL} files={len(files)}")
    _unload(PLANNER_MODEL)
    if not files:
        merged = {"file_count": 0, "files": [], "note": "no images"}
        (vision_dir / "vision.json").write_text(
            json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        state = set_stage(request_id, "executing", vision_done=True)
        return {"ok": True, "merged": merged, "state": state}

    for index, path in enumerate(files, start=1):
        out = vision_dir / f"{index:02d}_{path.stem}.json"
        cached = _usable_result(out)
        if cached is not None:
            append_log(request_id, f"vision file {index}/{len(files)} {path.name} (cached)")
            results.append(cached)
            continue
        append_log(request_id, f"vision file {index}/{len(files)} {path.name}")
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        try:
            resp = _ollama_chat(
                {
                    "model": VISION_MODEL,
                    "stream": False,
                    "keep_alive": "10m",
                    "messages": [
                        {
                            "role": "user",
                            "content": VISION_PROMPT.replace("ファイル名", path.name),
                            "images": [b64],
                        }
                    ],
                    "options": {
                        "temperature": 0.0,
                        "num_ctx": 8192,
                        "num_predict": 2048,
                    },
                }
            )
            content = (((resp.get("message") or {}).get("content")) or "")
            parsed = _extract_json(content)
            parsed.setdefault("source_file", path.name)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            parsed = {"source_file": path.name, "error": str(exc)}
            append_log(request_id, f"vision error {path.name}: {exc}", level="ERROR")
        out.write_text(json.dumps(parsed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        results.append(parsed)

    merged = {"file_count": len(results), "files": results}
    merged_path = vision_dir / "vision.json"
    merged_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    append_markdown(
        request_id,
        "Vision JSON",
        f"モデル: `{VISION_MODEL}`\n処理ファイル数: {len(results)}\n出力: `{merged_path}`",
    )
    state = set_stage(request_id, "executing", vision_done=True)
    append_log(request_id, f"vision done -> {merged_path}")
    _unload(VISION_MODEL)
    return {"ok": True, "merged_path": str(merged_path), "merged": merged, "state": state}
