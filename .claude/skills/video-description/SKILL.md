---
name: video-description
description: "Use when コレクションのYouTube概要欄を自動生成する必要があるとき。Complete Collection 形式に対応（情景フック＋タイムスタンプ＋Perfect for）。概要欄、タイトル作成、SEO最適化、メタデータ生成、動画の説明文など、YouTube投稿用テキストが必要な場面で必ず使用すること"
---

## Overview

コレクション用の YouTube 概要欄を自動生成します。ファーストビューに情景フックとタイムスタンプ（チャプター）を配置し、シーン描写・Perfect for セクション・Usage & Attribution・ハッシュタグで構成します。

## 前提

`config/channel/` が存在すること（`load_config()` でロード可能）。

存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-import` を案内

## When to Use

- コレクションの動画が完成し、YouTube 概要欄が必要なとき
- Complete Collection の概要欄を作成するとき

## Quick Reference

| 引数 | 説明 | 例 |
|------|------|-----|
| `$ARGUMENTS` | コレクションディレクトリパス（省略可） | `/video-description collections/planning/20260303-clm-merlin-study-collection/` |
| 未指定 | アクティブなコレクションを自動検出 | `/video-description` |

## Channel Adaptation

Complete Collection 形式（情景フック＋タイムスタンプ＋Perfect for）で生成する。
ハッシュタグ・CTA・チャンネル URL は `config/channel/*.json` から取得。

## Instructions

あなたは YouTube 概要欄最適化スペシャリストです。`config/channel/*.json` からチャンネル名・ジャンル・ハッシュタグ等を読み取り、チャンネルに最適化された概要欄を生成します。

### 対象コレクション

```
$ARGUMENTS
```

対象コレクションの `workflow-state.json` と `20-documentation/suno-prompts.md` を読み込み、コレクションのテーマ・雰囲気を把握してから概要欄を生成してください。

### Benchmark 概要欄 TTP 参照

概要欄生成前に、最新の `docs/benchmarks/*.md` または `data/benchmark_*.json` を確認する。

1. `docs/benchmarks/*.md` に `概要欄TTPサンプル` がある場合は、そのサンプルを優先して参照する
2. Markdown にサンプルがない場合は、最新の `data/benchmark_*.json` の `channels[].videos[].description` を参照する
3. 参照した概要欄から、冒頭文の構造・Tracklist/目次書式・CTA・ハッシュタグ記法・装飾量を抽出し、TTP 対象として生成内容へ反映する
4. benchmark 概要欄データが存在しない場合のみ、既存の Complete Collection テンプレートへフォールバックする

### Complete Collection テンプレート

情景フック＋タイムスタンプ＋Perfect for 構成のテンプレート。装飾ヘッダー・Usage & Attribution 本文は
`config.default.yaml` の `section_headers` / `usage_attribution_lines` に集約されており、
チャンネル特性に応じて `config/skills/video-description.yaml` で上書きできる（BGM 系・ゲーム音楽系・ASMR 系などへ展開可能）。

テンプレート本文・ポイント解説は `references/description-templates.md` の「Complete Collection 概要欄テンプレート」セクションを参照すること（記載値はデフォルトのサンプル）。

### タイムスタンプ生成手順

1. **個別トラックがある場合**（`02-Individual-music/`）: `metadata_generator.py` の `analyze_audio_files()` で自動計算
2. ファイル名規約 `\d+-pattern-[a-d]` を持つコレクションでは、`format_timestamps_text()` がテーマ見出し（`── Pattern A: <name> ──`）と楽曲行（`00:00 Track 1`）を組み合わせた **個別楽曲単位** のタイムスタンプを返す。テーマ見出し行は YouTube のチャプター parser に拾われないよう先頭 timestamp を持たない（重複 timestamp は chapter list 全体を無効化する）
   - テーマ表示名は `workflow-state.json` の `planning.music.patterns[<letter>].display_name`（無ければ `.name` を `Pattern X: <name>` に整形）から解決される。両方無ければ `Pattern X` にフォールバック
   - pattern 規約に従わない legacy コレクションはテーマ見出し無しのフラット出力（後方互換）
3. チャプター名は原則トラックタイトル（ファイル名から生成）を使用
4. **同名トラックの LLM リネーム**:
   - `BAHMetadataGenerator.detect_duplicate_track_titles()` を呼び、case-insensitive で重複しているタイトル群を取得する
   - 戻り値が空ならこの手順をスキップ
   - 重複があれば、本 skill を実行している LLM 自身が以下の情報を読み、コレクションのテーマ・シーン展開（時系列／空間／情緒のいずれか）を把握してから固有名に書き換える:
     - `workflow-state.json` の `planning.music.patterns[<letter>]`（pattern ごとの mood / instruments / tempo 等）
     - `20-documentation/suno-prompts.md`（pattern 別の Style / Lyrics 文脈）
     - 当該トラックの `pattern_key`（テーマ群が同じか別か判定）
   - 命名方針:
     - 元曲名のコア語彙は保つ（同一テーマ群であることを視聴者に示すため）
     - コレクションの物語アークに沿った短い修飾語（英語 2〜3 語）で区別する。例: `Quiet Hours` × 2 → `Quiet Hours — Dusk` / `Quiet Hours — Dawn`、`Rain Window` × 3 → `Rain Window I` 型ではなく `Rain Window — Distant` / `Rain Window — Closer` / `Rain Window — Drift`
     - 末尾に `v1〜v9` / ロマン数字 `I〜VIII` を付けない（preflight の variation suffix 検出で reject される）
   - 決めたリネーム結果は `BAHMetadataGenerator.apply_track_display_names({index: "新表示名", ...})` に渡す。これで:
     - `self.tracks[i]["title"]` が上書きされる
     - `workflow-state.json` の `track_display_names` に `{filename: display_name}` 形式で永続化される（次回ロード時 `_apply_persisted_display_names()` で再適用される）
   - `02-Individual-music/` のファイル名や ID3 タグは変更しない（派生アセットへの波及防止）
5. `00:00` から始まること（YouTube チャプター要件）、最低3チャプター

### Perfect for テーマ別カスタマイズ

skill-config (`.claude/skills/video-description/config.default.yaml` / 上書き `config/skills/video-description.yaml`)
の `perfect_for_themes` からコレクションのテーマにマッチするキーを選択:

- テーマが辞書にない場合は `config/channel/content.json` の `descriptions.perfect_for`（デフォルト）を使用
- 絵文字は skill-config の `theme_emoji` から引く（例: 📚(study), 🌙(sleep), 🍺(tavern), 🌊(ocean), 🌿(forest), 🔮(druid/magic), 🌧️(rain), 🔥(hearth)）

### タイトル形式

`config/channel/content.json` の `title.template` に基づいてタイトルを生成する。

- `[総時間]`: `2+ Hours` / `1+ Hour` 等（切り捨て表記）
- ユースケースはコレクションテーマに応じて調整

### タグ（YouTube タグ欄）

`config/channel/content.json` の `tags.base` + `tags.themes.<theme>` を結合してタグリストを生成する。

テーマに応じてキーワードを調整すること。

### 必須要素

各要素は YouTube SEO と視聴者信頼の両面で CTR・視聴維持率に寄与する:

1. **誇張表現回避**: Epic, Ultimate 等を避け Ancient, Enchanted 等を使用 — 誇張は CTR を下げる傾向があり、チャンネルブランドの信頼性も損なう
2. **AI 透明性**: Usage & Attribution セクションを含める — AI 生成コンテンツの透明性維持はコミュニティとの信頼関係の基盤
3. **SEO 最適化**: `config/channel/content.json` の `tags.base` に基づく戦略的キーワード — YouTube 検索とおすすめアルゴリズムの両方で発見性を高める
4. **ハッシュタグ**: 13個（base + theme固有）— YouTube は概要欄の最初の3ハッシュタグをタイトル下に表示するため、数と順序が重要
5. **タイムスタンプ必須**: `00:00` 始まり、3チャプター以上 — YouTube がチャプターを自動認識し、検索結果にプレビュー表示される

### Cards（YouTube Studio で手動設定）

概要欄生成時に、カードセクションも descriptions.md に含める。設定は skill-config の `cards` セクション参照。

- **カード種類**: 動画カード（Video card）のみ
- **枚数**: **1動画1枚**（最小限運用）
- **タイミング**: skill-config `cards.timing`（デフォルト `12:00`）
- **リンク先**: 最新のコレクション（新コレクション公開時に全動画を更新）
- **テキスト**: skill-config `cards.text_template`（デフォルト `Up next from {channel_name}`）

### 品質チェック

- [ ] 誇張表現なし（Epic/Ultimate等 不使用）
- [ ] AI 透明性あり（Usage & Attribution セクション）
- [ ] チャンネル CTA 含む
- [ ] ハッシュタグ 13個（base + theme）
- [ ] モバイル読みやすさ（セクション区切り）
- [ ] タイムスタンプあり（00:00 始まり、3チャプター以上）
- [ ] カードセクション含む（タイミング・テキスト・リンク先）

### 概要欄保存

概要欄は必ずコレクションの `20-documentation/descriptions.md` に保存する。
保存フォーマット（ヘッダー、概要欄本文、タイトル案、タグ、Cards、品質チェック）は
`references/description-templates.md` の「descriptions.md 保存フォーマット」セクションを参照すること。

保存後、`workflow-state.json` の `description.generated = true` に更新する。

## 障害時ガイダンス

概要欄はエージェント生成（テキスト）で、外部サービスを呼ばない。

| 状況 | 兆候 | 対処 |
|---|---|---|
| 入力データ/設定の不在 | 参照先のローカルファイルが見つからない | 該当ファイルを用意するか前段スキルを先に実行（外部サービスに依存しないため API 障害・quota の影響は受けない） |

## Next Step

概要欄生成後:
→ `/video-upload <collection-path>` で YouTube へアップロード
