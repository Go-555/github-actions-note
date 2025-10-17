# note 自動生成・投稿パイプライン

このリポジトリは、キーワード／メモを起点に Gemini API で長文記事と画像を生成し、GitHub Actions だけで queue 登録から note 投稿まで自動化するための構成です。1 日 24 本（設定上は最大 30 本）を想定し、

1. **メモ生成（研究）** – 指定キーワード「生成AI」に基づく最新トピックを収集し `inputs/memos/` に蓄積
2. **記事生成** – メモ＋構成案＋画像ブリーフから Markdown と画像を生成し `articles-queue/` に出力
3. **投稿** – 毎時 1 本ずつ queue から note.com へ投稿し、完了したら `articles-posted/` へ移動

というフローを GitHub Actions で回します。Playwright の storageState 以外にローカル操作は不要です。

## ディレクトリ構成
```
config/                # 設定 (config.yaml)
inputs/
  ├─ memos/           # 生成待ちメモ（自動補充）
  ├─ memos_trash/     # 使用済みメモ（自動移動）
  └─ research/        # 手動追加の参考資料
articles-queue/       # 投稿待ち記事 (Markdown)
articles-posted/      # 投稿済み記事 (Markdown / note_url 記録)
assets/               # 生成画像 (./assets/ 相対参照)
logs/                 # 実行ログ (jsonl / log)
scripts/              # 生成・品質・ユーティリティPython
  └─ utils/
tools/path_rewriter.mjs # 投稿前に ./assets → Raw URL へ書き換え
```

## 必要な Secrets
| 名前 | 用途 |
| --- | --- |
| `GEMINI_API_KEY` | Gemini 1.5 Pro / Imagen 呼び出し用 API キー |
| `IMAGE_API_KEY` | 画像生成用 API キー（未設定時は GEMINI_API_KEY を流用） |
| `NOTE_STATE_B64` | 投稿ワークフロー用 Playwright storageState(Base64) |

## 主要ワークフロー
### generate-batch.yml
- 毎日 0:00 JST（UTC 15:00）＋ `workflow_dispatch` で実行
- 手順: `memo_researcher` でメモ不足を補充 → `batch_runner.py` で 24 本分の記事＋画像を生成 → 差分をコミット
- `dry_run` 入力を 1 にすると API 呼び出し無しでダミー生成のみ行います（CI 用）

### post-hourly.yml
- 毎時 0 分で実行
- `articles-queue/` 先頭の Markdown を取得 → 画像パスを Raw URL に書き換え → note-post MCP CLI で投稿 → 記事を `articles-posted/` へ移動

### quality-gate.yml
- push / PR 時に `scripts/quality_gate_runner.py` を実行（簡易静的検査）

## スクリプト概要
| ファイル | 役割 |
| --- | --- |
| `scripts/memo_researcher.py` | キーワード「生成AI」に基づくメモ生成／補充、使用済みメモの移動 |
| `scripts/task_loader.py` | メモをタスク化（最大 24 件） |
| `scripts/outline_planner.py` | Gemini Structured Output で構成案＋画像ブリーフ生成（dry run ではモック） |
| `scripts/article_generator.py` | Gemini で本文生成（dry run 時はテンプレ本文） |
| `scripts/image_generator.py` | Imagen で画像生成（dry run 時はプレースホルダ） |
| `scripts/quality_gate.py` | 文字数／章立て／NG語／画像存在／簡易類似度チェック |
| `scripts/batch_runner.py` | 全体オーケストレーション（メモ補充→生成→品質→queue 保存→メモ退避） |
| `tools/path_rewriter.mjs` | 投稿前に `./assets/..` を Raw URL へ変換 |

## 使い方
1. `config/config.yaml` で生成条件（文字数、トーン、1 回あたりの生成数など）を調整します。デフォルトでは 1 本生成・1 本投稿の流れに合わせて `per_run_batch=1` になっています。
2. Secrets (`GEMINI_API_KEY`, `IMAGE_API_KEY`, `NOTE_STATE_B64`) を登録します。
3. 乾燥実行は `Actions → Generate Articles → dry_run=1` で確認できます（品質ゲートはスキップされます）。
4. 本番運用では dry_run を空欄にし、投稿ワークフローを有効化すれば毎時 1 本ずつ自動投稿されます。品質ゲートに引っ掛かった記事は `articles-queue/rejected/` に退避され、投稿はスキップされます。

### 設定ハイライト
- `article.target_chars` / `article.tone` で本文の長さと文体を指定できます。
- `quality_gate.reject_phrases` / `min_body_lines` によりテンプレ文やスカスカ記事を自動的に弾きます。
- `note.*` および `defaults.paid` / `defaults.price` / `defaults.theme` で公開設定（無料/有料、価格、テーマ）を制御します。これらは front matter に書き込まれ、投稿時の UI 操作に反映されます。

### 有料記事・テーマ設定
front matter には自動で以下のキーが付与されます。

```yaml
paywall: paid    # or "free"
price: 500       # paywall: paid の場合に使用
theme: ビジネス   # note 側のチャンネル／テーマ
visibility: public  # draft/unlisted/private にすると投稿せず下書き保存
```

`config/config.yaml` の `note` セクション、もしくは生成後に front matter を手修正することで有料公開・テーマを切り替えられます。ワークフローは UI のラジオボタン／入力欄を操作して反映します。

### ローカルでのテスト
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DRY_RUN=1
python scripts/batch_runner.py
```
生成結果は `articles-queue/` に保存され、dry run ではメモも自動補充されます。

## 注意事項
- 生成本数を増減したい場合は `config.memos.daily_target` と `concurrency.per_run_batch` を調整してください。投稿フローはキュー内の先頭 1 本のみ扱います。
- API コストが大きいため、Google Cloud の利用制限と課金状況を定期的に確認してください。
- 投稿後の Markdown は `articles-posted/` に移され、Front Matter に `posted_at` と `note_url` が追記されます。品質ゲートに落ちた記事は `articles-queue/rejected/` に移動します。
- 乾燥実行では品質ゲートが緩和されます。実運転では dry_run=0 で必ずテストしてください。

## ライセンス
MIT
