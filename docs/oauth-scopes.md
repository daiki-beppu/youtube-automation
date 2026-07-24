# OAuth scope 分離と skill × scope 対応表

issue #1699 で導入した用途別 OAuth token の設計と、各 skill / CLI の実効 scope の対応表。
token 漏洩時の blast radius を read-only に限定し、「どの skill がどの scope で動くか」を機械的に説明できる状態を保つ。

## 用途別 token ファイル

| token ファイル | scope | 用途 | 発行方法 |
|---|---|---|---|
| `auth/token.json` | `youtube` / `youtube.force-ssl` / `yt-analytics.readonly` / `yt-analytics-monetary.readonly` | write 系（upload / metadata 更新 / playlist 操作 / コメント投稿） | `uv run yt-oauth`（従来どおり。各 write CLI の初回実行でも発行される） |
| `auth/token.readonly.json` | `youtube.readonly` / `yt-analytics.readonly` / `yt-analytics-monetary.readonly` | read-only 系（Analytics 収集 / ベンチマーク / ステータス閲覧） | `uv run yt-oauth --readonly` |
| `auth/token_streaming.json` | `youtube` | ライブ配信 stream key 取得（`youtube.readonly` では streamName がマスクされるため write scope が必要。#135） | `uv run yt-fetch-stream-key` の初回実行 |

scope 定義の単一ソースは `src/youtube_automation/infrastructure/auth/youtube.py` の
`YouTubeOAuthHandler.SCOPES` / `READONLY_SCOPES`（stream 用は `scripts/fetch_stream_key.py`）。

## token 選択と fallback の仕様

- read 系の入口は instance-scoped な `infrastructure/google/youtube.py` の
  `YouTubeClients` に集約されている。
  `analytics` / `reporting` / `youtube_readonly` は `token.readonly.json` を
  優先使用する。Analytics / Reporting API 用の credentials は
  `YouTubeOAuthHandler` の readonly handler 経由で取得される。
- `token.readonly.json` が**未発行**の場合はサイレント失敗せず、warning ログで
  `uv run yt-oauth --readonly` による発行を案内した上で `token.json`（全 scope）へ
  フォールバックする。既存の下流チャンネルは再認証なしで従来どおり動作する。
- token の探索順は `token.json` と同じ（channel 側 `auth/` → main worktree 側 `auth/`。#1721）。
- write 系（`youtube`）は従来どおり `token.json` を使う。

## skill × 実効 scope 対応表

「readonly 優先」= `token.readonly.json` 発行済みならそれを使用、未発行なら `token.json` へ fallback。

| skill | 主な CLI / モジュール | 実効 scope | token |
|---|---|---|---|
| /analytics-collect, /analytics-analyze | `yt-analytics`（analytics_system / analytics_collector / reporting_analytics） | read-only | readonly 優先 |
| /channel-status | `yt-channel-status` | read-only | readonly 優先 |
| /benchmark（動画収集） | `yt-benchmark-collect` | read-only | readonly 優先 |
| /viewer-voice（コメント収集） | `yt-benchmark-comments` | `youtube.force-ssl`（`commentThreads.list` の API 要件） | `token.json` |
| /discover-competitors | `yt-discover-competitors` | read-only | readonly 優先 |
| /metadata-audit | `yt-metadata-audit`（監査のみ） | read-only | readonly 優先 |
| /playlist（状態確認） | `yt-playlist-status` | read-only | readonly 優先 |
| /streaming（帯域集計） | `yt-stream-bandwidth` / `yt-stream-archive-check` | read-only | readonly 優先 |
| /video-upload | `domains/uploads/youtube.py` | write（`youtube`） | `token.json` |
| /playlist（作成・割り当て） | `yt-playlist-manager` | write（`youtube`） | `token.json` |
| /channel-new（seed / 設定 push） | `yt-channel-seed` / `yt-channel-settings` | write（`youtube`） | `token.json` |
| /video-description ほか一括更新 | `yt-bulk-update-desc` / `yt-bulk-update-synthetic-media` | write（`youtube`） | `token.json` |
| /comments-reply | `yt-comments-reply` | write（`youtube.force-ssl`） | `token.json` |
| /pinned-comment | `yt-pinned-comment` | write（`youtube.force-ssl`） | `token.json` |
| 字幕アップロード | `yt-captions-upload` | write（`youtube.force-ssl`） | `token.json` |
| /streaming（stream key 取得） | `yt-fetch-stream-key` | write（`youtube`） | `token_streaming.json` |

## 運用手順（下流チャンネルでの readonly token 発行）

1. チャンネルリポジトリのルートで `uv run yt-oauth --readonly` を実行する
2. ブラウザ認証を完了すると `auth/token.readonly.json` が 0o600 で保存される（gitignore 済み）
3. 以後、read-only 系 skill は自動的に readonly token を使う（コード変更・設定不要）

未発行のままでも動作は変わらない（warning ログのみ）。発行は任意だが、最小権限で
運用したいチャンネルから順次発行することを推奨する。

## 最小権限化ロードマップ

- 済: read 系入口（YouTubeClients / analytics / benchmark / status 系 CLI）の readonly token 優先化（#1699）
- 済: stream key の専用 token 分離（#135）
- 将来候補: write 系をさらに upload（`youtube`）と comment（`youtube.force-ssl`）に分割する。
  現状は write 系 skill が同一チャンネル運用者の操作で完結しており、分割の運用コスト
  （再認証 2 回）が blast radius 縮小効果を上回るため見送り
