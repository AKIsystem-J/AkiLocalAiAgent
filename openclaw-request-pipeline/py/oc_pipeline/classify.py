from __future__ import annotations

import re

OK_RE = re.compile(
    r"^(ok|okay|yes|y|はい|ええ|うん|承認|許可|いいよ|それで|よろしく|実行して|go|lgtm)"
    r"([!！.。\s]*)$",
    re.I,
)
NG_RE = re.compile(r"^(ng|no|だめ|駄目|違う|ちがう|やり直し|却下|却下して)\b", re.I)
SYSTEM_RE = re.compile(
    r"(heartbeat monitor|Pre-compaction memory flush|"
    r"Continue the OpenClaw runtime event|OpenClaw heartbeat poll|"
    r"^VISION_READY\b)",
    re.I,
)
CONTINUE_RE = re.compile(r"(続き|継続|続けて|続きで|ひきつづ|引き継)", re.I)
EXPAND_RE = re.compile(r"(拡張|改善|バージョンアップ|追加でやって)", re.I)
NEW_RE = re.compile(r"(いいえ|新規|新しい|別件|別リクエスト|新しく)", re.I)
SLASH_RESET_RE = re.compile(r"^[/／]?\s*(new|reset)\b", re.I)
TASK_RE = re.compile(
    r"(して|下さい|ください|お願い|集計|整理|作って|分析|調べ|計画|実行|一覧|合計|分類|読み取)",
    re.I,
)
GREETING_RE = re.compile(
    r"^(おはよう|こんにちは|こんばんは|やあ|よ[ー〜]*|hi+|hello|hey|ping|test|テスト)\b",
    re.I,
)
PING_RE = re.compile(
    r"(繋がって|つながって|生きてる|顔確認|応答して|聞こえて|いますか|いる[？?]|通じて)",
    re.I,
)


def is_chat(text: str) -> bool:
    raw = (text or "").strip()
    if not raw or len(raw) > 80 or TASK_RE.search(raw):
        return False
    return bool(GREETING_RE.search(raw) or PING_RE.search(raw))


def classify(stage: str | None, text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return "empty"
    if SYSTEM_RE.search(raw):
        return "system"
    if SLASH_RESET_RE.match(raw):
        return "session_reset"
    if is_chat(raw):
        return "chat"
    if stage == "ask_similar":
        if NEW_RE.search(raw):
            return "new"
        if EXPAND_RE.search(raw):
            return "expand"
        if CONTINUE_RE.search(raw) or OK_RE.match(raw):
            return "continue"
        return "unclear_similar"
    if stage in {"awaiting_approval"}:
        if NG_RE.match(raw) or raw.lower().startswith("ng"):
            return "ng"
        if OK_RE.match(raw):
            return "ok"
        return "revise"
    if stage in {"planning", "replanning"}:
        if NG_RE.match(raw):
            return "ng"
        if OK_RE.match(raw):
            return "ok"
        return "more_detail"
    if stage in {"executing", "vision"}:
        if NEW_RE.search(raw):
            return "new"
        return "followup"
    if stage == "done":
        return "new_or_followup"
    return "new_request"


def ng_points(text: str) -> str:
    stripped = (text or "").strip()
    stripped = re.sub(r"^(ng|no|だめ|駄目|違う|ちがう|やり直し|却下)\s*[:：-]?\s*", "", stripped, flags=re.I)
    return stripped or "（指摘なし）"
