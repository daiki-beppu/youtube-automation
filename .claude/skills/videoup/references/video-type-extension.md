# 動画タイプの追加手順

`video_type` は動画の構成（`loop` / `static` / 将来の `multi_scene`）を表す。
Veo などの生成エンジン選択とは別の軸として扱う。

## 現行タイプ

- `loop`: `main.png/jpg` から `loop.mp4` を生成し、マスター動画の背景として反復する。
- `static`: `main.png/jpg` を直接マスター動画の背景として使う。生成 hook は持たない。

`video_type` 未設定時は後方互換のため `loop`。`videoup` で `loop.mp4` が無い場合は
従来どおり `static` にフォールバックする。

## 新規タイプを追加する

1. `src/youtube_automation/utils/video_type.py::VideoType` に値を追加する。
2. 生成が必要なら専用 generator を実装し、
   `src/youtube_automation/utils/veo_generator.py::register_video_generator` へ登録する。
   呼び出し側は `generate_video(video_type, ...)` で dispatch する。
3. `src/youtube_automation/scripts/` の CLI で `VideoTypeConfig.from_mapping()` を使い、
   選択タイプをログへ出す。タイプ固有の入出力名はその CLI に閉じ込める。
4. `.claude/skills/loop-video/config.default.yaml` と
   `.claude/skills/videoup/config.default.yaml`、必要な下流テンプレートへ既定値を追加する。
5. `.claude/skills/videoup/references/generate_videos.sh` の `VIDEO_TYPE` validation と
   background selection に分岐を追加する。ファイルの有無だけでタイプを決めない。
6. enum/config validation、generator dispatch、CLI の観測可能ログ、`videoup` の背景選択を
   unit test で固定し、既存 `loop` / fallback の regression test も実行する。
7. `CHANGELOG.md` の `[Unreleased]` を更新する。

新規タイプの生成処理を既存 `generate_loop_video()` に条件分岐として足さず、専用 hook に分離する。
