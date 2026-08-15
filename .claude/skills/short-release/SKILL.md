---
name: short-release
purpose: 作る
description: "Use when release 型（楽曲リリース）チャンネルで JP+EN の 9:16 クリップを生成するとき。「リリースショート」「サビ抽出」で発動。collection 型は /short"
---

## 前後工程

- `前工程`: `なし`
- `後工程`: `/short-thumbnail`
- `委譲先`: `なし`

## Overview

`config.youtube.content_model.type == "release"` のチャンネル向けに、本編リリース動画
（`${motif}-{jp,en}.mp4`）から JP・EN の 2 言語ぶん 9:16 縦型ショートを生成する。
楽曲のサビ部分を抜き出して縦型クロップ + スケール変換する。

現行の `yt-upload-shorts` は collection ディレクトリ向けの uploader であり、release ディレクトリや
言語指定つきアップロードには未対応。release 型ショートのアップロード自動化が必要な場合は、
別実装タスクとして扱う。

## 完了条件

- `<release-path>/video/short-jp.mp4` / `short-en.mp4`（`shorts.release.languages` で絞った場合は対象言語分）が生成されている
- Step 5 のプレビューで生成物を確認済み（アップロードと workflow-state への記録はスコープ外・未実装）

## 設定読み込みゲート

以下を deep-merge した値を設定として使う。

1. `.claude/skills/short-release/config.default.yaml`
2. `config/skills/short-release.yaml`（存在する場合）

合成規則は `youtube_automation.configuration.skills.load_skill_config("short-release")` と同じで、チャンネル上書きが優先される。存在しない override は未設定として扱い、勝手に作成しない。

## 前提

- `config/channel/` がロード可能（`load_config()`）
- `config.shorts.enabled == true`（`config/channel/shorts.json`）
- `config.youtube.content_model.type == "release"`
- リリースディレクトリに `video/${motif}-jp.mp4` と `video/${motif}-en.mp4` が存在する（`motif` は release ディレクトリ名から先頭の `<番号>-` を除去したもの）

## Quick Reference

| コマンド | 説明 |
|---------|------|
| `bash .claude/skills/short-release/references/generate-shorts.sh <release-path>` | デフォルト位置で JP/EN 縦型変換 |
| `bash .claude/skills/short-release/references/generate-shorts.sh <release-path> -s 30 -t 40` | 開始秒・尺を指定 |

## Instructions

### Step 1: 前提チェック

```python
from youtube_automation.configuration import load_config
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

所要時間とログの扱いは後述「所要時間と完了報告」に従う。

出力: `<release-path>/video/short-{jp,en}.mp4`。中央クロップ（`crop=ih*9/16:ih`）→ 1080x1920 へスケール → `fps=30`。

### Step 5: プレビュー

```bash
open <release-path>/video/short-{jp,en}.mp4
```

この skill は生成物の確認までを扱う。release 型ショートのアップロード実行と、
workflow-state へのアップロード結果記録は未実装。

`workflow-state.json::post_upload.shorts` の実装済み schema は collection 型 `yt-upload-shorts` 向けの list 形式:

```json
"post_upload": {
  "shorts": [
    {
      "short_num": 1,
      "video_id": "xxx",
      "publish_at": "2026-03-12T08:00:00+09:00",
      "uploaded_at": "2026-03-11T09:12:00+09:00"
    }
  ]
}
```

上記は collection 型 `yt-upload-shorts` の実装済み schema。release 型の JP/EN 別 upload schema は
未実装のため、単一 object に言語別キーを持たせる形式は使わない。

## 設定

| 配置 | ファイル | 責務 |
|------|---------|------|
| チャンネル運用 | `config/channel/shorts.json` | enabled / `shorts.release.languages` / `shorts.release.start_sec` / `shorts.release.duration_sec` |
| skill 動作 | `.claude/skills/short-release/config.default.yaml` | クロップ / スケール / コーデック設定 |
| チャンネル上書き | `config/skills/short-release.yaml` | skill-config の差し替え |

## ショート動画仕様

| 項目 | 値 |
|------|-----|
| アスペクト比 | 9:16（1080x1920） |
| 推奨長 | 30-45 秒（`shorts.release.duration_sec`） |
| 最大長 | 60 秒 |
| フレームレート | 30fps 必須 |
| 構成 | JP / EN それぞれ 1 本（`shorts.release.languages` で生成対象を選択可） |

## Gotchas

- **motif 名の取り出し**: `motif=$(basename <release-path> | sed 's/^[0-9]*-//')`。番号プレフィックスを必ず除去すること
- **JP/EN 片方欠落**: `${motif}-jp.mp4` か `${motif}-en.mp4` の片方しか無い場合は skip。両方欠落で early-exit
- **fps=30 必須**: 元動画が低 fps の場合は `fps=30` フィルタなしで生成すると YouTube がショート認識しない（`generate-shorts.sh` が常時付与）
- **サビ位置のテスト**: 実機で `open <release-path>/video/short-jp.mp4` 確認前にアップロードしないこと。冒頭が無音だと最後まで再生されない

## 所要時間と完了報告

`generate-shorts.sh` は JP / EN 各 1 本の縦型変換を ffmpeg で走らせるため **1〜2 分**。

ログを `/tmp/short-release-$(date +%s).log` へ redirect し、完了後は末尾から `short-jp.mp4` / `short-en.mp4` のパスを報告する。失敗時は ffmpeg のエラー行を抜き出す。

## Next Step

- collection 型ショートも作る別チャンネルでは `/short` を使う
- 全本数完了後の進捗確認: `/wf-status`
