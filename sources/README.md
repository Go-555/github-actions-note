# Sources

このフォルダに `.md` ファイルを置くと、夜間の "Generate Articles" ワークフローが自動的に内容を取り込み、`articles-queue/` に投稿候補を生成します。

- Front Matter に `title`, `tags`, `is_public` などを設定すると、そのまま記事に引き継がれます。
- `processed/` には取り込み済みのファイルが自動移動されるため、手動削除は不要です。
- 1回の生成で処理する件数は環境変数 `GENERATE_LIMIT`（デフォルト=1）で制御できます。

README.md や `_` で始まるファイルは自動生成の対象外です。
