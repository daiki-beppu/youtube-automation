---
name: wf-status
description: "Use when コレクション制作の進捗を読むだけで確認するとき（実行しない）。「どこまで進んだ？」「制作中コレクション一覧」で発動。YouTube 統計は /channel-status"
---

## Overview

アクティブなコレクションの進捗一覧・詳細を表示する。新旧スキーマ両対応。

> **このセッションで初めて `/wf-*` を呼ぶ場合は、先に [`docs/workflow-cheatsheet.md`](../../../docs/workflow-cheatsheet.md) の判定フローを 1 回だけユーザーに提示すること**（CLAUDE.md §6 参照）。

## When to Use

| 状況 | 使う？ |
|---|---|
| 「どこまで進んだ？」「読むだけ」 | ✅ 使う |
| 「次のステップ実行して」 | ❌ `/wf-next` を使う（`/wf-status` は **実行系を一切呼ばない**） |
| 「workflow-state.json を見せて」 | ✅ 使う（生 JSON ではなく phase / assets を整形表示する） |
| 「YouTube 側の登録者数・再生数を見せて」 | ❌ `/channel-status` を使う |

`/wf-status` は読み取り専用で `workflow-state.json` を一切更新しない。`/wf-next` を呼んだら何が起きるか **事前に確認するための skill**。

**唯一の例外**: raw_master 突合チェック（後述）が不整合を検知し、**ユーザーが明示承認した場合のみ** `yt-raw-master-check --apply` で `assets.raw_master` / `updated_at` を修復する（#1668）。承認なしの書き込みは一切行わない。

## 前提

`config/channel/` が存在すること（`load_config()` でロード可能）。

存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-new`（既存チャンネル取り込みモード）を案内

## Instructions

### 手順

1. `collections/planning/` を Glob で探索
2. 各コレクションの `workflow-state.json` を読み込み
3. スキーマ判別: `steps` キーがあれば旧スキーマ（v1）、なければ新スキーマ（v2）
4. 新スキーマ（v2）のコレクションには `uv run yt-raw-master-check <dir>` で `assets.raw_master` と `01-master/` 実ファイルの突合チェックを実行（読み取り専用 / #1668）
   - **exit 2（不整合）**: 進捗表示に ⚠️ を添えて CLI の警告（例:「assets.raw_master が実ファイルと一致しません。更新しますか」）を提示し、AskUserQuestion で更新可否を確認する
     - 承認 → `uv run yt-raw-master-check <dir> --apply` で修復し、修復後の状態で進捗を表示する
     - 非承認 → 何も書き込まず、不整合が残っている旨を表示に含める（次回起動時も同じ警告が再表示される）。**警告を出さずに silent 続行するのは禁止**
   - **exit 1（エラー）**: workflow-state.json 破損等として「障害時ガイダンス」に従う

### 新スキーマ（v2）の表示

```
アクティブなコレクション

| # | コレクション名 | フェーズ | 状態 |
|---|---------------|---------|------|
| 1 | Late Night Jazz | prepared | 制作中（Suno 作成待ち） |
| 2 | Forest Walk     | mastered | 公開準備完了 |
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
- `assets.raw_master != null` + `assets.master_audio = null` + `load_config().workflow.wf_next.skip_manual_mastering = true` → 「raw master 直採用待ち（/wf-next で mastered へ進行）」
- `assets.raw_master != null` + `assets.master_audio = null` + `load_config().workflow.wf_next.skip_manual_mastering = false` → 「ミキシング+マスタリング待ち」

詳細表示（コレクション1つの場合 or ユーザーが指定した場合）:
```
コレクション: Late Night Jazz
テーマ: late-night-jazz
音楽エンジン: suno
フェーズ: prepared（制作中）
ディレクトリ骨格: ✅ OK
                （欠落時: ⚠️ 01-master 欠落 — `uv run yt-collection-preflight <dir名> --fix` で補完）

素材状況:
  サムネイル:      ✅
  ループ動画:      ✅
  音楽プロンプト:   ✅
  raw マスター:    ❌
  最終マスター:    ❌
  動画:           ❌
  概要欄:         ❌
```

ディレクトリ骨格行は `uv run yt-collection-preflight <dir名>`（`--fix` なし = 読み取り専用）の結果で判定する（#1494）。欠落があっても `/wf-status` からは補完しない — `--fix` 実行はユーザーまたは `/wf-next` に委ねる。

### 旧スキーマ（v1）の表示

従来通り `steps` の `approved = true` のステップ数で進捗計算（分母4）。

### 補足

- `workflow-state.json` が存在しないコレクションは「未トラッキング」として表示する
- スキーマ詳細は `.claude/skills/wf-new/references/schema.md` を参照

## 障害時ガイダンス

進捗表示は `collections/planning/` の JSON を読むだけで外部サービスを呼ばない。

| 状況 | 兆候 | 対処 |
|---|---|---|
| workflow-state.json 不在/破損 | 対象ディレクトリに状態ファイルが無い | `/wf-new` で初期化するかパスを確認（外部サービスに依存しないため API 障害・quota の影響は受けない） |

## Cross References

- 新規開始: `/wf-new`
- 次ステップ実行: `/wf-next`
