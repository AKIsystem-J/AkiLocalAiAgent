from __future__ import annotations

import json
from typing import Any

from .classify import classify, ng_points
from .logs import append_log
from .similar import find_similar
from .store import (
    append_markdown,
    attach_media,
    create_request,
    load_state,
    record_path,
    request_dir,
    session_request,
    set_stage,
    unbind_session,
)
IMAGE_HINT = ("画像", "写真", "レシート", "領収", "明細", "スキャン", "スクショ")


def peek(*, session_key: str, text: str) -> dict[str, Any]:
    current = session_request(session_key)
    action = classify(current.get("stage") if current else None, text or "")
    reset = action in {"new_request", "new", "session_reset"} or (
        current is None and action not in {"system", "empty"}
    )
    return {
        "ok": True,
        "action": action,
        "reset": reset,
        "stage": current.get("stage") if current else None,
        "request_id": current.get("id") if current else None,
    }


def ingest(
    *,
    session_key: str,
    text: str,
    media: list[dict[str, Any]] | None = None,
    sender: str = "",
    channel: str = "slack",
    capture_assistant: str | None = None,
) -> dict[str, Any]:
    current = session_request(session_key)
    media = media or []
    text = text or ""

    def out(state: dict[str, Any], event: str, instruction: str, extra: dict[str, Any] | None = None):
        return _bundle(state, event=event, instruction=instruction, extra=extra, user_text=text)

    if current and (current.get("last_user_text") or "") == text.strip() and text.strip():
        return _bundle(current, event="repeat", instruction=_instruction(current))
    action = classify(current.get("stage") if current else None, text)
    if action == "session_reset":
        if current:
            unbind_session(session_key)
        return {
            "ok": True,
            "event": "session_reset",
            "state": None,
            "reset": True,
            "instruction": "セッションを初期化した。短い確認だけ返せ。案件フォルダは作るな。",
            "context": context_block(
                {
                    "state": None,
                    "event": "session_reset",
                    "instruction": "セッションを初期化した。短い確認だけ返せ。案件フォルダは作るな。",
                }
            ),
        }

    if action in {"system", "chat"}:
        instruction = (
            "内部ハートビート。ユーザー案件としては扱うな。短い NO_REPLY でよい。"
            if action == "system"
            else "接続確認・挨拶。ツールは使うな。短く返事せよ。案件フォルダは作るな。プランも出すな。"
        )
        if current:
            return _bundle(current, event=action, instruction=instruction)
        return {
            "ok": True,
            "event": action,
            "state": None,
            "instruction": instruction,
            "context": context_block(
                {"state": None, "event": action, "instruction": instruction}
            ),
        }

    if capture_assistant and current and current.get("stage") in {"planning", "replanning"}:
        append_markdown(current["id"], "プラン", capture_assistant)
        append_log(current["id"], "plan captured from assistant")
        current = set_stage(current["id"], "awaiting_approval", approved_plan=None)
        action = classify("awaiting_approval", text) if text.strip() else "empty"

    if action == "empty" and current:
        return out(current, "noop", _instruction(current))

    if current and action == "ok":
        append_markdown(current["id"], "承認", text or "OK")
        append_log(current["id"], "plan approved")
        current = set_stage(current["id"], "executing")
        return out(
            current,
            "approved",
            "承認済み。最初の一文だけ「プランを承認した。画像を読み取って一覧化する。」と返せ。ツールは使うな。Vision はパイプラインが裏でやる。",
        )

    if current and action == "ng":
        points = ng_points(text)
        append_markdown(current["id"], "NG指摘", points)
        append_log(current["id"], f"plan rejected: {points}")
        current = set_stage(current["id"], "replanning")
        return out(current, "rejected", _instruction(current, ng=points))

    if current and action in {"continue", "expand"}:
        kind = "continuation" if action == "continue" else "expansion"
        append_markdown(current["id"], "続き/拡張" if action == "continue" else "拡張実施", text)
        attach_media(current["id"], media)
        current = set_stage(current["id"], "planning", kind=kind, vision_done=False)
        append_log(current["id"], f"reuse as {kind}")
        return out(current, kind, _instruction(current))

    if current and action == "unclear_similar":
        return out(current, "ask_similar_again", _instruction(current))

    if current and action == "followup":
        if current.get("has_images") and not current.get("vision_done"):
            return out(current, "waiting_vision", "Vision JSON 作成中。短く待つ旨だけ返せ。実行するな。")
        if current.get("stage") != "executing":
            current = set_stage(current["id"], "executing")
        return out(current, "continue_exec", _instruction(current))

    if current and action in {"revise", "more_detail"}:
        attach_media(current["id"], media)
        append_markdown(current["id"], "追加指示", text)
        if current.get("stage") == "awaiting_approval":
            current = set_stage(current["id"], "replanning")
        append_log(current["id"], f"additional instruction ({action})")
        return out(current, "more_detail", _instruction(current))

    if current and action == "new":
        unbind_session(session_key)
        current = None
        similar = []
        state = create_request(
            text=text,
            session_key=session_key,
            sender=sender,
            channel=channel,
            media=media,
            kind="new-after-similar",
        )
        append_log(state["id"], "explicit new folder after similar prompt")
        return out(state, "new", _instruction(state))

    similar = find_similar(text, exclude_id=current["id"] if current else None)
    if similar and action in {"new_request", "new_or_followup"}:
        state = create_request(text=text, session_key=session_key, sender=sender, channel=channel, media=media)
        set_stage(state["id"], "ask_similar", similar=similar, parent_id=similar[0]["id"])
        append_markdown(
            state["id"],
            "類似候補",
            "\n".join(f"- `{item['id']}` score={item['score']} {item['summary']}" for item in similar),
        )
        append_log(state["id"], f"similar hits: {[item['id'] for item in similar]}")
        state = load_state(state["id"])
        return out(state, "ask_similar", _instruction(state))

    if current and action == "new_or_followup":
        attach_media(current["id"], media)
        append_markdown(current["id"], "追加リクエスト", text)
        current = set_stage(current["id"], "planning", vision_done=False)
        return out(current, "followup_newish", _instruction(current))

    state = create_request(text=text, session_key=session_key, sender=sender, channel=channel, media=media)
    if not text.strip() and state.get("has_images"):
        append_markdown(state["id"], "補足", "本文なし。画像整理として扱う。")
    needs_vision = bool(state.get("has_images") or any(token in text for token in IMAGE_HINT))
    if needs_vision:
        state["has_images"] = True
        from .store import save_state

        save_state(state)
    append_log(state["id"], "new request created")
    return out(state, "new", _instruction(state))


def capture_plan(session_key: str, assistant_text: str) -> dict[str, Any]:
    current = session_request(session_key)
    if not current or current.get("stage") not in {"planning", "replanning"}:
        return {"ok": False, "reason": "not_planning"}
    if not _looks_like_plan(assistant_text):
        return {"ok": False, "reason": "not_a_plan"}
    append_markdown(current["id"], "プラン", assistant_text)
    append_log(current["id"], "plan appended")
    state = set_stage(current["id"], "awaiting_approval")
    return {"ok": True, "state": state}


def _looks_like_plan(text: str) -> bool:
    raw = (text or "").strip()
    if not raw or classify(None, raw) == "system":
        return False
    if raw.upper() in {"NO_REPLY", "NO_REPLY."}:
        return False
    if raw.lower().startswith("plan approved"):
        return False
    return len(raw) >= 8


def save_output(request_id: str, name: str, content: str) -> str:
    safe = name.replace("..", "").lstrip("/")
    if not safe:
        raise ValueError("empty filename")
    path = request_dir(request_id) / "output" / safe
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    append_markdown(request_id, "成果物", f"`{path}`")
    append_log(request_id, f"output saved {path}")
    return str(path)


def context_block(payload: dict[str, Any]) -> str:
    state = payload.get("state")
    if not state:
        return (
            "<request_pipeline>\n"
            f"stage: {payload.get('event') or 'chat'}\n"
            f"event: {payload.get('event')}\n"
            "\nこのターンの指示:\n"
            f"{payload.get('instruction')}\n"
            "</request_pipeline>\n"
        )
    request_id = state["id"]
    rec = record_path(request_id)
    vision = request_dir(request_id) / "vision" / "vision.json"
    similar = state.get("similar") or []
    similar_lines = (
        "\n".join(f"- {item['id']} ({item['score']}): {item['summary']}" for item in similar)
        if similar
        else "- なし"
    )
    display_stage = payload.get("event") if payload.get("event") in {"chat", "system"} else state.get("stage")
    return f"""<request_pipeline>
stage: {display_stage}
request_id: {request_id}
folder: {request_dir(request_id)}
record_md: {rec}
vision_json: {vision if vision.exists() else "(未作成)"}
has_images: {state.get("has_images")}
vision_done: {state.get("vision_done")}
event: {payload.get("event")}

類似候補:
{similar_lines}

このターンの指示:
{payload.get("instruction")}
</request_pipeline>
"""


def _bundle(
    state: dict[str, Any],
    *,
    event: str,
    instruction: str,
    extra: dict[str, Any] | None = None,
    user_text: str | None = None,
) -> dict[str, Any]:
    extra = dict(extra or {})
    if event != "repeat" and user_text is not None:
        from .store import save_state

        state = dict(state)
        state["last_user_text"] = user_text.strip()
        save_state(state)
    payload = {
        "ok": True,
        "event": event,
        "state": state,
        "instruction": instruction,
        "context": "",
    }
    payload.update(extra)
    payload["context"] = context_block(payload)
    return payload


def _instruction(state: dict[str, Any], ng: str | None = None) -> str:
    stage = state.get("stage")
    request_id = state["id"]
    folder = request_dir(request_id)
    if stage == "ask_similar":
        similar = state.get("similar") or []
        head = similar[0] if similar else {}
        return (
            f"以前に受けた `{head.get('id')}` が近い: {head.get('summary')}\n"
            "続きか、拡張実施か？\n"
            "はい→改善実行（同じフォルダに追記） / いいえ→新規フォルダを作って新規実行\n"
            "このターンでは計画も実行もするな。上の二択だけ聞け。"
        )
    if stage in {"planning", "replanning"}:
        extra = f"\nNGポイント: {ng}\nこれを直して再計画せよ。" if ng else ""
        vision_note = (
            "画像がある。プランには「承認後に qwen2.5vl:7b で全画像をJSON化してから整理・集計・一覧化する」と書け。今は画像の中身を確定値として使うな。"
            if state.get("has_images")
            else "画像は無い。通常の計画を出せ。"
        )
        return (
            "実行するな。ツールでファイルを書くな。プランだけ出せ。\n"
            f"{vision_note}\n"
            "プランには手順、使う入力、出力ファイル名、数値項目の集計方針を含めよ。\n"
            "末尾は必ず次の一文: 「このプランで進めてよいか。OK / NG（指摘）で返してほしい。」"
            f"{extra}"
        )
    if stage == "awaiting_approval":
        return "すでにプラン提示済み。ユーザーの OK / NG を待て。実行するな。"
    if stage == "executing":
        vision = folder / "vision" / "vision.json"
        image_part = ""
        if state.get("has_images") and not state.get("vision_done"):
            return "承認済み。Vision JSON 作成中。ツールは使うな。短く待つ旨だけ返せ。"
        if state.get("has_images"):
            image_part = (
                f"Vision JSON は `{vision}`。全画像処理済み。整理要件に従い整理し、"
                "同じクラスの数値（金額など）は集計し、一覧化せよ。"
            )
        return (
            f"承認済み。プランに基づき実行せよ。成果物は `{folder / 'output'}` に保存し、"
            f"経過は `{folder / (request_id + '.md')}` に追記せよ。{image_part}\n"
            "pipeline ツールの save / finish を使え。"
        )
    if stage == "done":
        return "このリクエストは完了済み。短い確認だけ返せ。新しい作業なら新規として扱え。"
    return "リクエストを解釈し、計画だけ出せ。"
