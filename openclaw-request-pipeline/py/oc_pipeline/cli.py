from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .engine import capture_plan, context_block, ingest, peek, save_output
from .logs import append_log
from .paths import PLANNER_MODEL, VISION_MODEL, requests_root
from .store import load_state, session_request, set_stage, unbind_session
from .vision import analyze_request
from .warmup import warmup


def _json_arg(raw: str | None) -> Any:
    if not raw:
        return None
    if raw.startswith("@"):
        return json.loads(Path(raw[1:]).read_text(encoding="utf-8"))
    return json.loads(raw)


def _print(data: Any) -> int:
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return 0 if isinstance(data, dict) and data.get("ok", True) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="oc-pipeline")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ingest")
    p.add_argument("--session", required=True)
    p.add_argument("--text", default="")
    p.add_argument("--media", default="")
    p.add_argument("--sender", default="")
    p.add_argument("--channel", default="slack")

    p = sub.add_parser("capture-plan")
    p.add_argument("--session", required=True)
    p.add_argument("--text", required=True)

    p = sub.add_parser("vision")
    p.add_argument("--request-id", required=True)

    p = sub.add_parser("save")
    p.add_argument("--request-id", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--content", default="")
    p.add_argument("--file", default="")

    p = sub.add_parser("log")
    p.add_argument("--request-id", required=True)
    p.add_argument("--message", required=True)
    p.add_argument("--level", default="INFO")

    p = sub.add_parser("status")
    p.add_argument("--session", default="")
    p.add_argument("--request-id", default="")

    p = sub.add_parser("finish")
    p.add_argument("--request-id", required=True)

    p = sub.add_parser("peek")
    p.add_argument("--session", required=True)
    p.add_argument("--text", default="")

    p = sub.add_parser("context")
    p.add_argument("--session", required=True)

    p = sub.add_parser("warmup")
    p.add_argument("--models", default="")

    sub.add_parser("root")

    args = parser.parse_args(argv)

    if args.cmd == "ingest":
        result = ingest(
            session_key=args.session,
            text=args.text,
            media=_json_arg(args.media) or [],
            sender=args.sender,
            channel=args.channel,
        )
        return _print(result)
    if args.cmd == "capture-plan":
        return _print(capture_plan(args.session, args.text))
    if args.cmd == "vision":
        return _print(analyze_request(args.request_id))
    if args.cmd == "save":
        content = Path(args.file).read_text(encoding="utf-8") if args.file else args.content
        path = save_output(args.request_id, args.name, content)
        return _print({"ok": True, "path": path})
    if args.cmd == "log":
        path = append_log(args.request_id, args.message, level=args.level)
        return _print({"ok": True, "path": path})
    if args.cmd == "status":
        state = load_state(args.request_id) if args.request_id else session_request(args.session)
        return _print({"ok": bool(state), "state": state})
    if args.cmd == "finish":
        state = set_stage(args.request_id, "done")
        unbind_session(state.get("session_key") or "")
        append_log(args.request_id, "request marked done")
        return _print({"ok": True, "state": state})
    if args.cmd == "peek":
        return _print(peek(session_key=args.session, text=args.text))
    if args.cmd == "context":
        state = session_request(args.session)
        if not state:
            return _print({"ok": False, "reason": "no_active_request"})
        payload = {"state": state, "event": "status", "instruction": ""}
        sys.stdout.write(context_block(payload))
        return 0
    if args.cmd == "warmup":
        models = [m for m in args.models.split(",") if m] or None
        return _print(warmup(models))
    if args.cmd == "root":
        return _print(
            {
                "ok": True,
                "requests": str(requests_root()),
                "planner": PLANNER_MODEL,
                "vision": VISION_MODEL,
            }
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
