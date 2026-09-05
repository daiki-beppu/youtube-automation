---
name: short
purpose: 作る
description: "Use when collection 型（BGM テイスター）または release 型（楽曲リリース）のチャンネルでショートを生成するとき。「ショート作って」「shorts」「BGM 切り抜き」「リリースショート」「サビ抽出」「ショートサムネ」で発動。content_model.type から手順を自動判定し、--thumbnail で 9:16 素材を生成する"
---

## 前後工程

- `前工程`: `/setup`
- `後工程`: `なし`
- `委譲先`: `なし`

## 成果物

- `書き込む`: collection 型は `collections/<id>/01-master/shorts/short-*.mp4` と `workflow-state.json`、release 型は `releases/<id>/video/short-{jp,en}.mp4`、`--thumbnail` は `10-assets/short.png` と `short-loop.mp4`
- `読み込む`: `config/channel/youtube.json`, `config/channel/shorts.json` と対象 collection / release の映像・音声素材

## Overview

チャンネル設定の `config.youtube.content_model.type` を入口で一度だけ読み、利用者に型やフラグを指定させず手順を自動分岐する。

| `content_model.type` | 実行内容 | 手順 |
|---|---|---|
| `collection` | CC 公開後にショートを既定 3 本前後生成し、全 supported language にローカライズして投稿 | [references/collection.md](references/collection.md) |
| `release` | 本編のサビを抽出し、JP+EN の 9:16 クリップを生成 | [references/release.md](references/release.md) |

`collection` / `release` 以外は設定エラーとして停止する。これは config から自動判定できる分岐であり、手動 mode や選択フラグは設けない。

## モード判定

`$ARGUMENTS` から `--thumbnail` の個数を最初に数える。

- 2 個以上なら重複指定として停止し、1 つだけ指定するよう促す
- 1 個なら対応する reference を読み、その一段だけを実行する
- 0 個なら `content_model.type` で collection / release の通常手順を自動分岐する

| mode | 読む reference |
|---|---|
| `--thumbnail` | `references/thumbnail.md` |

`--thumbnail` は型を選ぶフラグではない。release 型では対象外として停止し、collection 型の素材生成だけを明示実行する。

## 完了条件

- collection 型: 生成した全番号をプレビューし、番号指定の実投稿結果と `workflow-state.json::post_upload.shorts` の `short_num`・`video_id` が一致する。blocked・失敗を含む場合は未完了として番号別に報告する（[投稿手順](references/collection.md#プレビュー投稿state-を確認する)）
- release 型: `shorts.release.languages` の対象言語ぶん `video/short-<lang>.mp4` が生成され、プレビュー確認済み。アップロードは現時点ではスコープ外
- `--thumbnail`: `10-assets/short.png` が生成・承認され、ループ動画化する場合は `short-loop.mp4` も確認済み

## Subagent Contract

- **入力**: 対象パス、映像ソース、確定済みハイライト / サビ区間、必要な場合はクロップ位置
- **成果物**: collection 型は `01-master/shorts/short-*.mp4`、release 型は `video/short-{jp,en}.mp4`
- **委譲しない処理**: 区間・クロップ・プレビュー・投稿の承認。state を更新する実投稿 CLI は承認後にメインが実行する

subagent は `workflow-state.json` を更新せず、ユーザー確認を行わない。完了報告は `status: success | failure`、成果物の絶対パス一覧、エラーを返す。

## 設定読み込みゲート

1. `load_config()` で `config/channel/shorts.json` と `config.youtube.content_model.type` を読む
2. `.claude/skills/short/config.default.yaml` と、存在する場合だけ `config/skills/short.yaml` を `load_skill_config("short")` で deep-merge する。override は勝手に作成しない
3. 判定した型と同名の `collection` / `release` 節だけを生成パラメータとして使う

旧 `short-release` の skill-config owner や override は読まない。チャンネル固有値は必ず上記 config 経由で解決する。

```python
from youtube_automation.configuration import load_config
from youtube_automation.configuration.skills import load_skill_config

cfg = load_config()
assert cfg.shorts.enabled, "config/channel/shorts.json で shorts.enabled=true にしてください"
content_type = cfg.youtube.content_model.type
assert content_type in {"collection", "release"}, f"未対応の content_model.type: {content_type}"
generation = load_skill_config("short")[content_type]
```

## 前提

- `config/channel/` がロード可能
- `config.shorts.enabled == true`
- 型別 reference に記載した対象素材が存在する

いずれか欠ける場合は早期に止めて該当 skill / config 更新を案内する（`/setup --import` / `/setup` / `/publish --upload`）。

## Quick Reference

| コマンド | 説明 |
|---|---|
| `bash .claude/skills/short/references/generate-shorts.sh <target-path>` | config の型に従いショートを生成 |
| `bash .claude/skills/short/references/generate-shorts.sh <release-path> -s 30 -t 40` | release 型でサビ位置・尺を指定 |
| `bash .claude/skills/short/references/test-crop-positions.sh <master> 30` | collection の loop-mp4 素材でクロップ候補を確認 |
| `uv run yt-upload-shorts <collection-path> --short-num <short-num> --plan` | 生成物の番号を指定して投稿内容を API なしで確認 |
| `uv run yt-upload-shorts <collection-path> --short-num <short-num>` | 指定番号のショートを 1 本投稿し、結果の action を確認 |
| `uv run yt-shorts-bulk-update-loc --dry-run` | 投稿済み collection Shorts の localization 更新を確認 |
| `uv run yt-generate-image --aspect-ratio "9:16" --prompt "<text>" --output <collection>/10-assets/short.png -y` | `--thumbnail` の 9:16 画像生成 |
| `uv run yt-generate-shorts-loop <collection-path> -y` | `short.png` の 9:16 ループ動画化 |

## Instructions

### Step 1: 型を判定する

設定読み込みゲートを実行し、`content_type` を一度だけ確定する。型をユーザーへ質問せず、フラグでも上書きしない。

`--thumbnail` が指定された場合は `content_type == "collection"` を確認し、[references/thumbnail.md](references/thumbnail.md) だけを実行して終了する。

### Step 2: 型別手順を実行する

- `collection`: [references/collection.md](references/collection.md) を読み、素材確認から投稿・state 検証まで実行する
- `release`: [references/release.md](references/release.md) を読み、素材確認から JP/EN 生成物のプレビューまで実行する

両手順とも生成コマンドは同じ `references/generate-shorts.sh` を使う。このスクリプトも `load_config()` の `content_model.type` を読み、別 skill や手動型フラグへ分岐を委ねない。

## 想定 API call 数

| API | call 数 / 実行 | 変動要因 |
|---|---|---|
| videos.insert（1,600 units / 本） | collection 型の投稿本数 | `shorts.collection.default_count`。release 型は 0 |
| thumbnails.set（50 units / 本） | collection 型の投稿本数 | release 型は 0 |
| videos.update（50 units） | `yt-shorts-bulk-update-loc` の対象 Shorts 数 | `--dry-run` は 0 |
| Vertex AI Gemini | `--thumbnail` の `short.png` 生成で 1 call | 再生成回数 |
| Vertex AI Veo 3.1 | `--thumbnail` のループ動画化で 1 call | ループ不要なら 0 |

- 上限 / 承認: collection 型は `--plan` と `--short-num` で小出しに確認できる。`--thumbnail` の画像・動画生成は各 1 call ごとに承認する。release 型はローカル ffmpeg 生成だけで、投稿 API は呼ばない。

## 設定

| 配置 | 責務 |
|---|---|
| `config/channel/shorts.json` | enabled、公開時刻、collection の本数・間隔、release の言語・開始秒・尺 |
| `.claude/skills/short/config.default.yaml` | `collection` / `release` の生成側既定値 |
| `config/skills/short.yaml` | 生成設定のチャンネル上書き |
| `config/localizations.json` | collection 型の言語別タイトル・説明テンプレート |

## 所要時間と完了報告

ffmpeg 生成は通常 1〜3 分。`/tmp/short-$(date +%s).log` へ redirect し、終了後に生成物の絶対パスを報告する。失敗時は ffmpeg のエラー行と未生成の対象を報告する。

## Next Step

- collection 型の投稿済み localizations 更新: `uv run yt-shorts-bulk-update-loc --dry-run`
- 全本数完了後の進捗確認: `/wf-status`
