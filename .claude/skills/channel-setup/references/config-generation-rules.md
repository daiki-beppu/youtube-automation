# config/channel/*.json 生成ルール

`/channel-setup` と `/channel-import` から共通参照するルール集。
テンプレートは同ディレクトリの `config-template.json`。

## TTP（徹底的にパクる）路線時の優先順位

`docs/channel/channel-direction.md` で「TTP 完全コピー路線」が選ばれている場合、各フィールド生成ルール（後述）は **競合スナップショットの転写を最優先** し、独自設計はあとから差分として乗せる。

1. **`/channel-setup` Step 2.1 で取得した競合の `channels().list(part='snippet,brandingSettings,localizations')` レスポンス**を Claude のコンテキストに必ず載せる
2. 競合の構造（章立て・段落順・箇条書きの数・絵文字の有無）をそのままコピーし、`competitor → my-channel` の固有名詞置換だけを行う
3. `brandingSettings.channel.keywords` は数・順序・スペース入りクォート形式（`"chill beats"` 等）まで踏襲する
4. `localizations` で多言語化されている言語セットを `config/localizations.json::supported_languages` の決定に反映する（独自に絞る場合は理由を明文化）
5. TTP self-check（SKILL.md Step 2.3）に通してから提案する

「独自路線」「ハイブリッド路線」を選んでいる場合は競合スナップショットを必ず参照しつつも、転写率と差別化の比率を方向性ドキュメントに合わせる。

## 必須セクション

以下は **すべて `config/channel/*.json` に含める**:

- `channel` — name, short, core_message, channel_id, youtube_handle, url
- `content_model` — collection / release など
- `music_engine` — `"suno"` または `"lyria"`（チャンネルのデフォルト音楽エンジン）
- `genre` — primary, style, context
- `youtube` — デフォルトのアップロード設定。アップロード metadata に使う `youtube.category_id` / `youtube.privacy_status` もここで決める
- `tags` — base, themes
- `descriptions` — opening, sub_opening, perfect_for, hashtags
- `analytics` — 計測対象の設定
- `title` — template, theme_activities
- `workflow` — フェーズ定義

## ルート設定ファイル

- `config/localizations.json` — `default_language` + `supported_languages`。scene_phrases / 概要欄多言語版の対象言語の単一ソース。`supported_languages` は多言語チャンネルなら高 CPM 言語（`ja` / `en` / `de`）を推奨、低 CPM 言語（`ko` / `es` / `pt` / `zh-CN` など）は原則追加しない（issue #272）。en-only 運用も可（preflight は `supported_languages` を尊重し、ハードコード必須言語は無い）。**TTP 路線時**は競合の `localizations` エントリ言語を最優先で踏襲する。競合が多言語化していないチャンネル（en 一択など）を TTP 対象にしている場合、自分も同様に絞る選択肢を必ずユーザーに提示する

## 各フィールドの生成ルール

### `tags.base`
ジャンルに適した YouTube 検索タグを **10 個程度**。競合の頻出タグを参考に。

**TTP 路線**: 競合 `brandingSettings.channel.keywords` の語彙・件数・順序・クォート形式（`"my channel"`）をそのまま転写し、固有名詞だけを自チャンネル名に置換する。`keywords` 全体の文字数上限は 500 文字（`yt-channel-settings` の事前バリデーションも 500 文字基準 #563）なので、転写時に超過しないか必ず確認する。

### `tags.themes`
**6-10 テーマ** のタグ群。各テーマ **3 語程度**。

### `descriptions`

| フィールド | 内容 |
|---|---|
| `opening` | `{style} {primary} music inspired by ...` の形式で開始 |
| `sub_opening` | opening を補足する 1-2 文 |
| `perfect_for` | **4 項目**（例: Study & Focus, Relaxation, Creative Work, Sleep） |
| `hashtags` | **5 個** 程度 |

**TTP 路線**: チャンネル概要欄（`snippet.description` / `brandingSettings.channel.description`）の章立て・段落構造を `descriptions.opening` + `descriptions.sub_opening` + `descriptions.perfect_for` に転写する。welcome 行・絵文字・箇条書きセクションの並び順を変えないこと。「TTP できているか」は SKILL.md Step 2.3 の self-check で必ず検証する。

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
| suno-lyric | `config/skills/suno-lyric.yaml` |
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

ボーカル歌詞本文の persona / quote / lyric structure は `/suno-lyric` 側の `config/skills/suno-lyric.yaml` で任意上書き。

**Thumbnail**:

| キー | 転記元 |
|---|---|
| `image_generation.gemini.brand_background` | 「ビジュアルアイデンティティ」の背景色 |
| `image_generation.gemini.reference_images.default` | TTP 対象の代表サムネ（`data/thumbnail_compare/benchmark/<channel>-<vid>.jpg`、`/benchmark` で download される） |
| `image_generation.gemini.composition_rules.*` | 「ビジュアルアイデンティティ」「サムネイル方針」 |
| `image_generation.gemini.diff_prompt_template` | コレクション側 `prompts/<theme>.md` への差分指示テンプレ |

`reference_images.default` の TTP サムネは `/benchmark` skill（CLI は `yt-benchmark-collect`）が
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
