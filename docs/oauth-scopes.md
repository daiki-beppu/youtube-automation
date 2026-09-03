# YouTube 権限を安全に使い分ける

このページでは、YouTube チャンネルの操作に使う OAuth token と権限（scope）の
使い分けを説明します。OAuth client の作成や認証をまだ済ませていない場合は、先に
[GCP / YouTube API セットアップ](oauth-setup.md)を完了してください。

読み取り専用の作業には権限を絞った token を使い、動画のアップロードやコメント投稿
などの更新操作には書き込み可能な token を使います。万一 token が漏洩した場合の
影響を抑えながら、必要な操作を継続できます。

## 用途別 token ファイル

| token ファイル | scope | 用途 | 発行方法 |
|---|---|---|---|
| `auth/token.json` | `youtube` / `youtube.force-ssl` / `yt-analytics.readonly` / `yt-analytics-monetary.readonly` | write 系（upload / metadata 更新 / playlist 操作 / コメント投稿） | `uv run yt-oauth`（従来どおり。各 write CLI の初回実行でも発行される） |
| `auth/token.readonly.json` | `youtube.readonly` / `yt-analytics.readonly` / `yt-analytics-monetary.readonly` | read-only 系（Analytics 収集 / ベンチマーク / ステータス閲覧） | `uv run yt-oauth --readonly` |
| `auth/token_streaming.json` | `youtube` | ライブ配信 stream key 取得（読み取り専用権限では stream key を取得できないため、専用 token を使用） | `uv run yt-fetch-stream-key` の初回実行 |

通常は各コマンドが適切な token を自動で選ぶため、利用者が scope を指定する必要は
ありません。

## token 選択と fallback の仕様

- Analytics、ベンチマーク収集、ステータス確認などの read-only 操作は
  `token.readonly.json` を優先して使う。
- `token.readonly.json` が**未発行**の場合はサイレント失敗せず、warning ログで
  `uv run yt-oauth --readonly` による発行を案内した上で `token.json`（全 scope）へ
  フォールバックする。既存の下流チャンネルは再認証なしで従来どおり動作する。
- token は対象チャンネルの `auth/` から自動的に読み込まれる。
- write 系（`youtube`）は従来どおり `token.json` を使う。

## skill × 実効 scope 対応表

「readonly 優先」= `token.readonly.json` 発行済みならそれを使用、未発行なら `token.json` へ fallback。

| skill | 主なコマンド | 実効 scope | token |
|---|---|---|---|
| /analytics --collect, /analytics --analyze | `yt-analytics` | read-only | readonly 優先 |
| /analytics --status | `yt-channel-status` | read-only | readonly 優先 |
| /channel-research --benchmark（動画収集） | `yt-benchmark-collect` | read-only | readonly 優先 |
| /channel-research --voice（コメント収集） | `yt-benchmark-comments` | `youtube.force-ssl`（`commentThreads.list` の API 要件） | `token.json` |
| /channel-research --discover | `yt-discover-competitors` | read-only | readonly 優先 |
| /audit --metadata | `yt-metadata-audit`（監査のみ） | read-only | readonly 優先 |
| /publish --playlist（状態確認） | `yt-playlist-status` | read-only | readonly 優先 |
| /streaming（帯域集計） | `yt-stream-bandwidth` / `yt-stream-archive-check` | read-only | readonly 優先 |
| /publish --upload | YouTube アップロード | write（`youtube`） | `token.json` |
| /publish --playlist（作成・割り当て） | `yt-playlist-manager` | write（`youtube`） | `token.json` |
| /setup（seed / 設定 push） | `yt-channel-seed` / `yt-channel-settings` | write（`youtube`） | `token.json` |
| /video --describe ほか一括更新 | `yt-bulk-update-desc` / `yt-bulk-update-synthetic-media` | write（`youtube`） | `token.json` |
| /reply | `yt-comments-reply` | write（`youtube.force-ssl`） | `token.json` |
| /publish --pinned | `yt-pinned-comment` | write（`youtube.force-ssl`） | `token.json` |
| 字幕アップロード | `yt-captions-upload` | write（`youtube.force-ssl`） | `token.json` |
| /streaming（stream key 取得） | `yt-fetch-stream-key` | write（`youtube`） | `token_streaming.json` |

## 運用手順（下流チャンネルでの readonly token 発行）

1. チャンネルリポジトリのルートで `uv run yt-oauth --readonly` を実行する
2. ブラウザ認証を完了すると `auth/token.readonly.json` が 0o600 で保存される（gitignore 済み）
3. 以後、read-only 系 skill は自動的に readonly token を使う（コード変更・設定不要）

未発行のままでも動作は変わらない（warning ログのみ）。発行は任意だが、最小権限で
運用したいチャンネルから順次発行することを推奨する。

## 現在の権限分離方針

- read-only 操作は `token.readonly.json` を優先する。
- stream key の取得には `token_streaming.json` を使う。
- upload とコメント投稿は `token.json` を共有する。書き込み用途をさらに分割すると
  再認証の回数が増えるため、現在は日常運用の分かりやすさを優先している。
