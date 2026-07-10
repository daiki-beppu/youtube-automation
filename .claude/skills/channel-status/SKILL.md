---
name: channel-status
description: "Use when チャンネルの YouTube 統計（登録者・再生回数）を取得するとき。「登録者数は？」「YouTube の数字」で発動。制作進捗は /wf-status"
---

## Overview

チャンネルの最新統計 + 個別動画パフォーマンスを YouTube API から取得する。

## 完了条件

`uv run yt-channel-status` が exit 0 で終了し、チャンネル統計とコレクション一覧をユーザーに提示した時点で完了。

## 前提

`config/channel/` が存在すること（`load_config()` でロード可能）。

存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-new`（既存チャンネル取り込みモード）を案内

## Instructions

以下のコマンドを実行:

```bash
uv run yt-channel-status
```

取得される情報:
- チャンネル統計: 登録者数、総再生回数、動画数
- コレクション一覧: タイトル、公開日、再生数、総視聴時間、平均視聴時間

制作中コレクションの進捗（`collections/planning/` の workflow-state.json）は本スキルでは扱わない — `/wf-status` を使う。

`--json` オプションで JSON 出力、`--summary` でサマリーのみ表示も可能。

## 障害時ガイダンス

| 状況 | 兆候 | 対処 |
|---|---|---|
| OAuth 未認証/失効 | `auth.oauth_handler` の `FileNotFoundError`（`client_secrets.json` 不在）/ `AuthError` / HTTP 403 | 初回認証フローを再実行。403 が続く場合は `auth/token.json` を削除しスコープを確認のうえ再認証 |
| YouTube quota / rate | HTTP 429 / 403 `quotaExceeded` | 日次 quota（既定 10,000 units・太平洋時間 0 時リセット）を待つか呼び出しを抑える |
| API 障害 / サービス停止 | HTTP 503 / タイムアウト | Google Cloud / YouTube のステータスを確認し、時間を置いて再実行 |
