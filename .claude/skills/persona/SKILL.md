---
name: persona
description: Use when ターゲット視聴者のペルソナを定義・見直したいとき。「誰が聴くか」「ペルソナ設定」「ターゲット」「視聴者像」「ターゲット層」「リスナー像」など。/viewer-voice の結果を前提とし、/viewing-scene の入力になる。チャンネル立ち上げ・方向性見直し時に必ず使用すること
---

## Overview

コメント分析 + ベンチマークタグ分析 + Web 調査で主要ペルソナ 2-3 名を定義する。

## 前提

- `config/channel/` が存在すること（`load_config()` でロード可能）。
  存在しない場合 → 新規チャンネルなら `/channel-new`、既存チャンネルなら `/channel-import` を案内。
- `docs/plans/viewer-voice-analysis.md` が存在すること。
  未実施の場合は先に `/viewer-voice` を実行するよう案内。

## 実行フロー

### Phase 1: データ収集（サブエージェント並列）

**2つのサブエージェントを並列起動**（Agent ツール）:

**Agent 1: ベンチマークタグ分析**
- `data/benchmark_YYYYMMDD.json`（最新）を読み込み
- 全ベンチマーク動画のタグを集計（頻度順）
- チャンネルごとのタグ戦略の違いを分析
- 視聴者が使う検索キーワードの傾向を抽出

**Agent 2: コミュニティ調査**
- `config/channel/content.json` の `tags.base` と `suno.genre_line`（またはチャンネルのジャンルキーワード）から動的に検索クエリを構築して WebSearch で調査する
- `config/channel/content.json` の `tags.base` と `genre.*` からキーワードを構築（例: `{genre.primary} music listener demographics` / `{genre.style} music youtube audience` / `{genre.context} background music community`）
- 関連コミュニティ（Reddit, Discord 等）の住人像を推定
- ジャンル横断での視聴者傾向

### Phase 2: ペルソナ構築

Phase 1 の結果 + `viewer-voice-analysis.md` の利用シーン・感情分析を統合し、
ペルソナ候補を導出。各ペルソナを以下のテンプレートで定義:

- 名前（架空）
- 年齢・性別傾向・職業
- 趣味・関心
- 音楽の利用シーン
- 求めている体験
- よく使うプラットフォーム
- 検索キーワード
- 自チャンネルへの示唆

### Phase 3: 優先順位決定

AskUserQuestion で第一ペルソナを選択:
```
question: "第一ペルソナをどれにしますか？"
options:
  - 各ペルソナの要約（名前 + 利用シーン + 自チャンネルへの影響）
```

### Phase 4: レポート保存

`docs/channel/personas/persona-definition.md` を生成。
ディレクトリが存在しなければ `mkdir -p docs/channel/personas` で作成してから書き出す。
選択結果に基づき、タイトル・タグ・概要欄への影響もまとめる。

## 関連ファイル

- `docs/plans/viewer-voice-analysis.md` — コメント分析結果（入力）
- `data/benchmark_YYYYMMDD.json` — タグデータ
- `config/channel/content.json` — 現在のタグ設定
