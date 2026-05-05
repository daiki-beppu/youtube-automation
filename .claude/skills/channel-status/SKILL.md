---
name: channel-status
description: Use when チャンネル全体の YouTube 統計（登録者数・総再生回数・動画別パフォーマンス）を取得したいとき。「登録者数は？」「チャンネルの最新情報」「YouTube の数字見せて」など、YouTube API から数字を取得するときに使用する。ローカルのコレクション制作進捗は /wf-status
---

## Overview

チャンネルの最新統計 + 個別動画パフォーマンスを YouTube API から取得する。

## 前提

`config/channel/` が存在すること（`load_config()` でロード可能）。

存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-import` を案内

## Instructions

以下のコマンドを実行:

```bash
uv run yt-channel-status
```

取得される情報:
- チャンネル統計: 登録者数、総再生回数、動画数
- コレクション一覧: タイトル、公開日、再生数、いいね数、コメント数
- 制作中コレクション: `collections/planning/` 内の workflow-state.json から現在フェーズを表示

`--json` オプションで JSON 出力、`--summary` でサマリーのみ表示も可能。
