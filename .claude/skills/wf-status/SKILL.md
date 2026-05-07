---
name: wf-status
description: Use when コレクション制作の進捗を読むだけで確認したいとき（実行はしない）。「どこまで進んだ？」「workflow-state 見せて」「制作中コレクション一覧」など、collections/planning/ 配下の現在地を一覧・詳細表示するときに使用する。チャンネル登録者数など YouTube 側の統計は /channel-status
---

## Overview

アクティブなコレクションの進捗一覧・詳細を表示する。新旧スキーマ両対応。

## 前提

`config/channel/` が存在すること（`load_config()` でロード可能）。

存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-import` を案内

## Instructions

### 手順

1. `collections/planning/` を Glob で探索
2. 各コレクションの `workflow-state.json` を読み込み
3. スキーマ判別: `steps` キーがあれば旧スキーマ（v1）、なければ新スキーマ（v2）

### 新スキーマ（v2）の表示

```
アクティブなコレクション

| # | コレクション名 | フェーズ | 状態 |
|---|---------------|---------|------|
| 1 | Alice Tea Party | prepared | 制作中（Suno 作成待ち） |
| 2 | Dragon's Lair  | mastered | 公開準備完了 |
```

phase 値と日本語ラベル:
- `planning` → 企画中
- `prepared` → 制作中
- `mastered` → 公開準備完了
- `publishing` → 公開中
- `complete` → 完了

`prepared` の場合は `assets` フラグで詳細表示:
- `assets.raw_master = null` + `music_engine = suno` → 「Suno 作成待ち」
- `assets.raw_master = null` + `music_engine = lyria` → 「Lyria 生成待ち（/wf-next で開始）」
- `assets.raw_master != null` + `assets.master_audio = null` → 「ミキシング+マスタリング待ち」

詳細表示（コレクション1つの場合 or ユーザーが指定した場合）:
```
コレクション: Alice Tea Party
テーマ: alice-tea-party
音楽エンジン: suno
フェーズ: prepared（制作中）

素材状況:
  サムネイル:      ✅
  ループ動画:      ✅
  音楽プロンプト:   ✅
  raw マスター:    ❌
  最終マスター:    ❌
  動画:           ❌
  概要欄:         ❌
```

### 旧スキーマ（v1）の表示

従来通り `steps` の `approved = true` のステップ数で進捗計算（分母4）。

### 補足

- `workflow-state.json` が存在しないコレクションは「未トラッキング」として表示する
- スキーマ詳細は `.claude/references/workflow/schema.md` を参照

## Cross References

- 新規開始: `/wf-new`
- 次ステップ実行: `/wf-next`
