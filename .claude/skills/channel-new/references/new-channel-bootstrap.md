# New channel bootstrap

新規開設モードの Step 2〜4 で使う repository 初期化、setup gate、config 入力 schema、初期ファイル生成の詳細を定義する。実行順、承認点、コマンド、成功・停止条件は `../SKILL.md` を正とし、必ず本体の dispatch からこの reference を読んで実行する。

## Repository initialization details

- `.git` がない場合だけ、現在のディレクトリをローカル repository として初期化する。テンプレート repository は clone しない。
- remote は private repository として現在のディレクトリを source に作り、`origin` を設定する。
- `gh` が未認証、または remote を今は作成しない判断になった場合も、ローカル初期化後の config 生成は継続できる。remote 作成を保留した事実は作業メモへ残す。
- repository 初期化と remote 作成は副作用なので、本体の承認より前に実行しない。

## Setup gate details

必須 check ID と、config 未生成でも許容する代表的な stop contract は `../SKILL.md` に残す。次の config 生成で解消する分類詳細だけをこの reference で定義する。

Step 4 の config 生成で解消する次の fail / warn だけは許容する。

- `playlist_config`: `config/channel/playlists.json` 未生成
- `playlist_create_dry_run`: config 未生成による設定ロード失敗
- `ttp_wf_new_readiness`: `config/channel/analytics.json` 未生成
- `initial_setup_readiness`: `config/skills/thumbnail.yaml` / `config/skills/suno.yaml` 未転記由来

その他の fail / warn / unknown は `next_action` を完了するまで先へ進まない。seed fetch の認証を既存チャンネルの token コピーで代替しない。

## Configuration input schema

Step 1 の TTP ヒアリングとは別に、次の初期値をユーザーへ確認する。

- 仮チャンネル名と SHORT: `meta.json::channel.name` / `channel.short`
- 初期ジャンル情報: `genre.primary` / `genre.style` / `genre.context`
- 音楽エンジン: `music_engine` の `suno` / `lyria`
- DistroKid 配信有無: 配信する場合だけ `distrokid.enabled=true`
- DistroKid 初期 profile: 配信する場合だけ `artist` / `language` / `main_genre` / `sub_genre` / songwriter first / last

動画尺は Step 5.5 で承認済み TTP の benchmark から導出し、ここでは手入力しない。DistroKid 配信時の `artist`、`language`、`main_genre` は必ず確認し、推測 default では埋めない。

## Initial file generation details

通常の初期化では次を生成する。

- `config/channel/{meta,content,youtube,analytics,playlists,workflow,audio}.json`
- `config/localizations.json`
- `config/schedule_config.json`（`upload_settings` を含む）
- `config/skills/{suno,thumbnail}.yaml`
- `.gitignore`
- `auth/client_secrets.template.json`

DistroKid 配信時だけ `config/channel/distrokid.json` を追加生成する。配信しない場合は `--distrokid-enabled` を指定せず、ファイル未配置を config loader が `distrokid.enabled=false` として扱う。

`workflow.json::scheduled_automation` は生成せず、未設定を既定の無効状態とする。定期実行は運用開始後に `/automation-schedule` で有効化する。

既存ファイルは `--force` なしで上書きしない。差分がある場合は unified diff を確認してから `--force` を判断する。初期ディレクトリ生成は `/setup` の責務であり、`yt-channel-init` は setup が作成済みのディレクトリを削除・再生成しない。

TTP 候補の URL / handle / channel ID と関係性メモは残すが、Step 4 では `benchmark.channels` へ書き込まない。Step 5 の実データ確認とユーザー承認後に承認済み対象だけを反映する。
