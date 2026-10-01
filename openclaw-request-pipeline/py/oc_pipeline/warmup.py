from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .paths import OLLAMA_URL, PLANNER_MODEL


def _generate(model: str) -> dict[str, Any]:
    payload = {
        "model": model,
        "prompt": "ok",
        "stream": False,
        "keep_alive": "15m",
        "options": {"num_predict": 1, "num_ctx": 512},
    }
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return {"model": model, "ok": True, "eval_count": data.get("eval_count")}


def warmup(models: list[str] | None = None) -> dict[str, Any]:
    targets = models or [PLANNER_MODEL]
    results = []
    for model in targets:
        try:
            results.append(_generate(model))
        except (urllib.error.URLError, TimeoutError) as exc:
            results.append({"model": model, "ok": False, "error": str(exc)})
    return {"ok": all(item.get("ok") for item in results), "results": results}
