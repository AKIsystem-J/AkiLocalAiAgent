# OpenClaw request pipeline

Slack → Tailscale → OpenClaw → MiMo（計画→承認→実行）＋ 必要時 qwen2.5vl（全画像 JSON）

## 配置

- コード: このディレクトリ
- 案件フォルダ: `~/Documents/ai_tasks/YYYYMMDDHHMMSS/`
  - `YYYYMMDDHHMMSS.md` リクエストとプランの記録
  - `YYYYMMDDHHMMSS_0001.log` 実行ログ（20MB で繰り上げ）
  - `input/` 元ファイル
  - `vision/vision.json` 全画像処理後の JSON
  - `output/` 成果物

## CLI

```bash
oc-pipeline ingest --session slack:demo --text '交通費を一覧に'
oc-pipeline status --session slack:demo
oc-pipeline warmup
```
