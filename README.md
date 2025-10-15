# Note Automations – Content Queue

このリポジトリは note 記事の「生成 → キュー → 投稿」フローのうち、記事生成とキュー管理を担当します。GitHub Actions を使うことで、ローカル作業なしに記事の準備と投稿を自動化できます。

## ディレクトリ構成

```
articles-queue/     # 投稿待ちの記事（GitHub Actions が生成）
articles-posted/    # 投稿済み記事の保管場所（投稿後に自動移動）
sources/            # 元ネタとなる Markdown メモを置く場所
├─ processed/       # 取り込み済みメモ（自動移動）
scripts/            # 生成・投稿に使うユーティリティスクリプト
```

`sources/` 直下に Front Matter 付きの Markdown を置くだけで、後述の生成ワークフローが 1 件ずつ `articles-queue/` へ記事化します。記事のフロントマター例:

```markdown
---
title: GitHub Actions で note を自動更新する
tags: [note, 自動化]
is_public: true
cta: note をフォロー
summary: note 投稿の自動化に必要なステップを解説します。
---
本文テキスト…
```

## 用意している GitHub Actions

### 1. Generate Articles (`.github/workflows/generate-nightly.yml`)
- スケジュール: 毎日 0:00 JST（UTC 15:00）
- 直近の `sources/*.md` を最大 1 件（`GENERATE_LIMIT` で変更可能）処理し、`articles-queue/` に記事ファイルを追加します。
- 生成結果は Git コミットとして自動 push されるため、永続的なキューとして機能します。
- `workflow_dispatch` で手動実行する際は `limit` を入力すれば複数件処理も可能です。

### 2. Post Article (`.github/workflows/post-hourly.yml`)
- スケジュール: 毎時 0 分
- `articles-queue/` から最も古いファイルを選び、note-post MCP CLI（`@gonuts555/note-post-mcp`）で投稿します。
- 投稿が成功すると `articles-posted/` へファイルを移動し、Front Matter に `posted_at` と note の URL を追記します。
- スクリーンショットはアーティファクト `note-screens` として保存されます。

> **注意:** 投稿ワークフローを動かすには、Secrets に `NOTE_STATE_B64`（Playwright storageState の base64 文字列）を登録しておく必要があります。

## Secrets / Variables

| Name | 種別 | 説明 |
| ---- | ---- | ---- |
| `NOTE_STATE_B64` | Secret | note.com ログイン状態の base64 文字列（必須） |
| `NOTE_ARTICLE_PATH` | Repository Variable | 投稿したい記事を明示的に指定したい場合に使用（任意） |
| `GENERATE_LIMIT` | Workflow env | 1 回の生成で処理する件数（デフォルト 1） |

## ローカルでの検証

ローカルでも `npm run generate` を実行すると、`sources/` 内のメモから `articles-queue/` が作成される仕組みを確認できます。Playwright などブラウザ操作は Actions 上でのみ行われるため、ローカルでの note 投稿は不要です。

```
npm install
npm run generate
```

## 運用イメージ

1. `sources/` に記事の元ネタとなる Markdown を追加しコミット
2. 深夜の生成ワークフローが queue に記事を作成し自動コミット
3. 毎時の投稿ワークフローが queue を 1 件ずつ消化して note へ投稿
4. 投稿済みファイルは `articles-posted/` に移動され、履歴として残る

このリポジトリを note 投稿専用リポジトリ（例: `note-post-automation`）と組み合わせれば、「生成→キュー→定期投稿」のフローをすべて GitHub Actions 上で完結できます。
