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
| `theme_activities` | テーマ → アクティビティのマッピング |

## skill-config で管理するセクション

以下は **`config/channel/*.json` には置かない**。チャンネル固有の上書きがある場合のみ `config/skills/<skill>.yaml` を作成する（ない場合は skill default を使用）:

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

**Suno の場合**: `config/skills/suno.yaml` で `workspace_name` / `genre_line` / `exclude_styles` / `lyrics_guidelines.style_reference` / `lyrics_generation.provider` を上書き可能。
英語歌詞のネイティブ感を寄せたいチャンネルでは、参考歌詞を `lyrics_guidelines.style_reference` に置き、歌詞本文のコピーではなく語り口・行長・韻の緩さだけを `/suno` に渡す。
`lyrics_generation.provider: codex` は Codex CLI 経由の初稿生成を使う場合のみ指定する。

## オプションセクション

方向性 or ヒアリング結果に応じて `config/channel/*.json` に追加:

| セクション | 条件 | 内容 |
|---|---|---|
| `playlists` | プレイリスト運用する場合 | プレイリスト名を提案（ID は空欄、作成後に埋める） |

## 参考

- `config-template.json` — 全フィールドの雛形
- `/channel-setup` — 方向性ドキュメントから config 完成までの手順
- `/channel-import` — 既存チャンネル取り込みの手順
