---
name: publish
purpose: 公開する
description: "Use when 完成した動画を公開工程へ進めるとき。--upload は collection 型または release 型の YouTube アップロードを、既存の承認ゲートを保って実行する。「アップロード」「公開する」「楽曲リリースを公開」で発動。動画生成は /videoup、概要欄生成は /video-description"
---

## 前後工程

- `前工程`: `/wf-new`, `/videoup`, `/video-description`, `/playlist`, `/thumbnail`
- `後工程`: `/post-publish`, `/community-post`, `/metadata-audit`, `/pinned-comment`, `/live-clean`
- `委譲先`: `/post-publish`

## 成果物

- `書き込む`: `collections/<id>/20-documentation/upload_tracking.json`, `collections/<id>/workflow-state.json`
- `読み込む`: `collections/<id>/01-master/*.mp4`, `collections/<id>/10-assets/thumbnail.jpg`, `collections/<id>/20-documentation/descriptions.md`, `config/channel/*.json`, `config/schedule_config.json`

## Overview

公開工程の統合エントリポイント。引数なしでは実行せず、排他的な mode を 1 つ指定する。

## モード判定

`$ARGUMENTS` から `--upload` の個数を最初に数える。

- 2 個以上なら排他違反として停止し、1 つだけ指定するよう促す
- 1 個なら対応する reference を読み、残りの引数を upload mode の引数として扱う
- 0 個なら利用可能な mode を表示して停止する

| mode | 読む reference |
|---|---|
| `--upload` | `references/upload.md` |

現在は `--upload` のみを受け付ける。未知 mode、mode なし、複数 mode は利用可能な mode を表示して停止する。

## 設定読み込みゲート

`youtube_automation.configuration.skills.load_skill_config("publish")` で次を deep-merge し、チャンネル上書きを優先する。upload mode は `config["upload"]` を使う。

1. `.claude/skills/publish/config.default.yaml`
2. `config/skills/publish.yaml`（存在する場合）

存在しない override は未設定として扱い、勝手に作成しない。

旧 `config/skills/video-upload.yaml` は `uv run yt-skills migrate-config` で `publish.yaml::upload` へ移行する。移行前も `load_skill_config("video-upload")` が upload 節の互換入口として機能する。

## Chain Contract

`references/publish-chain-manifest.json` を読み、upload step だけを実行する。実行前後に次を守る。

1. `references/publish-chain-state.py --collection-dir <path> --step upload` を実行する。
2. exit 0 は成果物記録済みのため skip、exit 10 は run、exit 20 は state 不正のため停止する。
3. prerequisite artifacts を検証し、`references/upload.md` の preflight と plan を完了する。
4. manifest の `approvalGate.configPath` を `load_config()` から解決する。値が未設定なら `approvalGate.skip` を使う。
5. resolved skip が `false` の場合、対象 collection、`content_model.type`、動画本数、plan が示す公開日時または公開範囲を提示し、「この先は YouTube への取り消し不能な外部アップロードを実行する」と明示する。選択肢を **「アップロードする」/「中止する」** の 2 つに限定し、承認されるまで upload CLI、tracking 更新、state 更新を行わない。
6. resolved skip が `true` の場合だけ upload 承認を省略する。これは既存の `workflow.wf_next.skip_upload_approval` による自動実行互換であり、初回 playlist 作成の承認や `/post-publish` 子チェーン固有の承認は省略しない。
7. CLI 成功後に output artifacts を実在確認する。`workflow-state.json::upload.video_id` が空なら完了扱いにしない。

## Instructions

`--upload` では `references/upload.md` を読み、`content_model.type` に応じて collection は `uv run yt-upload-collection`、release は `uv run yt-upload-auto` を使う。plan や status は read-only として先に実行できるが、実 upload は上記承認ゲートを通過してから行う。

`/post-publish` が構成済みなら upload 完了後にその chain へ委譲する。community-post、pinned-comment、metadata-audit の承認・履歴・再開契約をここへ複製しない。

## 想定 API call 数

| API | call 数 / 実行 | 変動要因 |
|---|---|---|
| videos.insert（1,600 units / 本） | collection 型 1 本、release 型は言語数分 | アップロード本数 |
| thumbnails.set（50 units / 本） | アップロード本数分 | — |
| search.list（100 units） | 約 2 | dedup 確認 |
| playlistItems.insert（50 units） | 割当プレイリスト数 | プレイリスト構成 |

- 上限 / 承認: plan は upload API を叩かず、実 upload は Chain Contract の承認ゲート通過後だけ行う。

## 完了条件

- upload CLI が正常終了している
- `20-documentation/upload_tracking.json` が存在する
- `workflow-state.json::upload.video_id` が非空文字列である
- collection 型では既存手順どおり `collections/live/` へ移動済み、release 型では対象全言語が処理済みである
