---
name: thumbnail
description: Use when コレクションのサムネイル画像が必要で、CTR最適化されたプロンプト生成 + 画像生成プロバイダー（Gemini / OpenAI）での画像生成を行いたいとき。サムネイル、画像生成、CTR改善、ビジュアル制作、アイキャッチ、main.pngなど、視覚コンテンツの作成に関わる場面で必ず使用すること
---

## Overview

コレクション用サムネイルを `config/skills/thumbnail.yaml`（skill-config）に基づいて生成する。
チャンネルごとにスタイル・キャラ・参照画像が異なり、すべて skill-config から動的に読み取る。
画像生成プロバイダー（Gemini / OpenAI）は `image_generation.provider` で切り替え可能。

## 前提

以下の 2 つが揃っていること:

1. `config/channel/` が存在する（`load_config()` でロード可能）
2. `config/skills/thumbnail.yaml` が存在する（配布された `.claude/skills/thumbnail/config.default.yaml` をベースにチャンネルでカスタマイズ）

いずれか不足する場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-import` を案内

## When to Use

- コレクションが確定し、サムネイル制作に着手するとき
- CTR 最適化されたサムネイルが必要なとき

## Quick Reference

| 引数 | 説明 | 例 |
|------|------|-----|
| `$ARGUMENTS` | テーマ・活動指定（省略可） | `/thumbnail fiddle playing` |
| 未指定 | デフォルト活動で生成 | `/thumbnail` |

## プロバイダー切り替え

`config/skills/thumbnail.yaml` の `image_generation.provider` で選択する:

| provider | 特徴 | 必要なシークレット |
|---|---|---|
| `gemini` | Gemini Image (Nano Banana 系) | `GOOGLE_CLOUD_PROJECT` ＋ ADC |
| `openai` | OpenAI gpt-image 系（CJK 文字描画が綺麗、16:9/9:16 ネイティブ対応） | `OPENAI_API_KEY` |

OpenAI provider 使用時は `image_generation.openai.aspect_ratio` を `"16:9"` または `"9:16"` のいずれかに設定（thumbnail スキルは内部で 16:9 固定）。

## Channel Adaptation

**すべての設定は `config/skills/thumbnail.yaml` から読み取る。**
スキル内にチャンネル固有のハードコードはしない。読み込みは以下のコマンドで確認できる:

```bash
uv run python -c "from youtube_automation.utils.skill_config import load_skill_config; import json; print(json.dumps(load_skill_config('thumbnail'), indent=2, ensure_ascii=False))"
```

実行前に以下を確認:

1. `image_generation.provider` → 使用するプロバイダー（`gemini` / `openai`）
2. `image_generation.gemini.model` → 使用する Gemini モデル
3. `image_generation.gemini.style` → スタイル説明（参照画像ベース or プロンプトベース）
4. `image_generation.gemini.prompt_prefix` → プロンプト冒頭の固定文（キャラ描写等）
5. `image_generation.gemini.reference_images` → 参照画像の定義（あれば参照画像モード）
6. `image_generation.gemini.fixed_character` → 固定キャラの設定（あればキャラ固定モード）
7. `image_generation.gemini.composition_rules` → 構図・環境のルール
8. `image_generation.gemini.thumbnail_text` → テキストオーバーレイの設定
9. `image_generation.gemini.generation_mode` → 生成モード（後述）
10. `image_generation.gemini.brand_background` → チャンネル統一背景色（single_step / diff_from_reference で使用）
11. `image_generation.gemini.color_themes` → テーマ別カラーパレット（single_step モードで差し替え）

## 生成モード判定

`image_generation.gemini.generation_mode` を確認:

| モード | 説明 |
|---|---|
| `ttp_swap` | 競合サムネ + 自キャラアイコンの 2 参照でキャラ置換 |
| `single_step` | テキスト付き参照画像から差分のみ指示、1 ステップで完成 |
| `diff_from_reference` | 既存キャラ画像を参照に差分指示 |
| `two_phase`（未指定時のフォールバック）| 従来の 2 フェーズ（背景 → テキストオーバーレイ）|

### 参照画像モード（`reference_images` が定義されている場合）

参照画像を渡してスタイルを維持する方式。

```bash
uv run yt-generate-image \
  --prompt "<prompt_prefix を含むプロンプト>" \
  --reference <channel_dir>/<reference_images.default> \
  --output <collection-path>/10-assets/main-v1.jpg -y
```

**参照画像の選択ロジック**:
- `reference_images` のキーからシーンに最適なものを選択
- `path_base: "channel_dir"` の場合、パスはチャンネルディレクトリからの相対パス
- `--reference` 使用時は `composition_prefix` が自動スキップされる（generate_image.py 修正済み）

### プロンプトベースモード（`reference_images` が未定義の場合）

参照画像なしでプロンプトのみで生成する方式（フォールバック）。

```bash
uv run yt-generate-image \
  --prompt "<完全なプロンプト>" \
  --output <collection-path>/10-assets/main-v1.jpg -y
```

`composition_prefix` が自動付加される。

## プロンプト構築

### 1. prompt_prefix を取得

`image_generation.gemini.prompt_prefix` をプロンプト冒頭に配置。

### 2. fixed_character から活動を組み立て

`image_generation.gemini.fixed_character` がある場合:
- `outfit`: 服装描写
- `instrument`: 楽器（テーマに応じて持ち替え可なら変更）
- `face`: 顔の向き指示

### 3. composition_rules から環境・制約を適用

- `environment`: 許可される環境
- `allowed_actions`: 使える活動
- `ng_actions`: 禁止パターン
- `brightness`: 明るさルール

### 4. プロンプトテンプレート（参照画像モード）

```
{prompt_prefix}, {表情}.
She/He/It wears {outfit}. {ポーズ・活動}. {環境描写}.
{光と雰囲気}. {face}.
No text, no words, no letters, no typography.
```

### 5. プロンプト末尾（プロンプトベースモード）

`reference_images` がない場合、スタイル句を末尾に付加する。
チャンネル `CLAUDE.md` にスタイル句指定があればそれを使用。なければデフォルト:

```
Hyper-detailed digital matte painting blending photorealism with subtle painterly
illustration touches. Widescreen 16:9 aspect ratio.
```

## ワークフロー

### TTP Swap モード（`generation_mode: "ttp_swap"`）

ベンチマーク競合の高再生サムネを **構図リファレンス**、自チャンネルのアイコンを **キャラリファレンス**
として 2 枚同時に渡し、「キャラだけ差し替える」手法。

**前提**:
- `data/thumbnail_compare/benchmark/<channel>-<video_id>.jpg` に競合サムネがキャッシュ済み
  （未取得なら `uv run yt-thumbnail-compare --no-open` で取得）
- `branding/icon.png` に自チャンネルキャラのアイコンが配置済み

**プロンプトは短く保つのが重要**（長文はノイズ）。3 段階テンプレ:

```
# 1. キャラ置換（必須・これだけでも動く）
Replace the character in the first image with the character from the second image.

# 2. リブランド（任意）
Remove the copyright text in the top-right corner. Remove the logo icon and
tagline text in the bottom-left corner. Both corners should be clean empty background.

# 3. オリジナリティ（任意）
Change the action: <自チャンネル固有の動作>. Change the <小道具のディテール> to <固有要素>.
```

**コマンド**:

```bash
uv run yt-generate-image \
  --reference data/thumbnail_compare/benchmark/<benchmark-thumb>.jpg \
  --reference branding/icon.png \
  --prompt "<上記テンプレ>" \
  --output collections/planning/<collection>/10-assets/main-v1.jpg -y
```

**運用上の注意**:
- **リトライ前提**: 画像生成プロバイダーは同一プロンプトでも瞬発的にエラーを返す。2〜3 回リトライで通る
- **テキスト継承**: 参照画像内のキャッチコピー・ジャンルタグ・フォントはデフォルトで完全継承される。変えたい部分だけ明示指示
- **ブランド置換**: `Replace every occurrence of the word 'X' with 'Y'` で文字列差し替え可
- **キャラサイズ**: 縮小傾向がある場合は `fills about 55% of the frame, bust-up portrait` を追記
- **コスト**: 単価は `cost_tracker.PRICING` 参照（最大 3 回試行込み = 初回 + 最大 2 回リトライ）。provider・モデル・画像サイズ別に自動算出される

### Single-Step モード（`generation_mode: "single_step"`）

テキスト付き参照画像（テキストレイアウト・背景テクスチャ・オブジェクト配置を含む）を参照にして、
**変更点だけ**をプロンプトで指示する。背景生成とテキストオーバーレイが 1 回の生成で完了する。

**重要**: 参照画像と同じ要素（レイアウト、固定オブジェクト、テキスト配置）はプロンプトに含めない。
差分のみを指示することで、参照画像のクオリティを維持しつつ変更が正しく反映される。

1. `image_generation.gemini.color_themes` からテーマのカラー設定を取得
2. `image_generation.gemini.diff_prompt_template` のプレースホルダーを置換してプロンプト構築:
   - `{background}`: カラーテーマの背景色（未指定時は `image_generation.gemini.brand_background` を使用）
   - `{candle}`, `{cocktail_description}` などオブジェクト系プレースホルダ: `ideate.objects` や `color_themes` 配下の値
   - `{title_line1}`, `{title_line2}`: コレクションタイトル

3. 生成:

```bash
uv run yt-generate-image \
  --reference <channel_dir>/<reference_images.default> \
  --prompt "<diff_prompt_template を置換したプロンプト>" \
  --output <collection-path>/10-assets/thumbnail-v1.jpg -y
```

4. `open` でプレビュー → ユーザー承認 → `cp thumbnail-v1.jpg thumbnail.jpg`
5. 背景画像（テキストなし）も必要な場合は、テキストなしの参照画像で別途生成

差分プロンプトの具体例は skill-config の `image_generation.gemini.diff_prompt_template` を参照し、チャンネル固有のオブジェクト・カラーを埋める。

### Two-Phase モード（従来方式・フォールバック）

#### Phase 1: 背景候補生成（main.png）

**main.png が既に存在する場合は Phase 1 をスキップして Phase 2 へ進む。**
（`/ideate` で本番品質のプレビューが生成され、選択後にコピーされている）

main.png が存在しない場合のみ:
1. テーマに合わせてプロンプトを構築（上記テンプレート）
2. 参照画像モードなら `reference_images` から適切な画像を選択
3. 生成: `yt-generate-image --reference <参照画像> --prompt <プロンプト> --output 10-assets/main-v1.jpg -y`
4. `open` でプレビュー → ユーザー承認 → `cp main-v1.jpg main.png`

#### Phase 2: テキストオーバーレイ（thumbnail.jpg）

1. `image_generation.gemini.thumbnail_text` からテキスト設定を取得
2. テキストオーバーレイプロンプトを構築:

**`thumbnail_text.text_overlay_prompt` が定義されている場合（推奨）:**
テンプレート内の `{title_line1}`, `{title_line2}`, `{channel_name}` をコレクションのタイトルとチャンネル名で置換して使用。

**未定義の場合（フォールバック）:**
```
Add text to this image. Add two lines of text in a classic serif font.
First line smaller: '<Title Line 1>' in light weight.
Second line larger and bolder: '<Title Line 2>' directly below with
almost no line spacing. Both lines in <color>.
Below the title, add '<channel_name>' in very small spaced-out small
caps, slightly more transparent. No decorations — only clean text.
Do not change the background image in any way.
```

3. 生成: `yt-generate-image --reference 10-assets/main.png --prompt <テキスト指示> --output 10-assets/thumbnail-v1.jpg -y`
4. `open` でプレビュー → ユーザー承認 → `cp thumbnail-v1.jpg thumbnail.jpg`

## 品質チェック

Phase 1 生成後:
- [ ] `image_generation.gemini.style` に記載されたスタイルが維持されているか
- [ ] `composition_rules.environment` の制約を満たしているか
- [ ] `fixed_character` の外見が維持されているか（ある場合）
- [ ] キャラの顔が見えているか（`fixed_character.face` の指示通り）
- [ ] キャラサイズが `composition_rules.character_size` を満たしているか
- [ ] テキストが入っていないか

Phase 2 生成後:
- [ ] 背景が変わっていないか
- [ ] タイトルテキストが `composition_rules.text_lines` の制約内か
- [ ] `thumbnail_text.channel_name` が表示されているか

## プロンプト保存

プロンプトは `20-documentation/thumbnail-prompts.md` に保存:

```markdown
# Thumbnail Prompts - <コレクション名>

*プロバイダー: {image_generation.provider}*
*スタイル: {image_generation.gemini.style}*
*モデル: {image_generation.gemini.model}*
*参照画像: <使用した参照画像>*

## Video Background Prompt (main.png)

\```
<生成に使用したプロンプト>
\```

## Text Overlay Prompt (thumbnail.jpg)

\```
<テキストオーバーレイ指示>
\```
```

## ファイル命名ルール（上書き禁止）

| ファイル | 用途 |
|---------|------|
| `main.png` | 動画背景（テキストなし） |
| `main-v{N}.jpg` | 背景候補 |
| `thumbnail-v{N}.jpg` | テキスト付き候補 |
| `thumbnail.jpg` | **最終承認後にベスト版をコピー** |

### クリーンアップ（承認後に必ず実行）

```bash
rm -f 10-assets/main-v*.jpg 10-assets/thumbnail-v*.jpg
```

### `workflow-state.json` 更新

画像確認・承認後、`thumbnail.approved = true` を更新する。

## Next Step

サムネイル確定後:
→ `/suno <theme>` で音楽プロンプト生成
