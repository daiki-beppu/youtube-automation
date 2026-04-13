---
name: status
description: Use when プロジェクトの全体像を把握したいとき、最新のチャンネル統計が必要なとき、他のスキル実行前に状況確認したいとき。「チャンネル状況」「登録者数」「今の状態」「最新情報」「どうなってる？」など、プロジェクトの現在地を確認する場面で必ず使用すること
---

## Overview

チャンネルの最新統計 + 個別動画パフォーマンスを YouTube API から取得する。

## 前提

`config/channel_config.json` が存在すること。

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
