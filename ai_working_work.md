# ai_working 作業記録

記録日: 2026-10-02  
対象: 旧 `~/Documents/ai_working`（現 `~/Documents/AkiLocalAiAgent`）  
目的: このフォルダで進めたローカルエージェント構築の実施事項を、続きの作業から読める形で残す。

リモート: https://github.com/AKIsystem-J/AkiLocalAiAgent （`main`、コミット `2c0fcb3`）

---

## 1. いまの結論

顧客向けの入り口は **Slack**。推論は **この Mac 上の Ollama**。OpenClaw Gateway が間にいる。

2026-10-02 時点で実際に有効な経路は、計画承認パイプラインを外した **Slack → OpenClaw → `qwen3.5:9b` 直結** である。検索は DuckDuckGo。Cursor Agent CLI は ACP で呼べる状態まで入れたが、自動ディスパッチはオフ。

計画承認つきの `openclaw-request-pipeline` はコードとしてリポジトリにある。稼働設定では **プラグインもスキルも無効**。デモ前に品質と待ち時間で直結へ戻した。

フォルダ名はリポジトリに合わせて `AkiLocalAiAgent` に変更済み。`ai_working` というパス参照は、実装と `~/.openclaw/openclaw.json` から外してある。

---

## 2. 狙い

利用者（将来の顧客）にはマシンを触らせない。

```
iPhone Slack
  → Slack Cloud（Socket Mode）
  → Mac の OpenClaw Gateway（127.0.0.1、Tailscale Serve は開発者用）
  → Ollama（ローカル LLM）
  → 必要なら Cursor CLI（重い文書・コード）
  → Slack へ短い結果
```

開発機はこの MacBook Pro（M2 Pro / 32GB）。顧客試験機は **Mac mini M6 32GB / 512GB**（発注済み、未着）。試験機でも入り口は Slack だけにする。

初期の設計メモ（`ai_egent_for_consumers.md`）では、成果物の正本を本人だけが見られる Google ドライブに置き、チャット全文は Mac Gateway に残す、としていた。その後の実装は Slack を操作面にし、案件フォルダを Mac ローカル（`~/Documents/ai_tasks`）に置く方向へ寄っている。ドライブ納品ワーカーは未実装。

---

## 3. 時系列

### 2026-09-12 設計とメモ

- Cursor チェンジログ要約を `chapter3/chat.md` に書いた。
- インラインモードの説明が `chapter3/inlinemode.md` にある。
- 消費者向け構成を `ai_egent_for_consumers.md` にまとめた。
  - 見せるもの: iPhone の会話、短い状態、本人の Google アカウントだけで開ける成果物。
  - 隠すもの: Cursor、Mac のファイル、資格情報。
  - LocalLLM は窓口（意図・スキル選択・要約）。Cursor は実行エンジン。直列に「LocalLLM が Cursor のループ全体を担う」形にはしない。
  - 文書・契約・納品・請求のようなコーディング以外も、ACP 経由の Cursor で対象にできる、という確認をした。

### 2026-09-15 この Mac で OpenClaw を動かす

- Ollama と OpenClaw の起動状態を確認し、スリープ復帰後も戻る常駐にした（LaunchAgent の Gateway、Homebrew の Ollama）。
- iPhone の OpenClaw アプリから「ハロー」が遅い／返らない問題を追った。
  - 待ちの主因は文脈の先読みと、毎ターン付くシステム説明・スキル要約・ツール一覧。
  - Gateway の thinking を落とし、起動時コンテキストを短くした。
  - ツールは minimal にし、`web_search` / `web_fetch` を足した。検索プロバイダは DuckDuckGo（地域 `jp-jp`）。
- `smtek/Qwen3.8-27B:Q3_K_M-128k` を主モデルにしたところ、Context Overflow とツール呼び出しの連発が起きた。文脈は 8192 → 16384 に上げた。同じ検索を `qwen3.5:9b` でやり直す判断になり、以後このマシンの実用モデルは 9B 側。
- 体感: 27B 3bit の長作業は約 5 分。同じ系統を 9B にすると約 1 分 12 秒。M2 Pro 32GB の開発・デモは 9B。

### 2026-09-15 以降 Slack を入り口にする

- Slack アプリを Socket Mode で OpenClaw に接続した。pairing で送信者を許可。
- Slack の方が iPhone OpenClaw アプリより体感が速い。生成中の経過表示があり、Control UI 側の 120 秒待ちで切れない。
- 出力上限は 4096 トークン前後。長い表は切れる。`/stop` のあと再送する運用。連続送信は輻輳する。
- 実在企業の一覧は、検索しても推定と取り違えが混ざる。客向けの確定情報にはしない、という制約を確認した。
- 構成スナップショットを `aki-mbk-m2-ai-agent-architecture.md` に書いた。
- Cursor Agent CLI、ACP プラグイン、exec 許可を入れた。`acp.enabled=true`、`defaultAgent=cursor`。`dispatch.enabled` は false のまま（Slack から勝手に Cursor へ投げない）。

### 2026-09-25 前後 計画承認パイプライン

依頼どおり、次の流れのコードを `openclaw-request-pipeline/` に作った。

```
Slack
  → OpenClaw
  → MiMo で計画
  → Slack で OK / NG
  → 画像があるときだけ qwen2.5vl:7b で全画像を JSON
  → MiMo で実行・集計・一覧
  → Slack へ結果
```

案件フォルダ、類似案件への「続きか、拡張実施か？」、プランの Markdown 追記、20MB ローテートの実行ログまでコードとテストがある。

レシート画像の通し試験で見えたこと:

- 承認前にファイルを書かせないガードは入っている。
- `OK` の即時応答、承認後にプランを出し直す、`NO_REPLY` で Slack が失敗する、Vision の細かい誤読（店名の取り違えなど）が残った。
- 補正（店名ゆれなど）は後回し。
- 市場調査は、パイプライン経由だと具体性が落ちた。以前できていた `qwen3.5:9b` 直結の方が検索つき一覧には向いていた。
- 成果の Slack 添付は、その場ではできなかった。
- デモとヒアリングに出るため、ここで環境作りを一区切りにした。パイプラインは無効に戻してある。

### 2026-09-28 前後 次の仕事の型（設計のみ）

エージェントにやらせたい仕事:

| 種類 | 例 | 動かし方 |
| --- | --- | --- |
| 非定型 | インターネット調査、提案資料の素案、プロジェクト計画、壁打ち | 依頼のたびにタスク化。残タスクを見せつつ FIFO。優先変更はその場の処理を止めて割り込み |
| 定型 | レシート・請求の整理集計、進捗報告 | タスク種別ごとに管理。決めた時刻に残処理して Slack へ報告 |

合意した流れ（壁打ち以外）:

1. 依頼 → タスク作成（フォルダと ID）
2. 計画を返して確認。NG なら修正
3. 承認後に実行
4. 結果を返す

壁打ちは計画承認を挟まない。音声入力で区別が付かない前提なので、発話の先頭に「壁打ち」を付ける。

ID の呼び方は次の案で止まっている（コードには未反映）。

- 定型: `定型-0001` のように通し番号。短い別名（例: 経費）。「定型の1番の経費」「経費に追加」で通す。
- 非定型: `非定型26-0001`（年 + 通し）。当年を基本にする。

定型の起動時刻案: 1:30、3:00、6:00、8:00、12:00、15:00、18:30、21:00。

Slack の置き方案:

- 今の「OpenClaw」はチャンネルではなく、Bot との DM。
- 新規依頼はスレッドの外。そのタスクへの返事（OK 含む）はスレッドの中。スレッド内なら ID を言わなくてよい。
- 定型を複数人で入れるなら共有チャンネルが必要。DM は本人にしか見えない。
- セクションは最初から「定型業務」「非定型業務」「入口の DM」を分けたい、という希望で止まっている。

成果物は Markdown を基本にし、スライドは Marp。Excel は一旦保留。

32GB ではローカル LLM を同時に複数本走らせない。割り込みは「今の処理を止めて次をやる」。

モデル動的ルーティング（個人情報はローカルに残し、難易度で外部モデルへ分ける `dynamic-llm-router` スキル）はファイルがある。OpenClaw の eligible 一覧には載せず、ルート切替の実装は後回し。

### 2026-10-02 リポジトリ化

- 試験機は Mac mini M6 32GB / 512GB で発注済み。48GB 以上は M5 Pro になり予算外。売れてから上位を足す。
- iPhone の Cursor から同じツリーを触るため、GitHub `AKIsystem-J/AkiLocalAiAgent` を正にした。
- フォルダを `~/Documents/AkiLocalAiAgent` に改名し、次のパスを更新した。
  - `openclaw-request-pipeline/hooks/warmup-models/handler.js`
  - `aki-mbk-m2-ai-agent-architecture.md`
  - `~/.openclaw/openclaw.json` とバックアップ、稼働コピーの warmup hook
- `main` を GitHub へ push 済み。

Gateway プロセスは改名前のパスを覚えていることがある。プラグインを再び有効にするときは Gateway 再起動が必要。

---

## 4. 2026-10-02 の稼働設定

`~/.openclaw/openclaw.json`（トークンはここには書かない）。

| 項目 | 値 |
| --- | --- |
| OpenClaw | 2026.8.2、bind loopback、Tailscale Serve |
| 主モデル | `ollama/qwen3.5:9b`（context 32768） |
| thinking | `low` |
| ツール | minimal + `web_search` `web_fetch` `exec` `process` `write` `edit` |
| 検索 | DuckDuckGo、有効 |
| Slack | Socket Mode、有効 |
| プラグイン | duckduckgo / ollama / slack / acpx が有効。`request-pipeline` は無効 |
| スキル `request-pipeline` | 無効 |
| ACP | 有効、backend `acpx`、default `cursor`、dispatch は無効 |
| warmup-models hook | 有効（起動時に planner と vision を載せようとする） |
| タイムゾーン | Asia/Tokyo |
| セッション | DM は相手ごと。アイドル 60 分でリセット |

Ollama に登録してあるモデル:

- `qwen3.5:9b`（いまの主モデル）
- `maternion/mimo-v2.6:9b-thinking-q4_K_M`
- `maternion/mimo-v2.6:9b-thinking-q6_K`
- `qwen2.5vl:7b`
- `smtek/Qwen3.8-27B:Q3_K_M-128k`

コード上のパイプライン既定 planner は `qwen3.5:9b`（環境変数 `OC_PLANNER_MODEL`）。設計図の本文は MiMo Q4 を計画役と書いている。再有効化するときにどちらを載せるか、設定を揃える必要がある。

---

## 5. リポジトリにあるもの

| パス | 内容 |
| --- | --- |
| `ai_egent_for_consumers.md` | 利用者から Cursor を隠す構成の設計（ファイル名の egent は原文のまま） |
| `aki-mbk-m2-ai-agent-architecture.md` | この MBP の構成スナップショット。一部は 9/25 のパイプライン前提で、現行の「直結・プラグイン無効」より進んだ記述が残る |
| `chapter3/chat.md` | Cursor チェンジログ要約 |
| `chapter3/inlinemode.md` | インラインモードの説明 |
| `openclaw-request-pipeline/` | 計画承認パイプライン（現状は未ロード） |

パイプラインの中身:

- `index.js` … OpenClaw プラグイン。段階に応じてプロンプトを注入し、承認前の write/exec を止める。
- `py/oc_pipeline/` … 段階機械、類似判定、Vision、ログ、案件ストア。
- `skill/request-pipeline/SKILL.md` … 段階の守り（chat は短く、planning はプランだけ、executing で成果を書く）。
- `skill/dynamic-llm-router/SKILL.md` … 外部モデル振り分けの草案。未接続。
- `hooks/warmup-models/` … Gateway 起動時にモデルを常駐させる。
- `tests/test_pipeline.py` … planning → awaiting_approval → executing、NG で replanning、類似で ask_similar。

案件の置き場（コードの既定）:

- `~/Documents/ai_tasks/YYYYMMDDHHMMSS/`
- 上書き: 環境変数 `OC_TASKS_ROOT`
- 記録 `YYYYMMDDHHMMSS.md`、ログ `*_0001.log`（20MB で繰り上げ）、`input/`、`vision/vision.json`、`output/`
- 索引 `index.json`

`aki-mbk-m2-ai-agent-architecture.md` の 5.1 は置き場を `~/.openclaw/workspace/requests/` と書いている。動くコードの既定は `~/Documents/ai_tasks`。続きを実装するときはコード側に合わせる。

CLI の入口: `openclaw-request-pipeline/bin/oc-pipeline`（`ingest` / `status` / `warmup`）。

---

## 6. まだやっていないこと

1. パイプラインのバグを直してから有効に戻す（OK の即レス、承認後にプランを再掲しない、`NO_REPLY` を Slack 失敗にしない、Vision の誤読補正）。
2. 定型 / 非定型のタスク ID、別名、スレッド 1 本、定型の時刻起動。設計で止まっている。
3. 共有チャンネル（定型）と入口 DM（非定型）のセクション分け。
4. 成果の Slack 添付、または設計メモどおりの Google ドライブ納品。
5. Marp でのスライド化。
6. `dynamic-llm-router` の接続。個人情報を外に出さない条件はスキル草案にある。
7. Mac mini 到着後の常駐（スリープしない、電源復帰で Gateway と Ollama が上がる）と、この MBP との速度比較。
8. アーキテクチャ文書を「いま有効な直結構成」に合わせて更新する。

デモで見せたかった中身は、レシート集計と、市場調査から一覧を作ること。後者は 9B 直結＋ web 検索で一度通っている。

---

## 7. 会話

このフォルダの Cursor 会話:

- [Changelog summary](a05824d9-b040-4264-a7a5-98a96faf3d13) … 2026-09-12
- [LocalLLM and Cursor design](86bb6a52-4c29-4a9e-85da-bd477b5ab44a) … 2026-09-12
- [ACP beyond coding](1ea19db1-f8bd-41b3-a81f-75a8d3964596) … 2026-09-12
- [Ollama and OpenClaw ops](61411559-e132-49c2-a232-b2a092b13874) … 2026-09-15
- [Slack and pipeline](b69e02fd-bbd2-4116-b904-5364e3b7e018) … 2026-09-15 から改名前
- [Rename and GitHub](3e769a71-8a0b-4e98-9f36-2646b8382918) … 改名後の続き。GitHub 同期まで
