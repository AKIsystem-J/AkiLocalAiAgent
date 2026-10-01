---
name: warmup-models
description: "Keep MiMo planner and qwen2.5vl loaded in Ollama on Gateway startup"
metadata:
  { "openclaw": { "emoji": "🔥", "events": ["gateway:startup"], "requires": { "bins": ["python3"] } } }
---

# Warmup models

Gateway 起動時に planner と vision モデルを Ollama に載せる。`keep_alive=-1`。
