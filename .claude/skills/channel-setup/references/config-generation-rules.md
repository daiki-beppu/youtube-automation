# config/channel/*.json 生成ルール

`/channel-setup` と `/channel-import` から共通参照するルール集。
テンプレートは同ディレクトリの `config-template.json`。

## 必須セクション

以下は **すべて `config/channel/*.json` に含める**:

- `channel` — name, short, core_message, channel_id, youtube_handle, url
- `content_model` — collection / release など
- `localization` — `default_language` + `supported_languages`。`localizations.json.supported_languages` と一致させること（scene_phrases / 概要欄多言語版の対象言語、単一ソース宣言）。`supported_languages` は広告単価が高い 3 言語（`ja` / `en` / `de`）を必ず含め、低 CPM 言語（`ko` / `es` / `pt` / `zh-CN` など）は原則追加しない（issue #272）
- `music_engine` — `"suno"` または `"lyria"`（チャンネルのデフォルト音楽エンジン）
- `genre` — primary, style, context
- `youtube` — デフォルトのアップロード設定
- `tags` — base, themes
- `descriptions` — opening, sub_opening, perfect_for, hashtags
- `analytics` — 計測対象の設定
- `title` — template, theme_activities
- `workflow` — フェーズ定義

## 各フィールドの生成ルール

### `tags.base`
ジャンルに適した YouTube 検索タグを **10 個程度**。競合の頻出タグを参考に。

### `tags.themes`
**6-10 テーマ** のタグ群。各テーマ **3 語程度**。

### `descriptions`

| フィールド | 内容 |
|---|---|
| `opening` | `{style} {primary} music inspired by ...` の形式で開始 |
| `sub_opening` | opening を補足する 1-2 文 |
| `perfect_for` | **4 項目**（例: Study & Focus, Relaxation, Creative Work, Sleep） |
| `hashtags` | **5 個** 程度 |

### `title`

| フィールド | 内容 |
|---|---|
| `template` | `"{style} {theme} ... Music - {activity} BGM [{duration_display}]"` 形式 |
| `theme_scenes` | テーマ → アクティビティ + 英語シーンフレーズのマッピング（TTP 形式・推奨）。`{theme: {activities: "...", scene: "..."}}` 形式。`yt-populate-scene-phrases` の `--en` 自動補完に使われる |
| `theme_activities` | テーマ → アクティビティのマッピング（レガシー形式）。`theme_scenes` 未設定のときのみ参照される |

`theme_scenes` / `theme_activities` をどちらも空のまま `/channel-setup` を抜けると
下流 `yt-populate-scene-phrases` が手動 `--en` 指定を要求する。channel-direction.md で
テーマ群が確定しているなら空のまま終了しないこと（issue #567）。

### `audio`（`config/channel/audio.json`）

| フィールド | 内容 |
|---|---|
| `target_duration_min` | コレクションの最小目標尺（分）。channel-direction の「動画の長さ」決定を転記 |
| `target_duration_max` | 最大目標尺（分）。固定尺戦略のチャンネルでは `target_duration_min` と同値にする |
| `chapter_max` | チャプター数の上限（デフォルト 100） |

固定尺戦略を取るチャンネルでも、`target_duration_min` を空のまま `/channel-setup` を
抜けてはならない（issue #567）。

## skill-config で管理するセクション

以下は **`config/channel/*.json` には置かない**。各スキルの同梱デフォルト
（`.claude/skills/<skill>/config.default.yaml`）と、チャンネル固有の上書き
（`config/skills/<skill>.yaml`）を deep-merge した値で動く。

| スキル | 設定ファイル |
|---|---|
| thumbnail / Gemini 画像生成 | `config/skills/thumbnail.yaml` |
| suno | `config/skills/suno.yaml` |
| lyria | `config/skills/lyria.yaml` |
| collection-ideate | `config/skills/collection-ideate.yaml` |
| benchmark | `config/skills/benchmark.yaml` |
| video-description | `config/skills/video-description.yaml` |
| masterup（`audio.crossfade_duration` 等） | `config/skills/masterup.yaml` |
| loop-video（Veo 3.1 ループ生成） | `config/skills/loop-video.yaml` |

### channel-direction.md の決定を必ず転記する skill-config（issue #567）

下記は「チャンネル固有の上書きが必要」ではなく **方向性が決まっていれば必ず書く**
セクション。空のまま `/channel-setup` を抜けてはならない。雛形は
`references/config-template/skills/<skill>.yaml`。

**Suno**（`music_engine: suno` のチャンネル）:

| キー | channel-direction.md からの転記元 |
|---|---|
| `workspace_name` | Suno UI 上のワークスペース名（チャンネル短縮名 + ジャンルなど） |
| `genre_line` | 「ジャンル & スタイル」決定の直訳（Suno Styles 欄にそのまま入る） |
| `exclude_styles` | 「ジャンル & スタイル」で排除すると決めた要素（白音 / 雨音 / EDM 等） |

`lyrics_guidelines.style_reference` / `lyrics_generation.provider` は任意上書き。

**Thumbnail**:

| キー | 転記元 |
|---|---|
| `image_generation.gemini.brand_background` | 「ビジュアルアイデンティティ」の背景色 |
| `image_generation.gemini.reference_images.default` | TTP 対象の代表サムネ（`data/thumbnail_compare/benchmark/<channel>-<vid>.jpg`、`/benchmark` で download される） |
| `image_generation.gemini.composition_rules.*` | 「ビジュアルアイデンティティ」「サムネイル方針」 |
| `image_generation.gemini.diff_prompt_template` | コレクション側 `prompts/<theme>.md` への差分指示テンプレ |

`reference_images.default` の TTP サムネは `/benchmark`（`yt-benchmark`）が
`docs/benchmarks/*.md` 取得時に `data/thumbnail_compare/benchmark/` に自動 download する。
**手動 download はしない**（issue #567）。

## オプションセクション

方向性 or ヒアリング結果に応じて `config/channel/*.json` に追加:

| セクション | 条件 | 内容 |
|---|---|---|
| `playlists` | プレイリスト運用する場合 | プレイリスト名を提案（ID は空欄、作成後に埋める） |

## 参考

- `config-template.json` — 全フィールドの雛形
- `/channel-setup` — 方向性ドキュメントから config 完成までの手順
- `/channel-import` — 既存チャンネル取り込みの手順
