# note 自動生成・投稿パイプライン

このリポジトリは、キーワード／メモから Gemini API を用いて note 記事（3,000〜5,000字）と画像を自動生成し、GitHub Actions 上でキュー化・投稿まで行うための仕組みです。1日最大 30 本を想定した夜間バッチ生成と、毎時 1 件の投稿ワークフローを備えています。

## ディレクトリ構成

```
config/           # 設定ファイル (config.yaml)
inputs/
  ├─ keywords/   # 1行1キーワードの .txt
  ├─ memos/      # メモ (Markdown/TXT)。ファイル名=キーワードが標準
  └─ research/   # 追加リサーチ素材
articles-queue/  # 投稿待ち記事 (MD)
articles-posted/ # 投稿済み記事 (MD / posted_at, note_url 付与)
assets/          # 生成画像 (相対パスで参照)
logs/            # 実行ログ (jsonl / log)
scripts/         # 生成・品質・ユーティリティPython
  └─ utils/      # 補助ユーティリティ
.tools/
  └─ path_rewriter.mjs # 投稿直前の asset パス書き換え用
```

## 必要な Secrets / Variables

| 名前 | 種別 | 用途 |
| --- | --- | --- |
| `GEMINI_API_KEY` | Actions Secret | Gemini 1.5 Pro / Imagen 呼び出し用 API キー |
| `IMAGE_API_KEY`  | Actions Secret | 画像生成 API キー（未設定なら GEMINI_API_KEY を流用） |
| `NOTE_STATE_B64` | Actions Secret | 投稿ワークフロー用 Playwright storageState(Base64) |

必要に応じて追加の通知 Webhook などを設定してください。

## セットアップ手順

1. `config/config.yaml` を用途に合わせて調整します（文字数、章立て、NGワード、並列度など）。
2. `inputs/keywords/` に 1 行 1 キーワードの `.txt` を置き、対応するメモを `inputs/memos/` に配置します（ファイル名がキーワードと一致する場合に優先的に利用します）。
3. `GEMINI_API_KEY` などの Secrets を登録します。
4. `articles-queue/` や `assets/` は Git にコミットされ、投稿ワークフローが利用します。不要な履歴を避けるため適宜クリーンアップしてください。

ローカルでの動作確認:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/batch_runner.py
```

API キーが未設定の場合、エラーで停止します。開発時はダミーを設定するか、後述の `dry_run` オプション実装などで対処してください。

## GitHub Actions ワークフロー

### generate-batch.yml
- 実行: 毎日 0:00 JST（UTC 15:00）+ 手動実行
- 内容: `scripts/batch_runner.py` を呼び、最大 30 件の記事を生成し `articles-queue/` に保存。生成成功時は自動コミット & push。
- ログ: `logs/` を Artifact としてアップロード。

### post-hourly.yml
- 実行: 毎時 0 分 + 手動実行
- 内容: `articles-queue/` 先頭の Markdown を選び、assets のパスを書き換えたうえで note-post MCP CLI で投稿。成功時は `articles-posted/` 移動＆ note_url 追記、スクリーンショットを Artifact へ保存。
- Secrets に `NOTE_STATE_B64` が必須。投稿用 token が失効した場合は Playwright で再取得してください。

### quality-gate.yml
- 実行: main への push / PR
- 内容: 生成済み Markdown を対象に簡易品質チェック（章立て、文字数、NGワードなど）。

## スクリプト概要

| ファイル | 役割 |
| --- | --- |
| `scripts/batch_runner.py` | 生成パイプラインのオーケストレーション。タスク読み込み → 構成 → 本文 → 画像 → 品質ゲート → queue 保存。
| `scripts/task_loader.py` | keywords/memos ディレクトリからタスクを組み立て。
| `scripts/outline_planner.py` | Gemini 1.5 Pro Structured Output で構成案と画像ブリーフ生成。
| `scripts/article_generator.py` | Gemini で本文生成（章立て・文字数指定）。
| `scripts/image_generator.py` | Imagen ベースの画像生成（失敗時は placeholder）。
| `scripts/markdown_builder.py` | Front Matter（UUID, publish_at, tags 等）＋本文組み立て。
| `scripts/quality_gate.py` | 文字数、必須章、NG表現、類似度チェック。
| `scripts/quality_gate_runner.py` | Actions 用の静的検証エントリーポイント。
| `tools/path_rewriter.mjs` | 投稿直前に `./assets` を Raw URL へ変換。

## カスタマイズ

- `config/config.yaml` で温度、並列数、画像生成数、NGワード等を調整できます。
- 類似度判定は TF-IDF + コサイン類似度。高精度が必要なら SentenceTransformer 等への差し替えも検討できます。
- エラーログは `logs/run.jsonl` に追記。必要に応じて Slack などへの通知フックを追加してください。

## 注意事項

- 30 本/日の生成は API コストが大きいため、Google Cloud の上限や費用を確認してください。
- 生成内容の品質保証は quality gate に依存するため、辞書やルールセットを定期的に更新してください。
- 投稿ワークフローは毎時1件ずつ消化する仕様です。queue に余剰があれば順次公開されます。
- 生成と投稿の双方が Git コミットを行うため、並列実行や force push には注意してください。

## ライセンス

MIT
