# 単一チャンネル repository から workspace への移行

multi-channel workspace は opt-in です。従来の「1 repository = 1 channel」構成も恒久サポートされるため、既存利用者が移行を強制されることはありません。

workspace では channel 固有データを `channels/<slug>/` に置き、`.claude/skills/`、`.claude/CLAUDE.md`、共通 docs は repository root に1セットだけ置きます。設計判断は [ADR-0022](adr/0022-multi-channel-workspace.md) を参照してください。

## 1. workspace を準備する

空の private repository を clone し、その root へ移動します。`channels/` と media 用 `.gitignore` は初回 import 時に自動生成されます。

```bash
git clone <your-private-workspace-repository>
cd <your-private-workspace-repository>
```

移行元 repository は削除・移動しません。import はコピーだけを行い、失敗時は作成途中の target を rollback します。

## 2. channel を取り込む

slug を明示する場合:

```bash
uv run yt-channel-import /absolute/path/to/existing-channel --slug ambient-island
```

`--slug` を省略すると `config/channel/meta.json` の `channel.youtube_handle`、`channel.short`、`channel.name` の順で候補を作り、確認後だけ実行します。無人実行では確認できないため `--slug` を明示してください。

CLI は次の channel 固有 path だけをコピーします。

- `config/`, `auth/`, `data/`, `collections/`, `assets/`, `branding/`, `research/`
- `docs/channel/`, `docs/benchmarks/`

`.claude/` や共通 docs はコピーしません。既存の同名 target、必須 config 欠落、`config/channel/*.json` の load 失敗を検出すると target を残さず停止します。

### symlink の扱い

移行元 repository 内かつ上記コピー対象 path 内の通常ファイルを指す symlink だけを許可し、リンクではなく解決先の内容を通常ファイルとしてコピーします。`data/thumbnail_compare/<slug>/*.jpg` が同じ repository の `collections/live/.../10-assets/thumbnail.jpg` を指す構成はこの経路で移行でき、移行先に絶対 path の symlink は残りません。

repository 外、コピー対象外、存在しない解決先、directory、循環 link を指す symlink は validation error として import 全体を rollback します。移行前に安全な内部 link を手動で実体化する必要はありません。

成功時は config load の結果と `auth/client_secrets.json` / `auth/token*.json` のコピー先を表示します。auth が `missing` の場合は、旧 repository の正しい channel 用ファイルを確認してから配置してください。OAuth client の統合や再認証はこの移行では行いません。

## 3. 共有 assets を同期する

workspace root で1回だけ実行します。

```bash
uv run yt-skills sync
```

続いて channel 一覧と診断を確認します。

```bash
uv run yt-channel list
uv run yt-doctor --channel ambient-island
```

channel directory 内で実行する CLI は従来どおり cwd から channel を解決します。workspace root から実行するときは `--channel ambient-island` または `CHANNEL=ambient-island` を指定します。
`yt-doctor` の bootstrap 診断は channel 固有の config / auth と、workspace root に1セットだけ置いた `pyproject.toml` / `.claude/skills` / `.agents/skills` を組み合わせて検査します。

## 4. `.env` と git 管理対象を確認する

移行元に `.env` がある場合、CLI はコピーせず警告します。特に固定 `CHANNEL_DIR` は workspace の slug 解決と矛盾するため削除してください。workspace では永続的な active channel を作らず、cwd / `--channel` / `CHANNEL` で毎回明示します。

生成音声・動画・画像と stock 音源は import 時に追加される `.gitignore` で管理外になります。config、workflow state、metadata、調査資料は引き続き commit 対象です。commit 前に `git status --short` で意図した対象だけが staged されることを確認してください。

## 5. 切り戻しと旧 repository の archive

本番操作を始める前なら、切り戻しは workspace 側の `channels/<slug>/` を削除するだけです。移行元は import により変更されないため、そのまま従来運用へ戻れます。

workspace 側で analytics 収集から制作、upload、公開後処理まで1サイクル完走した後に、旧 GitHub repository を Settings の archive 操作で read-only にします。旧 repository は削除せず、rollback と監査のため保持してください。archive 後に問題が見つかった場合は unarchive し、workspace 側で外部反映していないことを確認してから旧運用へ戻します。

first-party channel も external user も同じ手順を使います。複数 channel を移行するときは一度に切り替えず、1 channel ずつ完走を確認してください。
