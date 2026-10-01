---
name: request-pipeline
description: Slack/OpenClaw request pipeline. Plan with MiMo, ask OK/NG, then optional qwen2.5vl JSON, then execute. Use for every inbound request, image organization, receipts, lists, and follow-ups.
---

# Request pipeline

OpenClaw が `<request_pipeline>` を注入する。その `stage` に従え。

## 必ず守ること

1. `chat` / 挨拶・接続確認 — 短く返事だけ。ツール禁止。プランもフォルダも作るな。
2. `ask_similar` — 実行も計画もするな。近い過去案件を示し、「続きか、拡張実施か？」だけ聞け。
3. `planning` / `replanning` — プランだけ出せ。ファイル作成・検索・exec はするな。末尾は「このプランで進めてよいか。OK / NG（指摘）で返してほしい。」
4. `awaiting_approval` — 待つだけ。
5. `executing` — 承認済み。プランどおり実行。成果は `folder/output/`。記録は `record_md`。ログは `pipeline` の `log`。終わったら `finish`。
6. 画像整理 — 承認後に Vision JSON が揃っている。全ファイル処理済み。同じクラスの数値は集計し、一覧化する。

## 画像整理の成果物

- `output/一覧.md`（表）
- 必要なら `output/集計.json`
- Slack には短い表と合計を返す

## ツール

- `pipeline` action=`save|log|finish|status`
- 承認前の write/exec はプラグインが止める
