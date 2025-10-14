# Note Workflow – GitHub Actions

このリポジトリの `.github/workflows/note.yaml` は、以下のパイプラインをGitHub Actionsで実行します。

1) **リサーチAgent**: Google Gemini 1.5 Pro (latest) + Google Search grounding によるリサーチレポート作成
2) **執筆Agent**: Google Gemini 1.5 Pro (latest) でタイトル/本文/タグ(JSON)を生成
3) **ファクトチェックAgent**: Google Gemini 1.5 Pro (latest) の検索ツールを用いた検証結果を反映し本文を修正
4) **ドラフトAgent**: Playwrightで note.com に下書き/公開（storageState を利用）

## 現在の状況

- ワークフローは Gemini 1.5 Pro (latest) を中心に再構成済みですが、GitHub Actions 上での通し実行テストはまだ行っていません。
- `GEMINI_API_KEY` が未設定の場合はリサーチ/執筆/ファクトチェックの各ジョブが即時に失敗します。Google Cloud プロジェクトで Gemini API と Google Search Tool の利用権限が有効になっていることを確認してください。
- note.com への投稿部分は Playwright を使用する既存実装を流用しているため、以前と同様に `NOTE_STORAGE_STATE_JSON` の鮮度管理が必要です。
- Perplexity 併用版（`.github/workflows/note-perplexity.yaml`）も Gemini ベースに置き換えていますが、こちらも実運用前に Secrets とActions権限を設定した上での試験実行を推奨します。

## 反映状態と次のアクション

- **反映状況**: `main` ブランチには Gemini 版ワークフローがすでに取り込まれており、追加のデプロイ作業は不要です。GitHub Actions の手動実行を開始すれば現行構成で動作します。
- **必要な設定**: `GEMINI_API_KEY` と `NOTE_STORAGE_STATE_JSON` を含む Secrets が未登録の場合は、ワークフローが開始直後に失敗します。必要に応じて `PERPLEXITY_API_KEY` も追加してください。
- **検証のお願い**: 本番利用前に「dry_run: true」で少なくとも1回通しで実行し、生成物とログを確認してください。Playwright 操作やGoogle Search Toolの権限不足がないか検証することをおすすめします。
- **運用開始の目安**: 上記の事前テストで問題がなければ、`dry_run: false`・`is_public` の設定に応じてドラフト保存/公開まで実行できます。異常が見つかった場合はGitHub Actionsのログと `.note-artifacts` のアーティファクトを参照して調査してください。

---

## 事前準備（リポジトリSecrets）

以下の環境変数をGitHub Actionsのリポジトリシークレットに設定してください：

- `GEMINI_API_KEY`（必須）- Google Gemini APIキー
- `NOTE_STORAGE_STATE_JSON`（必須）- note.comのログイン状態（後述の手順で取得）
- `PERPLEXITY_API_KEY`（任意）- Perplexity検索APIキー（Perplexity版ワークフローを利用する場合）

---

## 実行方法

GitHub Actions > Note Workflow を手動実行し、以下の入力を与えます：

- **theme**: 記事テーマ（必須）
- **target**: 想定読者（必須）
- **message**: 伝えたい核メッセージ（必須）
- **cta**: 読後のアクション（必須）
- **tags**: カンマ区切りタグ（任意）
- **is_public**: true/false（公開 or 下書き保存）
- **dry_run**: true/false（投稿スキップ）

---

## note-state.json の取得手順（Playwright storageState）

note.com へのログイン情報は Playwright の storageState(JSON) を用います。以下の手順で取得してください。

### 1. ローカルで Playwright を準備

```bash
npm init -y
npm install playwright
npx playwright install chromium
```

### 2. 手動ログインスクリプトの作成と実行

まず、以下の内容で `login-note.mjs` を作成してください：

```javascript
import { chromium } from 'playwright';
import fs from 'fs';

const STATE_PATH = './note-state.json';

// 手動ログインのため環境変数は不要

const wait = (ms) => new Promise(r => setTimeout(r, ms));

(async () => {
  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext();
  const page = await context.newPage();

  await page.goto('https://note.com/login');

  console.log('手動でログインしてください。ログイン完了を自動検知します...');
  
  // ログイン完了を自動検知（note.comのトップページに遷移するまで待機）
  try {
    await page.waitForURL(/note\.com\/?$/, { timeout: 300000 }); // 5分待機
    console.log('ログイン完了を検知しました！');
  } catch (error) {
    console.log('ログイン完了の検知に失敗しました。手動でEnterキーを押してください。');
    await new Promise(resolve => {
      process.stdin.once('data', () => {
        resolve();
      });
    });
  }

  console.log('ログイン状態を保存中...');

  // 保存
  await context.storageState({ path: STATE_PATH });
  console.log('Saved:', STATE_PATH);

  await browser.close();
})();
```

そして、スクリプトを実行します：

```bash
node login-note.mjs
```

### 3. 手動ログイン手順

1. スクリプトを実行すると、ブラウザが自動で起動し note.com のログインページが開きます
2. **手動で**ログインを完了してください（メール、Google、Twitter等、お好みの方法で）
3. ログインが完了すると、スクリプトが自動でログイン状態を検知します（最大5分待機）
4. 検知に失敗した場合は、ターミナルでEnterキーを押してください
5. カレントディレクトリに `note-state.json` が生成されます

### 4. Secret に保存

1. 生成された `note-state.json` の内容を全選択してコピー
2. GitHub リポジトリ Settings > Secrets and variables > Actions > New repository secret
3. Name: `NOTE_STORAGE_STATE_JSON`
4. Secret: コピーした JSON の内容全体を貼り付け

---

## 動作イメージ

1. **Research ジョブ**: GeminiのGoogle検索ツールを使用して最新の一次情報を収集しMarkdownレポートを生成
2. **Write ジョブ**: Gemini 1.5 Pro (latest) がリサーチ内容からnote記事のタイトル・本文・タグをJSONで生成
3. **Fact-check ジョブ**: Gemini 1.5 Pro (latest) がGoogle検索ツールで事実確認し、本文に反映
4. **Post ジョブ**: Playwright でnote.comに自動投稿
   - `is_public: false` の場合は「下書き保存」
   - `is_public: true` の場合は「公開」
   - `dry_run: true` の場合は投稿をスキップ

ワークフロー実行時に `NOTE_STORAGE_STATE_JSON` を一時ファイルに展開し、Playwright の storageState として使用します。

---

## 注意事項

- **storageStateの期限**: storageState は期限切れ・無効化されることがあります。ログイン情報が切れた場合は、同手順で再取得してください
- **UI変更への対応**: note.com 側のUI変更でセレクタが変わる場合があります。その際は `post.mjs` 内のセレクタ調整が必要です
- **AI生成コンテンツ**: 生成AIの出力は誤情報を含む場合があります。公開前に最終レビューをおすすめします
- **手動ログイン**: セキュリティ上の理由から、パスワードを環境変数に保存せず、手動ログイン方式を採用しています
- **機密情報の管理**: `login-note.mjs` と `note-state.json` は `.gitignore` に追加されており、Gitリポジトリには含まれません

---

## 技術スタック

- **GitHub Actions**: CI/CDパイプライン
- **Google Gemini API (@google/generative-ai)**: リサーチ・執筆・ファクトチェックAgent（`gemini-1.5-pro-latest` モデル）
- **Perplexity API**: オプションのリサーチデータ取得
- **Playwright**: note.com への自動投稿
- **marked**: Markdown to HTML変換

---

## ファイル拡張子について

- **`.mjs`ファイル**: ES Modules（`import`/`export`）を使用するJavaScriptファイルです
- **package.jsonの設定**: `"type": "module"` がない場合でも、`.mjs` 拡張子でES Modulesが使用できます
- **従来の`.js`**: CommonJS（`require`/`module.exports`）方式です

---

## 参考

- [Google Gemini API](https://ai.google.dev/)
- [Perplexity API](https://docs.perplexity.ai/)
- [Playwright](https://playwright.dev/)
