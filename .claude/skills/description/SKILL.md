---
name: description
description: Use when コレクションのYouTube概要欄を自動生成する必要があるとき。Complete Collection 形式に対応（情景フック＋タイムスタンプ＋Perfect for）。概要欄、タイトル作成、SEO最適化、メタデータ生成、動画の説明文など、YouTube投稿用テキストが必要な場面で必ず使用すること
---

## Overview

コレクション用の YouTube 概要欄を自動生成します。ファーストビューに情景フックとタイムスタンプ（チャプター）を配置し、シーン描写・Perfect for セクション・Usage & Attribution・ハッシュタグで構成します。

## When to Use

- コレクションの動画が完成し、YouTube 概要欄が必要なとき
- Complete Collection の概要欄を作成するとき

## Quick Reference

| 引数 | 説明 | 例 |
|------|------|-----|
| `$ARGUMENTS` | コレクションディレクトリパス（省略可） | `/description collections/planning/20260303-clm-merlin-study-collection/` |
| 未指定 | アクティブなコレクションを自動検出 | `/description` |

## Channel Adaptation

Complete Collection 形式（情景フック＋タイムスタンプ＋Perfect for）で生成する。
ハッシュタグ・CTA・チャンネル URL は `channel_config.json` から取得。

## Instructions

あなたは YouTube 概要欄最適化スペシャリストです。`channel_config.json` からチャンネル名・ジャンル・ハッシュタグ等を読み取り、チャンネルに最適化された概要欄を生成します。

### 対象コレクション

```
$ARGUMENTS
```

対象コレクションの `workflow-state.json` と `20-documentation/suno-prompts.md` を読み込み、コレクションのテーマ・雰囲気を把握してから概要欄を生成してください。

### Complete Collection テンプレート

BGM チャンネル向けにアダプトした概要欄テンプレート。

```
[絵文字装飾]. [情景フック — 詩的な1行。コレクションの世界に引き込む]
[音楽の誘い — リスナーへの語りかけ1行] [絵文字]

[音楽の特徴 — 2行で楽器・ムード・雰囲気を描写]

- Genre : [ジャンル名, サブジャンル]
- Vibe : [形容詞4つ]
- Best for : [用途4つ]



⎯⎯⎯⎯⎯✦ ⋆˚ 𝙈𝙪𝙨𝙞𝙘 𝙏𝙞𝙢𝙚 ⋆˚✦⎯⎯⎯⎯⎯

💽 [コレクション名 — 英語ボールド Unicode]

00:00 [Track/Chapter 1]
XX:XX [Track/Chapter 2]
...


🎧 If you enjoyed the vibe, feel free to save and subscribe for more 🌧️
🔔 {channel_config: channel.cta_subscribe}

{channel_config: channel.url}


⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯
🎨 𝐀𝐫𝐭 & 🎹 𝐌𝐮𝐬𝐢𝐜 𝐛𝐲 {channel_config: channel.name}
• Original AI composition • Free for personal use
⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯



{channel_config: descriptions.hashtags}
```

**テンプレートのポイント:**
- 冒頭は **詩的な情景** + **リスナーへの語りかけ**（YouTube の折りたたみ前に表示される）
- メタデータは `Genre / Vibe / Best for` の3行（検索性 + 一目で内容がわかる）
- タイムスタンプセクションは装飾付きヘッダー（`⎯⎯✦ ⋆˚ Music Time ⋆˚✦⎯⎯`）
- CTA は短く温かい語調（「保存＆登録」をさりげなく）
- クレジットは最小限（Art & Music by）
- ハッシュタグは最後にまとめて配置

### タイムスタンプ生成手順

1. **個別トラックがある場合**（`02-Individual-music/`）: `metadata_generator.py` の `analyze_audio_files()` で自動計算
2. **composition.json がある場合**（Lyria DJ 生成）: `phases[].at_min` と `phases[].name_en` を使用
3. チャプター名は `composition.json` の `name_en` またはトラックタイトルを使用
4. `00:00` から始まること（YouTube チャプター要件）、最低3チャプター

### Perfect for テーマ別カスタマイズ

`channel_config.json` の `descriptions.perfect_for_themes` からコレクションのテーマにマッチするキーを選択:
- テーマが辞書にない場合は `descriptions.perfect_for`（デフォルト）を使用
- 絵文字は以下を使い分け: 📚(study), 🌙(sleep), 🍺(tavern), 🌊(ocean), 🌿(forest), 🔮(druid/magic), 🌧️(rain), 🔥(hearth)

### タイトル形式

`channel_config.json` の `title.template` に基づいてタイトルを生成する。

- `[総時間]`: `2+ Hours` / `1+ Hour` 等（切り捨て表記）
- ユースケースはコレクションテーマに応じて調整

### タグ（YouTube タグ欄）

`channel_config.json` の `tags.base` + `tags.themes.<theme>` を結合してタグリストを生成する。

テーマに応じてキーワードを調整すること。

### 必須要素

各要素は YouTube SEO と視聴者信頼の両面で CTR・視聴維持率に寄与する:

1. **誇張表現回避**: Epic, Ultimate 等を避け Ancient, Enchanted 等を使用 — 誇張は CTR を下げる傾向があり、チャンネルブランドの信頼性も損なう
2. **AI 透明性**: Usage & Attribution セクションを含める — AI 生成コンテンツの透明性維持はコミュニティとの信頼関係の基盤
3. **SEO 最適化**: `channel_config.json` の `tags.base` に基づく戦略的キーワード — YouTube 検索とおすすめアルゴリズムの両方で発見性を高める
4. **ハッシュタグ**: 13個（base + theme固有）— YouTube は概要欄の最初の3ハッシュタグをタイトル下に表示するため、数と順序が重要
5. **タイムスタンプ必須**: `00:00` 始まり、3チャプター以上 — YouTube がチャプターを自動認識し、検索結果にプレビュー表示される

### Cards（YouTube Studio で手動設定）

概要欄生成時に、カードセクションも descriptions.md に含める。

- **カード種類**: 動画カード（Video card）のみ
- **枚数**: **1動画1枚**（最小限運用）
- **タイミング**: **12:00** 固定（平均視聴時間 12〜21分 → 離脱直前に提示）
- **リンク先**: 最新のコレクション（新コレクション公開時に全動画を更新）
- **テキスト**: "Up next from {channel.name}"

### 品質チェック

- [ ] 誇張表現なし（Epic/Ultimate等 不使用）
- [ ] AI 透明性あり（Usage & Attribution セクション）
- [ ] チャンネル CTA 含む
- [ ] ハッシュタグ 13個（base + theme）
- [ ] モバイル読みやすさ（セクション区切り）
- [ ] タイムスタンプあり（00:00 始まり、3チャプター以上）
- [ ] カードセクション含む（タイミング・テキスト・リンク先）

### 概要欄保存

概要欄は必ずコレクションの `20-documentation/descriptions.md` に以下の構成で保存すること:

```markdown
# [Collection Name] — YouTube 概要欄

*生成日: YYYY-MM-DD*
*トラック数: N / 総時間: Xh Xm Xs*

---

## Complete Collection 概要欄

\`\`\`
[概要欄本文]
\`\`\`

---

## タイトル案

\`\`\`
[タイトル]
\`\`\`

---

## タグ（YouTube タグ欄）

\`\`\`
[タグリスト]
\`\`\`

---

## Cards (YouTube Studio で手動設定)

\`\`\`
Card ([タイミング]): "[ティーザーメッセージ]" → [リンク先動画タイトル]
\`\`\`

---

## 品質チェック

- [x] 誇張表現なし
- [x] AI 透明性あり
- [x] チャンネル CTA 含む
- [x] ハッシュタグ 13個
- [x] モバイル読みやすさ
- [x] カードセクション含む
```

保存後、`workflow-state.json` の `description.generated = true` に更新する。

## Next Step

概要欄生成後:
→ `/upload <collection-path>` で YouTube へアップロード
