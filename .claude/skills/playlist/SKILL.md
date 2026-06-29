---
name: playlist
description: "Use when プレイリストの作成・動画割り当て・状態確認をしたいとき。「プレイリスト作って」「プレイリスト整理」「動画をプレイリストに追加」「プレイリスト状況」「削除済み動画を整理」「初投稿」「初回投稿」「初回公開前にプレイリスト初期化」「/playlist」など、`config/channel/playlists.json` に基づくプレイリスト CRUD の場面で使用すること"
---

## Overview

`yt-playlist-status` と `yt-playlist-manager` を 1 スキルに統合し、プレイリストの状態確認・作成・動画割り当て・クリーンアップを案内する。

`config/channel/playlists.json` を Canonical ソースとして読み、定義されたプレイリストを YouTube 上に反映する。テーマ別マッチングルール（`auto_add_activities` / `auto_add_themes`）や全動画自動追加（`auto_add`）に対応。

## 前提

`config/channel/playlists.json` が存在し、`playlists` セクションが定義されていること。未定義の場合は `/channel-setup` を案内する。

## When to Use

- 新チャンネル開設後、`playlists.json` に定義したプレイリストを YouTube 上に初期化したいとき
- 新チャンネルの初投稿 / 初回公開前に、未作成プレイリストを作成して `playlist_id` を書き戻したいとき
- 単一動画を特定テーマのプレイリストに割り当てたいとき
- 現状どの動画がどのプレイリストに入っているかを確認したいとき
- YouTube で削除済み / 非公開化された動画のエントリをプレイリストから除去したいとき

## Quick Reference

| モード | コマンド | 説明 |
|--------|---------|------|
| **status** | `uv run yt-playlist-status` | 全プレイリストの ID・動画数・マッチングルールを表示（読み取り専用） |
| **init** | `uv run yt-playlist-manager --init [--dry-run]` | `playlists.json` 定義の全プレイリストを作成 + live/ 配下の全動画を割り当て |
| **assign** | `uv run yt-playlist-manager --assign VIDEO_ID --theme THEME [--dry-run]` | 単一動画を該当プレイリストに追加（テーマからマッチング） |
| **clean-deleted** | `uv run yt-playlist-manager --clean-deleted [--dry-run]` | 全プレイリストから削除済み/非公開動画のエントリを除去 |

`yt-playlist-manager --status` も同じ `PlaylistStatusViewer` に委譲するため、`yt-playlist-status` と等価。

## Instructions

### Step 1: 状態確認（必ず最初に実行）

```bash
uv run yt-playlist-status
```

- プレイリストごとに `playlist_id`・動画数・マッチングルールを一覧表示
- `(未作成)` が表示されたら Step 2 の init モードに進む

### Step 2: 初期化（プレイリスト未作成のとき）

`config/channel/playlists.json` の定義に従って全プレイリストを作成 + live/ 配下の動画を一括割り当て:

```bash
uv run yt-playlist-manager --init --dry-run    # まずプレビュー
uv run yt-playlist-manager --init              # 実反映
```

**注意**: `--dry-run` フラグなしが実反映。`yt-channel-settings` のように `--apply` 経由ではないので、dry-run → 確認 → 本番の 2 段階運用を徹底する。

実行後、`playlists.json` の各エントリに `playlist_id` が書き戻される。

**初投稿前の扱い**: `collections/live/` がまだ空でも `--init` を実行してよい。この場合は未作成プレイリストの作成と `playlist_id` 書き戻しが主目的で、初回動画の追加は後続の `/video-upload` 内部 `assign_video()` に任せる。初投稿前に `(未作成)` が残っているとアップロード時の自動 assign がスキップされるため、公開前に必ず初期化する。

### Step 3: 単一動画の追加（運用フェーズ）

新しい動画を YouTube にアップロードしたあと、該当プレイリストに追加:

```bash
uv run yt-playlist-manager --assign <VIDEO_ID> --theme <THEME>
```

- `<THEME>` は `workflow-state.json` の `theme` 値（`content.json` の `theme_scenes` で定義されたキー）
- マッチするプレイリストキーが返り値として表示される
- `"all"` プレイリストには末尾追加、それ以外は先頭追加（YouTube 表示順制御）

**自動連携**: `/video-upload` から呼ばれる `collection_uploader` 内部でも同じ `assign_video()` が走るため、通常運用では手動 assign は不要。手動 assign が必要なのは: 過去動画の再割り当て / 新テーマ追加後のレトロフィット / マッチングルール変更後の再同期。

### Step 4: 削除動画のクリーンアップ（定期メンテナンス）

YouTube 側で削除された動画が `playlistItems` に残ったままになることがあるため、定期的に除去:

```bash
uv run yt-playlist-manager --clean-deleted --dry-run    # 影響範囲をプレビュー
uv run yt-playlist-manager --clean-deleted              # 実反映
```

## 障害時ガイダンス

| 状況 | 兆候 | 対処 |
|---|---|---|
| OAuth 未認証/失効 | `auth.oauth_handler` の `FileNotFoundError`（`client_secrets.json` 不在）/ `AuthError` / HTTP 403 | 初回認証フローを再実行。403 が続く場合は `auth/token.json` を削除しスコープを確認のうえ再認証 |
| YouTube quota / rate | HTTP 429 / 403 `quotaExceeded` | 日次 quota（既定 10,000 units・太平洋時間 0 時リセット）を待つか呼び出しを抑える |
| API 障害 / サービス停止 | HTTP 503 / タイムアウト | Google Cloud / YouTube のステータスを確認し、時間を置いて再実行 |

## Cross References

- `/video-upload` — アップロード時に内部で `assign_video()` が呼ばれる（手動 assign 不要が基本）
- `/channel-setup` — `playlists.json` の初期定義
- `config/channel/playlists.json` — Canonical ソース
- `src/youtube_automation/scripts/playlist_manager.py` — 実装本体
- `src/youtube_automation/scripts/playlist_status.py` — 状態表示の読み取り専用 viewer
