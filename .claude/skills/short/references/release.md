# release 型の手順

## 前提

- `<release-path>/video/<motif>-jp.mp4` / `<motif>-en.mp4` のうち `cfg.shorts.release.languages` の対象が存在する
- `motif` は release ディレクトリ名から先頭の `<番号>-` を除いた値

現行 uploader は collection ディレクトリ向けであるため、release 型のアップロードと workflow-state 更新は行わない。

## サビ位置を決める

`cfg.shorts.release.start_sec` / `duration_sec` を初期値として提示し、ユーザーに区間を確認する。音源確認が必要なら次で再生する。

```bash
ffplay <release-path>/video/<motif>-jp.mp4 -ss 30
```

## JP / EN クリップを生成する

`load_skill_config("short")["release"]` の値を env に渡す。

```bash
export SHORT_CRF=18
export SHORT_PRESET=slow
export SHORT_AUDIO_BITRATE=192k
bash .claude/skills/short/references/generate-shorts.sh <release-path> -s 30 -t 40
```

スクリプトは対象言語の本編を中央クロップし、1080x1920・30fps の H.264/AAC として `video/short-<lang>.mp4` へ出力する。対象動画が片方だけなら存在する言語だけ生成し、両方無ければ非 0 で停止する。

## プレビューする

```bash
open <release-path>/video/short-{jp,en}.mp4
```

冒頭無音、サビ区間、クロップを確認する。release 型の投稿 API と言語別 upload schema は未実装なので、collection 用 `yt-upload-shorts` や `workflow-state.json::post_upload.shorts` を流用しない。
