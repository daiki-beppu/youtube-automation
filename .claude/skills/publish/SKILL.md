---
name: publish
purpose: 公開する
description: "Use when 完成した動画を公開工程へ進めるとき。--playlist はプレイリストの作成・割り当て・確認、--upload は YouTube アップロード、--community はコミュニティ投稿テキスト生成から Studio 起動までを実行する。「プレイリスト作って」「初投稿」「初回投稿」「初回公開前にプレイリスト初期化」「コミュニティ投稿」「投稿準備」「アップロード」「公開する」で発動。動画生成は /video の generate mode、概要欄生成は /video-description、JSON バッチ生成は /community-draft"
---

## 前後工程

- `前工程`: `/wf-new`, `/video --generate`, `/video-description`, `/thumbnail`
- `後工程`: `/post-publish`, `/metadata-audit`, `/pinned-comment`, `/live-clean`
- `委譲先`: `/post-publish`

## 成果物

- `書き込む`: `config/channel/playlists.json`, `collections/<id>/20-documentation/upload_tracking.json`, `collections/<id>/workflow-state.json`
- `読み込む`: `config/channel/playlists.json`, `config/channel/content.json`, `auth/token.json`, `collections/<id>/01-master/*.mp4`, `collections/<id>/10-assets/thumbnail.jpg`, `collections/<id>/20-documentation/descriptions.md`, `config/channel/*.json`, `config/schedule_config.json`

## Overview

公開工程の統合エントリポイント。引数なしでは playlist → upload → community の chain を状態判定付きで進め、mode 指定時はその一段だけを実行する。

## モード判定

`$ARGUMENTS` から `--playlist` / `--upload` / `--community` の個数を最初に数える。

- 2 個以上なら排他違反として停止し、1 つだけ指定するよう促す
- 1 個なら対応する reference を読み、その一段だけを実行する。残りの引数はその mode の引数として扱う
- 0 個なら chain manifest に従い playlist → upload → community の順で状態判定して進める

| mode | 読む reference |
|---|---|
| `--playlist` | `references/playlist.md` |
| `--upload` | `references/upload.md` |
| `--community` | `references/community.md` |

未知 mode や複数 mode は利用可能な mode を表示して停止する。

## 設定読み込みゲート

`youtube_automation.configuration.skills.load_skill_config("publish")` で次を deep-merge し、チャンネル上書きを優先する。upload mode は `config["upload"]` を使う。

1. `.claude/skills/publish/config.default.yaml`
2. `config/skills/publish.yaml`（存在する場合）

存在しない override は未設定として扱い、勝手に作成しない。

旧 `config/skills/video-upload.yaml` と `config/skills/community-post.yaml` は `uv run yt-skills migrate-config` でそれぞれ `publish.yaml::upload` と `publish.yaml::community` へ移行する。移行前も `load_skill_config("video-upload")` と `load_skill_config("community-post")` が各節の互換入口として機能する。

## Chain Contract

`references/publish-chain-manifest.json` を読み、playlist step → upload step → community step の順に実行する。mode 指定時は対応 step だけを実行する。実行前後に次を守る。

1. `references/publish-chain-state.py --channel-dir <channel-root> [--collection-dir <path>] --step <playlist|upload|community>` を実行する。`--collection-dir` は upload/community の collection mode とフラグなし chain では必須だが、playlist と community の URL mode では不要。
2. exit 0 は成果物記録済みのため skip、exit 10 は run、exit 20 は state 不正のため停止する。
3. prerequisite artifacts を検証し、playlist step は `references/playlist.md`、upload step は `references/upload.md`、community step は `references/community.md` の前提を満たす。
4. manifest の `approvalGate.configPath` を `load_config()` から解決する。値が未設定なら `approvalGate.skip` を使う。
5. playlist step の gate は常に `skip=false`。status と dry-run を先に実行し、作成されるプレイリスト名と割り当て件数を提示して、明示承認されるまで実反映を行わない。upload step の resolved skip が `false` の場合、対象 collection、`content_model.type`、動画本数、plan が示す公開日時または公開範囲を提示し、「この先は YouTube への取り消し不能な外部アップロードを実行する」と明示する。選択肢を **「アップロードする」/「中止する」** の 2 つに限定し、承認されるまで upload CLI、tracking 更新、state 更新を行わない。
6. community step は manifest の `workflow.post-publish.skip_approvals.community-post` を正規 config path とし、`config/channel/workflow.json::post_publish.skip_approvals.community_post` から解決する。旧 `workflow.json::post_publish.approval_gates.community_post` が有効なら逆向き alias により resolved skip は `false` になる。同一 step への新旧同時指定は拒否し、resolved skip が `false` の場合は対象 collection/動画と Studio 投稿準備 1 件を提示して、承認されるまで community mode を実行しない。
7. resolved skip が `true` の場合だけ upload/community の各承認を省略する。upload は既存の `workflow.wf_next.skip_upload_approval`、community は既存 post-publish 設定の互換であり、初回 playlist 作成の承認や `/post-publish` の他 step 固有の承認は省略しない。
8. 各 step 成功後に output artifacts を実在確認する。`workflow-state.json::upload.video_id` が空なら upload/community を完了扱いにしない。

## Instructions

`--playlist` では `references/playlist.md` を読み、状態確認・初期化・割り当て・clean の指定操作を行う。書き込み操作は必ず dry-run → 確認 → 本番の順にする。

`--upload` では `references/upload.md` を読み、`content_model.type` に応じて collection は `uv run yt-upload-collection`、release は `uv run yt-upload-auto` を使う。plan や status は read-only として先に実行できるが、実 upload は上記承認ゲートを通過してから行う。

`--community` では `references/community.md` を読み、固定テンプレを保存・クリップボードへコピーして Studio を開く。動画添付と投稿はユーザーが Studio 上で手動実行する。`--batch` は後続 issue のため、現段では `/community-draft` を案内する。

`/post-publish` が構成済みなら upload 完了後にその chain へ委譲する。community-post、pinned-comment、metadata-audit の承認・履歴・再開契約をここへ複製しない。

## 想定 API call 数

| API | call 数 / 実行 | 変動要因 |
|---|---|---|
| videos.insert（1,600 units / 本） | collection 型 1 本、release 型は言語数分 | アップロード本数 |
| thumbnails.set（50 units / 本） | アップロード本数分 | — |
| search.list（100 units） | 約 2 | dedup 確認 |
| playlistItems.list（1 unit） | Σ ceil(各プレイリスト項目数 / 50) | プレイリスト数・項目数 |
| playlists.insert（50 units） | 新規作成プレイリスト数 | 未作成エントリ数 |
| playlistItems.insert（50 units） | 割当動画本数 | プレイリスト構成 |
| playlistItems.delete（50 units） | 削除エントリ数 | 削除済み / 非公開動画数 |

- 上限 / 承認: plan は upload API を叩かず、実 upload は Chain Contract の承認ゲート通過後だけ行う。

## 完了条件

- playlist step は指定操作が exit 0 で完了し、初期化時は全 `playlist_id` が記録済みである
- upload CLI が正常終了している
- `20-documentation/upload_tracking.json` が存在する
- `workflow-state.json::upload.video_id` が非空文字列である
- collection 型では既存手順どおり `collections/live/` へ移動済み、release 型では対象全言語が処理済みである
