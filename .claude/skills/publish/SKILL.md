---
name: publish
purpose: 公開する
description: "Use when 完成した動画を公開工程へ進めるとき。--playlist はプレイリスト管理、--upload は YouTube アップロード、--community はコミュニティ投稿準備、--batch は JSON バッチ生成、--pinned はオーナー固定コメント投稿、--clean は公開済みメディアや tmp 残骸の削除を実行する。「プレイリスト作って」「初投稿」「初回投稿」「初回公開前にプレイリスト初期化」「コミュニティ投稿」「投稿バッチ」「投稿準備」「固定コメント」「ピンコメント」「容量」「クリーンアップ」「live 整理」「でかいファイル」「tmp 掃除」「残骸」「アップロード」「公開する」で発動。動画生成は /video、概要欄生成も /video"
---

## 前後工程

- `前工程`: `/wf-new`, `/video --generate`, `/video --describe`, `/thumbnail`
- `後工程`: `/audit --metadata`
- `委譲先`: `なし`

## 成果物

- `書き込む`: `config/channel/playlists.json`, `collections/<id>/20-documentation/upload_tracking.json`, `collections/<id>/20-documentation/community-post.txt`, `collections/<id>/workflow-state.json`, `pinned_comment_history.json`
- `読み込む`: `config/channel/playlists.json`, `config/channel/content.json`, `auth/token.json`, `collections/<id>/01-master/*.mp4`, `collections/<id>/10-assets/thumbnail.jpg`, 検証済み `collections/<id>/20-documentation/descriptions.json`, `config/channel/*.json`, `config/schedule_config.json`

## Overview

公開工程の統合エントリポイント。引数なしでは playlist → upload → community → pinned の chain を状態判定付きで進め、mode 指定時はその一段だけを実行する。

## モード判定

`$ARGUMENTS` から `--playlist` / `--upload` / `--community` / `--pinned` / `--clean` の個数を最初に数える。

- 2 個以上なら排他違反として停止し、1 つだけ指定するよう促す
- 1 個なら対応する reference を読み、その一段だけを実行する。残りの引数はその mode の引数として扱う
- 0 個なら chain manifest に従い playlist → upload → community → pinned の順で状態判定して進める

| mode | 読む reference |
|---|---|
| `--playlist` | `references/playlist.md` |
| `--upload` | `references/upload.md` |
| `--community` | `references/community.md` |
| `--pinned` | `references/pinned.md` |
| `--clean` | `references/clean.md` |

未知 mode や複数 mode は利用可能な mode を表示して停止する。

## 修飾フラグ

| modifier | 効果 |
|---|---|
| `--batch` | `--community` の config テンプレートから投稿バッチ JSON を生成する |

`--batch` は明示した `--community` と組み合わせた場合だけ有効。`--playlist` / `--upload` / `--pinned` / `--clean` との併用、または mode なしの `--batch` はエラーとして停止し、無視や chain 実行への fallback をしない。

## 設定読み込みゲート

`youtube_automation.configuration.skills.load_skill_config("publish")` で次を deep-merge し、チャンネル上書きを優先する。upload mode は `config["upload"]`、clean mode は `config["clean"]` を使う。

1. `.claude/skills/publish/config.default.yaml`
2. `config/skills/publish.yaml`（存在する場合）

存在しない override は未設定として扱い、勝手に作成しない。

旧 `config/skills/video-upload.yaml`、`config/skills/community-post.yaml`、`config/skills/live-clean.yaml` は `uv run yt-skills migrate-config` でそれぞれ `publish.yaml::upload`、`publish.yaml::community`、`publish.yaml::clean` へ移行する。移行前も `load_skill_config("video-upload")`、`load_skill_config("community-post")`、`load_skill_config("live-clean")` が各節の互換入口として機能する。

## Chain Contract

`references/publish-chain-manifest.json` を読み、playlist step → upload step → community step → pinned step の順に実行する。mode 指定時は対応 step だけを実行する。実行前後に次を守る。

1. `references/publish-chain-state.py --channel-dir <channel-root> [--collection-dir <path>] --step <playlist|upload|community|pinned>` を実行する。`--collection-dir` は upload/community/pinned の collection mode とフラグなし chain では必須だが、playlist と community/pinned の video ID 直接指定では不要。
2. exit 0 は成果物記録済みのため skip、exit 10 は run、exit 20 は state 不正のため停止する。
3. prerequisite artifacts を検証し、playlist step は `references/playlist.md`、upload step は `references/upload.md`、community step は `references/community.md`、pinned step は `references/pinned.md` の前提を満たす。
4. manifest の `approvalGate.configPath` を `load_config()` から解決する。値が未設定なら `approvalGate.skip` を使う。
   legacy `approvalGate.enabled` を読む場合は `skip = not enabled` とし、同一 gate への `skip` と `enabled` の同時指定はエラーにする。
5. playlist step の gate は常に `skip=false`。status と dry-run を先に実行し、作成されるプレイリスト名と割り当て件数を提示して、明示承認されるまで実反映を行わない。upload step の resolved skip が `false` の場合、対象 collection、`content_model.type`、動画本数、plan が示す公開日時または公開範囲を提示し、「この先は YouTube への取り消し不能な外部アップロードを実行する」と明示する。選択肢を **「アップロードする」/「中止する」** の 2 つに限定し、承認されるまで upload CLI、tracking 更新、state 更新を行わない。
6. community step は `load_config().workflow.post_publish.skip_approvals.community_post` から gate を解決する。旧 `approval_gates.community_post` が有効なら逆向き alias により resolved skip は `false` になる。同一 step への新旧同時指定は拒否し、resolved skip が `false` の場合は対象 collection/動画と Studio 投稿準備 1 件を提示して、承認されるまで community mode を実行しない。
7. pinned step は `load_config().workflow.post_publish.skip_approvals.pinned_comment` から gate を解決する。旧 `approval_gates.pinned_comment` が有効なら逆向き alias により resolved skip は `false` になる。同一 step への新旧同時指定は拒否し、resolved skip が `false` の場合は dry-run の対象 video ID・件数・代表テキストを提示して、「投稿する」/「キャンセル」の 2 択で承認されるまで apply を実行しない。
8. resolved skip が `true` の場合だけ upload/community/pinned の chain gate を省略する。pinned reference 自身の safety gate は、同じ video ID・件数への明示承認を引き継げない限り省略しない。
9. 各 step 成功後に output artifacts を実在確認する。`workflow-state.json::upload.video_id` が空なら upload/community/pinned を完了扱いにしない。
10. 途中失敗後の再発動でも必ず先頭 step から状態判定し、完了済み step は exit 0 の `skip` として副作用を再実行しない。

## Instructions

`--playlist` では `references/playlist.md` を読み、状態確認・初期化・割り当て・clean の指定操作を行う。書き込み操作は必ず dry-run → 確認 → 本番の順にする。

`--upload` では `references/upload.md` を読み、`content_model.type` に応じて collection は `uv run yt-upload-collection`、release は `uv run yt-upload-auto` を使う。plan や status は read-only として先に実行できるが、実 upload は上記承認ゲートを通過してから行う。

`--community` では `references/community.md` を読む。`--batch` なしは固定テンプレを保存・クリップボードへコピーして Studio を開き、動画添付と投稿はユーザーが手動実行する。`--community --batch` は同 reference の batch 分岐だけを実行し、単発投稿の保存・`pbcopy`・Studio 起動を行わない。

`--pinned` では `references/pinned.md` を読み、`yt-pinned-comment` の `--dry-run` で PASS 条件を確認してから、承認ゲート後に `--apply` で投稿する。ピン留め自体は Studio UI で手動実行する。

`--clean` では `references/clean.md` を読み、公開完了の 3 条件を同一 skill 内で検証する。対象と容量を dry-run 表示し、不可逆な物理削除への明示承認を得た場合だけ削除する。clean は任意操作のため chain manifest へ追加しない。

upload 完了後も同じ chain を続行し、community、pinned を順に状態判定する。metadata 監査はこの chain に含めず、必要な場合は `/audit --metadata` を独立して実行する。

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
- community step は `20-documentation/community-post.txt` が非空である
- pinned step は対象 video ID が設定済み history file の `posted` に記録済みであり、Studio UI の手動ピン留めを案内済みである
- collection 型では既存手順どおり `collections/live/` へ移動済み、release 型では対象全言語が処理済みである
