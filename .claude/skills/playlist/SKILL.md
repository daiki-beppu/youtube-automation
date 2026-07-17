---
name: playlist
description: "Use when プレイリストの作成・割り当て・確認をするとき。「プレイリスト作って」「初投稿」「初回投稿」「初回公開前にプレイリスト初期化」「/playlist」で発動"
---

## Overview

`uv run yt-playlist-status` と `uv run yt-playlist-manager` を 1 スキルに統合し、プレイリストの状態確認・作成・動画割り当て・クリーンアップを案内する。

`config/channel/playlists.json` を Canonical ソースとして読み、定義されたプレイリストを YouTube 上に反映する。テーマ別マッチングルール（`auto_add_activities` / `auto_add_themes`）や全動画自動追加（`auto_add`）に対応。

## 前提

`config/channel/playlists.json` が存在し、`playlists` セクションが定義されていること。未定義の場合は `/channel-new`（再生成モード）を案内する。

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

`uv run yt-playlist-manager --status` も同じ `PlaylistStatusViewer` に委譲するため、`uv run yt-playlist-status` と等価。

## 完了条件

実行したモードのコマンドが exit 0 で終了した時点で完了。init モードでは加えて `playlists.json` の全エントリに `playlist_id` が書き戻され、`uv run yt-playlist-status` で `(未作成)` が残っていないことを確認する。status モードは一覧表示のみで完了。

## 想定 API call 数

| API | call 数 / 実行 | 変動要因 |
|---|---|---|
| playlistItems.list（1 unit、--status / yt-playlist-status） | Σ ceil(各プレイリスト項目数 / 50) | プレイリスト数・項目数 |
| playlists.insert（50 units、--init） | 新規作成プレイリスト数 | 未作成エントリ数 |
| playlistItems.insert（50 units、--init / --assign） | 割当動画本数（+ 重複確認の list 数件） | 割当対象の動画数 |
| playlistItems.delete（50 units、--clean-deleted） | 削除エントリ数 | 削除済み / 非公開動画数 |

- 上限 / 承認: 全モードに `--dry-run` があり、書き込み前にプレビューで確認できる。status モードは read のみで書き込み API を呼ばない。

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

**注意**: `--dry-run` フラグなしが実反映。`yt-channel-settings` のように `--apply` 経由ではないので、dry-run → 確認 → 本番の 2 段階運用を徹底する。ここでの「確認」は、dry-run 出力（作成されるプレイリスト名と割り当て件数）をユーザーに提示し、問題ない旨の応答を得ることを指す。dry-run 出力を提示しないまま実反映コマンドを実行しない。

実行後、`playlists.json` の各エントリに `playlist_id` が書き戻される。

**初投稿前の扱い**: `collections/live/` がまだ空でも `--init` を実行してよい。この場合は未作成プレイリストの作成と `playlist_id` 書き戻しが主目的で、初回動画の追加は後続の `/video-upload` に任せる。collection 型では `/video-upload` 内部の自動 assign (`assign_video()`) が追加を担う。初投稿前に `(未作成)` が残っているとアップロード時の自動 assign がスキップされるため、公開前に必ず初期化する。

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
- `/channel-new`（再生成モード） — `playlists.json` の初期定義
- `config/channel/playlists.json` — Canonical ソース
- `src/youtube_automation/scripts/playlist_manager.py` — 実装本体
- `src/youtube_automation/scripts/playlist_status.py` — 状態表示の読み取り専用 viewer
