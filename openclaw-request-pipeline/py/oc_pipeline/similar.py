from __future__ import annotations

import re
from typing import Any

from .paths import SIMILAR_THRESHOLD
from .store import load_index, load_state, record_path

_TOKEN = re.compile(r"[A-Za-z0-9]+|[\u3040-\u30ff\u4e00-\u9fff]+")


def tokens(text: str) -> set[str]:
    found = set()
    for match in _TOKEN.findall(text.lower()):
        if len(match) >= 2:
            found.add(match)
        if len(match) >= 3:
            for i in range(len(match) - 1):
                found.add(match[i : i + 2])
    return found


def score(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def find_similar(text: str, *, exclude_id: str | None = None, limit: int = 3) -> list[dict[str, Any]]:
    query = (text or "").strip()
    if len(query) < 4:
        return []
    hits: list[dict[str, Any]] = []
    for row in load_index().get("requests") or []:
        request_id = row.get("id")
        if not request_id or request_id == exclude_id:
            continue
        blob = row.get("summary") or ""
        rec = record_path(request_id)
        if rec.exists():
            blob = f"{blob}\n{rec.read_text(encoding='utf-8')[:4000]}"
        value = score(query, blob)
        if value >= SIMILAR_THRESHOLD:
            hits.append(
                {
                    "id": request_id,
                    "score": round(value, 3),
                    "summary": (row.get("summary") or "")[:180],
                    "stage": row.get("stage"),
                    "dir": row.get("dir"),
                }
            )
    hits.sort(key=lambda item: item["score"], reverse=True)
    return hits[:limit]


def request_summary(request_id: str) -> str:
    state = load_state(request_id)
    return state.get("summary") or request_id
