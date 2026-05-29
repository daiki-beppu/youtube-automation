---
name: comments-reply
description: Use when YouTube のコメントに自動返信したいとき。`config/channel/comments.json` のルールに沿って LLM 生成返信を dry-run でプレビューしてから apply で実反映する。二重返信は履歴ファイル (`comment_reply_history.json`) で防止。「コメント返信」「自動返信」「コメント対応」「視聴者返信」「リプライ」など、コメント対応の自動化に関わる場面で使用すること
---

## Overview

YouTube Data API v3 の `commentThreads.list` / `comments.insert` を使い、
自チャンネルの動画に寄せられたコメントへ `comments.json` のルールに従って自動返信する。

- **dry-run**: 対象コメントと生成返信テキストのプレビューのみ（API 書き込みなし）
- **apply**: 実際に YouTube 側へ返信を反映、同時に履歴 JSON を更新

## 前提

- `config/channel/comments.json` を設定済み（`examples/channel_config.example/comments.json` を参考）
- `comments.enabled: true` になっている
- `auth/token.json` が `youtube.force-ssl` スコープで発行済み

## 実行フロー

### Phase 1: ルール / provider の確認

`config/channel/comments.json` の `rules` と `generator` を Read ツールで確認する。
ルールは `priority` の降順で評価され、最初にマッチしたものが採用される。
返信文は常に LLM が生成する。既定 provider は `codex`、`provider: "gemini"` を使う場合は `model` を設定する。

### Phase 2: dry-run で内容をプレビュー

```bash
uv run yt-comments-reply --dry-run --limit 5
```

- `--video-id <id>` で特定動画のみに絞れる（複数指定可）
- `--since 2026-04-01` で日付以降のコメントのみ対象
- `--json` で機械可読な出力

出力の確認ポイント:
- `返信候補` が期待件数になっているか
- `reply` 欄の LLM 生成文がチャンネル persona とコメント言語に合っているか
- `skipped` に `already_replied` / `no_rule_matched` があるかを確認

## 設定スキーマ

```json
{
  "comments": {
    "enabled": true,
    "rules": [
      {
        "name": "greeting_ja",
        "keywords": ["こんにちは"],
        "language": "ja",
        "priority": 10,
        "provider": "codex"
      }
    ],
    "generator": {
      "provider": "codex",
      "model": null,
      "channel_persona": "Warm YouTube channel host",
      "max_length": 280,
      "fallback_on_error": "skip",
      "requests_per_minute": 30
    }
  }
}
```

- `comments.generator.provider`: `codex` / `gemini`。省略時は `codex`
- `comments.rules[].provider`: ルール単位の provider override。省略時は global provider
- `fallback_on_error`: `skip` / `retry`
- **破壊的変更**: 旧 `comments.generator.type`、`comments.templates`、`comments.rules[].template_key`、`comments.rules[].generator`、`fallback_on_error: "template"` は廃止。downstream の `config/channel/comments.json` は `provider` 軸へ移行する

### Phase 3: apply で反映

```bash
uv run yt-comments-reply --apply --limit 5
```

- `実返信` が期待件数になっていれば成功
- `errors` が 0 でない場合は `comment_reply_history.json` に書き込まれない該当コメントを要確認

## Quick Reference

| 引数 | 説明 |
|------|------|
| `--dry-run` / `--apply` | どちらか必須（排他） |
| `--video-id <id>` | 対象動画 ID（複数指定可、省略時は全動画） |
| `--limit N` | 1 実行での返信件数上限（`comments.max_replies_per_run` を上書き） |
| `--per-video-limit N` | 動画あたりのコメント取得上限（default: 100） |
| `--since <ISO8601>` | これより新しいコメントのみ対象 |
| `--json` | 結果を JSON で出力 |

## トラブルシュート

- `comments.enabled=false です` → `config/channel/comments.json` で `enabled: true` に変更
- `all already_replied` ばかり → 既に対応済みコメントのみ。`comment_reply_history.json` を確認
- API エラー `status=403` → OAuth スコープが `youtube.force-ssl` を含むか確認（含まなければ `auth/token.json` を削除して再認証）

## 非スコープ

- 1 件ずつ対話承認するモード（別 issue 予定）
- langdetect 等の自動言語判定（ルール側で明示指定する前提）
- センチメント分析・要約
