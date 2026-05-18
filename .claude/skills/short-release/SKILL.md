---
name: short-release
description: Use when release 型チャンネル（話す系・楽曲リリース）でショート動画を生成・投稿したいとき。`${motif}-{jp,en}.mp4` から JP+EN 各 1 本ずつ 9:16 縦型クリップを生成・投稿。「リリースショート」「楽曲ショート」「JP/EN クリップショート」「サビ抽出」「short-release」など、release 型チャンネルのショート制作に関わる場面で必ず使用すること。BGM テイスター（collection 型）チャンネルは `/short` を使う
---

## Overview

`config.youtube.content_model.type == "release"` のチャンネル向けに、本編リリース動画
（`${motif}-{jp,en}.mp4`）から JP・EN の 2 言語ぶん 9:16 縦型ショートを生成・投稿する。
楽曲のサビ部分を抜き出して縦型クロップ + スケール変換し、`#Shorts` タグ付きで投稿する。

## 前提

- `config/channel/` がロード可能（`load_config()`）
- `config.shorts.enabled == true`（`config/channel/shorts.json`）
- `config.youtube.content_model.type == "release"`
- 本編動画が YouTube にアップ済みで `upload_tracking.json` に JP / EN それぞれの `video_url` が記録されている
- リリースディレクトリに `video/${motif}-jp.mp4` と `video/${motif}-en.mp4` が存在する（`motif` は release ディレクトリ名から先頭の `<番号>-` を除去したもの）

## Quick Reference

| コマンド | 説明 |
|---------|------|
| `uv run yt-upload-shorts <release-path>` | JP / EN 両方をまとめてアップロード |
| `uv run yt-upload-shorts <release-path> --lang jp` | JP のみアップロード |
| `uv run yt-upload-shorts <release-path> --dry-run` | メタデータプレビュー |
| `bash .claude/skills/short-release/references/generate-shorts.sh <release-path>` | デフォルト位置で JP/EN 縦型変換 |
| `bash .claude/skills/short-release/references/generate-shorts.sh <release-path> -s 30 -t 40` | 開始秒・尺を指定 |

## Instructions

### Step 1: 前提チェック

```python
from youtube_automation.utils.config import load_config
cfg = load_config()
assert cfg.shorts.enabled, "config/channel/shorts.json で shorts.enabled=true にしてください"
assert cfg.youtube.content_model.type == "release", "collection 型は /short を使ってください"
```

失敗時は対応 skill を案内して終了。

### Step 2: 素材確認

```bash
ls <release-path>/video/    # ${motif}-{jp,en}.mp4 が必要
```

JP / EN の片方しか無い場合は `cfg.shorts.release.languages` で投稿対象を絞れる。両方無ければ録音・編集前提のため早期終了。

### Step 3: サビ位置決定（AskUserQuestion）

`config.shorts.release.start_sec` / `duration_sec` を初期値として提示し、`AskUserQuestion` でサビ位置を確認:
- そのまま使う / 別の秒数を指定する
- 「楽曲ファイルを再生して指示する」場合は `ffplay <release-path>/video/${motif}-jp.mp4 -ss 30` で先頭 30s から再生

### Step 4: 縦型変換

```bash
bash .claude/skills/short-release/references/generate-shorts.sh <release-path> -s 30 -t 40
```

出力: `<release-path>/video/short-{jp,en}.mp4`。中央クロップ（`crop=ih*9/16:ih`）→ 1080x1920 へスケール → `fps=30`。

### Step 5: プレビュー → アップロード

```bash
open <release-path>/video/short-{jp,en}.mp4
uv run yt-upload-shorts <release-path> --dry-run    # メタデータ確認
uv run yt-upload-shorts <release-path>              # 実投稿
```

`ShortUploader` が自動で行うこと:
- 本編 JP / EN それぞれの `publish_at` 基準で `cfg.shorts.publish_time` 翌日公開時刻を計算
- 各言語のメタデータ生成（タイトル / 説明欄 / `#Shorts` タグ）
- `workflow-state.json::post_upload.short.{jp,en}` に記録

### Step 6: workflow-state.json 更新

```json
"post_upload": {
  "short": {
    "jp": { "generated": true, "uploaded": true, "video_id": "xxx", "publish_at": "..." },
    "en": { "generated": true, "uploaded": true, "video_id": "yyy", "publish_at": "..." }
  }
}
```

## 設定

| 配置 | ファイル | 責務 |
|------|---------|------|
| チャンネル運用 | `config/channel/shorts.json` | enabled / publish_time / `shorts.release.languages` / `shorts.release.start_sec` / `shorts.release.duration_sec` / 投稿間隔 |
| skill 動作 | `.claude/skills/short-release/config.default.yaml` | クロップ / スケール / コーデック設定 |
| チャンネル上書き | `config/skills/short-release.yaml` | skill-config の差し替え |

## ショート動画仕様

| 項目 | 値 |
|------|-----|
| アスペクト比 | 9:16（1080x1920） |
| 推奨長 | 30-45 秒（`shorts.release.duration_sec`） |
| 最大長 | 60 秒 |
| フレームレート | 30fps 必須 |
| 構成 | JP / EN それぞれ 1 本（`shorts.release.languages` で選択可） |

## Gotchas

- **motif 名の取り出し**: `motif=$(basename <release-path> | sed 's/^[0-9]*-//')`。番号プレフィックスを必ず除去すること
- **JP/EN 片方欠落**: `${motif}-jp.mp4` か `${motif}-en.mp4` の片方しか無い場合は skip。両方欠落で early-exit
- **fps=30 必須**: 元動画が低 fps の場合は `fps=30` フィルタなしで生成すると YouTube がショート認識しない（`generate-shorts.sh` が常時付与）
- **サビ位置のテスト**: 実機で `open <release-path>/video/short-jp.mp4` 確認前にアップロードしないこと。冒頭が無音だと最後まで再生されない

## Next Step

- collection 型ショートも作る別チャンネルでは `/short` を使う
- 全本数完了後の進捗確認: `/wf-status`
