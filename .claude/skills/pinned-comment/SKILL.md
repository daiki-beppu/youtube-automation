---
name: pinned-comment
description: Use when 新規アップロード動画にチャンネルオーナーの固定コメントを自動投稿したいとき。`config/channel/pinned-comment.json` のテンプレを使い dry-run でプレビューしてから apply で投稿する。ピン留めは YouTube Data API 非対応のため Studio UI で手動。「固定コメント」「ピンコメント」「オーナーコメント」「リピーター動線」など視聴者との接点を増やす運用に関わる場面で使用すること
---

## Overview

YouTube Data API v3 の `commentThreads.insert` で、自チャンネルの動画にトップレベルコメント（オーナーコメント）を自動投稿する。`comments-reply` と同じ dry-run / apply / history パターンを踏襲し、`yt-pinned-comment` CLI から実行する。

- **dry-run**: 生成コメント文字列のプレビューのみ（API 書き込みなし）
- **apply**: 実投稿 + 履歴 JSON (`pinned_comment_history.json`) を更新
- **preflight**: 投稿前に `videos.list(part="status")` を一括で叩き、削除済み動画 (`video_not_found`) / private 動画 (`video_private`) を自動 skip する（apply 段階で 404/403 を踏むのを防ぐ）
- **ピン留め**: YouTube Data API 非対応のため、投稿後に Studio UI で手動ピン留め（1 動画 1 クリック）

## 前提

- `config/channel/pinned-comment.json` を作成済み（`pinned_comment.enabled: true` に設定）
- `auth/token.json` が `youtube.force-ssl` スコープで発行済み（`comments-reply` が動いていれば同スコープで動作）
- 投稿対象動画がアップロード完了済み（`upload_tracking.json` の `complete_collection.video_id` または `workflow-state.json` の `upload.video_id` に video_id が記録されている）

## 設定 (`config/channel/pinned-comment.json`)

```json
{
  "pinned_comment": {
    "enabled": true,
    "history_file": "pinned_comment_history.json",
    "delay_between_posts_sec": 2.5,
    "default_language": "en",
    "templates": {
      "ja": "{scene_phrase} {scene_emoji}\n\n（オーナーコメント本文）",
      "en": "{scene_phrase} {scene_emoji}\n\n(owner comment body)"
    }
  }
}
```

利用できるプレースホルダ: `{scene_phrase}` `{video_title}` `{theme}` `{scene_emoji}`
（コレクション指定時は `workflow-state.json` の `scene_phrases` / `planning.scene_emoji` / `theme` から展開される）

## 実行フロー

### Phase 1: dry-run でプレビュー

最新コレクションを対象にする場合:

```bash
uv run yt-pinned-comment --collection collections/live/<latest-dir> --dry-run --lang en
```

video_id 直接指定の場合:

```bash
uv run yt-pinned-comment --video-id <id1> --video-id <id2> --dry-run --lang en
```

確認ポイント:
- `planned` 件数が期待値か
- 生成テキストが `scene_phrase` / `scene_emoji` を正しく展開しているか
- `SKIP ... already_posted` / `SKIP ... video_not_found` / `SKIP ... video_private` が想定どおりか

### Phase 2: apply で投稿

```bash
uv run yt-pinned-comment --collection collections/live/<latest-dir> --apply --lang en
```

実行後、Studio UI の Comments タブで投稿コメントを **手動ピン留め**する（API でのピン留めは不可）。

## Quick Reference

| 引数 | 説明 |
|------|------|
| `--collection <path>` | `collections/live/<dir>` を指定。`upload_tracking.json` → `workflow-state.json` の順で video_id を自動解決 |
| `--video-id <id>` | 動画 ID 直接指定（複数指定可、`--collection` とは排他） |
| `--dry-run` / `--apply` | どちらか必須（排他） |
| `--lang ja\|en` | テンプレート言語（省略時は設定の `default_language`） |
| `--json` | 結果を JSON で出力（machine-readable） |

終了コード: `0`=正常 / `1`=設定・認証エラー / `2`=投稿エラーあり

## 運用フロー（推奨）

1. `/video-upload <collection-path>` で動画公開
2. 公開直後に `yt-pinned-comment --collection <path> --dry-run` でプレビュー
3. テキスト OK なら `--apply` で投稿
4. Studio UI でピン留め
5. `pinned_comment_history.json` に記録され、同一 video_id への二重投稿は防止される

## トラブルシュート

- `pinned_comment.enabled=false です` → `config/channel/pinned-comment.json` で `enabled: true` に変更
- `SKIP ... already_posted` ばかり → 対象動画は既に投稿済み。`pinned_comment_history.json` を確認
- `SKIP ... video_not_found` → 削除済み / 存在しない video_id。collection の状態ファイルを確認
- `SKIP ... video_private` → private 公開待ち。公開後に再実行
- `ERR ... status=403` → OAuth スコープが `youtube.force-ssl` を含むか確認（含まなければ `auth/token.json` を削除して再認証）
- `ERR ... status=400`（commentsDisabled）→ 動画のコメント許可が無効になっている

## 非スコープ

- ピン留めの API 自動化（Data API v3 が非対応 → Studio UI 手動）
- 既存コメントの編集・削除
- リプライへの返信（それは `/comments-reply` の責務）
