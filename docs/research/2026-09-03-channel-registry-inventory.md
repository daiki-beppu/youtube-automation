# channel registry（`~/.config/tayk/channels.json`）の schema・writer・consumer 棚卸し

- 調査日: 2026-09-03
- 対象: #4872（Part of #4871 wayfinder map）
- 調査方法: 本リポジトリ（`main` @ `9502fe5f`）のコード・tests・docs、運営者マシン上の実ファイル `~/.config/tayk/channels.json` とその周辺、下流 workspace リポ（`youtube-channels-workspace`）の実ディレクトリ、tayk リポの docs を一次情報として読んだ。コードの変更・実行（`uv run`）・API 呼び出しは行っていない
- 前提: fan-out（#4874）が「dashboard 用 channel registry を台帳として流用する」ことの可否判断に使う。実値は first-party 運営者本人のマシンのものなので絶対パスをそのまま載せる

## ステータスの読み方

- **確認済み**: 2026-09-03 に一次情報（コード / tests / docs / 実ファイル）で確認できた
- **未確認**: 一次情報から確定できず、推測で補っていない（末尾「未確認事項」に集約）
- 根拠は `path:line` で示す。本リポジトリ外のファイルは絶対パスで示す

## 結論

| 観点 | 要旨 |
|---|---|
| schema | **確認済み**: 「空でない絶対パス文字列」だけの JSON 配列。slug / 表示名 / 種別などの属性は持てず、object 形式は拒否される。表示名は各チャンネルの `config/channel/meta.json` の `channel.name` から、channel id はパス文字列の sha256 から導出される |
| writer | **確認済み**: 本リポジトリに書き込み経路は存在しない（loader は読み取り専用、CLI / skill / hook / migration 手順のいずれも触らない）。このマシンの実ファイルは 2026-08-08 に Claude Code セッションが手で書き換えたもの（`cp` で `.bak` 退避 → `Write`） |
| consumer | **確認済み**: `yt-dashboard` だけが読む。`yt-workspace-status` / `yt-workspace-guard` / `yt-channel list` は registry ではなく cwd 祖先の workspace `channels/` を列挙する。hook に registry 消費はない。tests は fixture で `--registry` を差し替える |
| 実値 | **確認済み**: 6 件（001ch〜006ch）が workspace 内 `channels/<slug>/` を指す。**007ch-slowpour は未登録**（workspace 実体には存在）。独立リポ時代のパスは `channels.json` には残っておらず `channels.json.bak` にのみ残る（6 件とも実体は消滅済み）。登録パスは symlink `/Users/mba/02-yt/youtube-channels-workspace` 経由 |
| ADR-0013 との境界 | **確認済み**: registry は「dashboard の起動時収集・表示対象を発見する手段」として `yt-dashboard` が所有し（ADR-0013:15、architecture.md:78）、ADR-0022:15 で workspace 内パスも指せると再解釈された。fan-out 流用で衝突するのは (1) エントリ意味論の二重化（表示対象 = 更新・commit 対象）、(2) 現行 6 エントリが git リポでも `pyproject.toml` 保持者でもない workspace 内ディレクトリである点、(3) 書き込み経路・登録 UX の不在、(4) `infrastructure/analytics/` 配下という配置と CI path filter、(5) `~/.config/tayk/` が tayk（TS 版）と共有される名前空間である点 |

fan-out の台帳として流用すること自体はコード上の障害がない（loader は汎用で、`ChannelRegistryError` も `ConfigError` 系）。ただし「今の実値のまま」では fan-out の 3 手順（`uv add -U` → `yt-skills sync --force` → `git commit`）を 1 件も実行できない。逆移行が進んで独立リポのパスに置き換わるまでの移行期間に、workspace 内エントリと独立リポエントリが混在する registry をどう扱うかが、#4874 と #4876 で先に決めるべき点になる。

## 1. schema

### 1.1 loader が受理する形

| 規則 | 根拠 |
|---|---|
| 既定パスは `Path.home() / ".config" / "tayk" / "channels.json"`（環境変数での上書きなし） | `src/youtube_automation/infrastructure/analytics/channel_registry.py:11` |
| ルートは JSON 配列。object 等は `ChannelRegistryError` | `channel_registry.py:28-29`、`tests/infrastructure/analytics/test_channel_registry.py:23-36`（`{"channels": []}` を拒否） |
| 各要素は空でない文字列 | `channel_registry.py:34-35` |
| 各要素は絶対パス（相対は拒否） | `channel_registry.py:36-38`、`test_channel_registry.py:28` |
| 重複は `os.path.normcase(os.path.normpath(value))` で判定し拒否。`resolve()` はしないので **symlink と実体パスは別物として通る** | `channel_registry.py:39-42`、`test_channel_registry.py:46-52` |
| 宣言順を保って `list[Path]` で返す。並び替えなし | `channel_registry.py:15, 43-44`、`test_channel_registry.py:14-20` |
| ファイル欠損 / 読取不能 / 不正 JSON はいずれも `ChannelRegistryError` | `channel_registry.py:17-26`、`test_channel_registry.py:39-43` |
| `ChannelRegistryError` は `ConfigError` の派生 | `src/youtube_automation/core/errors.py:22-23` |

要素はパス文字列だけであり、slug・表示名・種別（workspace 内 / 独立リポ）・有効フラグなどの属性を持つ余地がない。docs も同じ形を示す（`docs/dashboard.md:7-14`、`docs/architecture.md:78`）。

### 1.2 slug / 表示名の解決元

| 項目 | 解決方法 | 根拠 |
|---|---|---|
| 表示名 | `<entry>/config/channel/meta.json` の `channel.name`。欠損・不正なら `status="invalid_channel"` としてディレクトリ名（`channel.name`）を fallback 表示 | `src/youtube_automation/infrastructure/analytics/dashboard_read_model.py:318-326, 370-378` |
| channel id（API の `/api/channels/<id>`） | registry の**パス文字列そのもの**の sha256 先頭 16 hex を `channel-<digest>` にしたもの。symlink 表記か実体表記かで id が変わる | `dashboard_read_model.py:248-250`、`src/youtube_automation/commands/analytics/dashboard.py:156-165` |
| slug | registry には存在しない。workspace の slug は `channels/` 直下のディレクトリ名として別系統で定義される | `docs/architecture.md:74`、`src/youtube_automation/configuration/loader.py:109-118` |
| 設定全体 | `load_config_from_path(channel)` が singleton に触れず読む（`resolve()` 済みパスで `_build`） | `loader.py:238-240`、`dashboard.py:49`、CHANGELOG.md:736（#3322） |

### 1.3 workspace 内 `channels/<slug>/` を指すエントリ

- loader はパスの中身を検査しない（`channel_registry.py:36-43`）ので、workspace 内ディレクトリも独立リポも同じ「絶対パス」として通る
- ADR-0022 は「registry のエントリが workspace 内の `channels/<slug>/` を指せばよい」と明記し（`docs/adr/0022-multi-channel-workspace.md:15`）、Consequences で「workspace 内パスも指せる定義に更新済み」と述べる（同 `:52`）。ただし `docs/architecture.md:78` の用語定義そのものは「first-party チャンネルの絶対パス一覧」とだけ書かれており、workspace の語は含まない（定義がパス種別に中立、という意味で ADR-0022 と矛盾はしない）
- 実値は 6 件すべてが workspace 内パス（§4）

## 2. writer

### 2.1 本リポジトリ内

| 経路 | 結果 | 根拠 |
|---|---|---|
| loader モジュール | 読み取り専用。`write_text` / `json.dump` なし。docstring も「読み取り専用 loader」 | `channel_registry.py:1`（grep で書き込み API なし） |
| `src/` 全体 | `channels.json` / `channel_registry` / `DEFAULT_CHANNEL_REGISTRY` を参照するのは `channel_registry.py` と `commands/analytics/dashboard.py` の 2 ファイルのみ | grep（`src/**/*.py`、`dashboard_dist/` 除外） |
| `yt-channel-import`（workspace への取り込み CLI） | registry を触らない | `src/youtube_automation/commands/channel/channel_import.py:16`（import は `find_workspace_root` / `load_config` / `reset` のみ）、grep 結果 |
| `/setup`（`--channel` / `--import` mode） | SKILL.md・references に registry / channels.json への言及なし | grep（`.claude/skills/setup/`） |
| 全 skill（`.claude/skills/**`） | `yt-dashboard` に言及するのは analytics skill だけで、いずれも読み取りの説明 | `.claude/skills/analytics/SKILL.md:107`、`.claude/skills/analytics/references/collect.md:68` |
| hook（`.claude/settings.json`） | PreToolUse / PostToolUse / UserPromptSubmit の全 command に registry 参照なし | `.claude/settings.json`（hooks section を列挙して確認） |
| 移行ガイド | `docs/channel-workspace-migration.md` の 5 節に registry 更新の手順はない | 同ファイル見出し（1. workspace 準備 / 2. channel 取り込み / 3. assets 同期 / 4. .env と git / 5. 切り戻し） |
| dashboard UI | 空 registry 時に「`~/.config/tayk/channels.json` にチャンネルの絶対 path を追加してください」と**手動編集を案内** | `dashboard/src/App.tsx:996-999` |

結論: 本リポジトリに registry の登録・削除経路は存在しない。運用上は手動編集が前提になっている。

### 2.2 tayk（TS 版）側

- tayk の `CONTEXT.md` と ADR-0001 は同じ `~/.config/tayk/channels.json` を「channel registry（絶対パス文字列の JSON 配列）」として定義する（`/Users/mba/ghq/github.com/daiki-beppu/tayk/CONTEXT.md:117-118`、`/Users/mba/ghq/github.com/daiki-beppu/tayk/docs/adr/0001-thin-architecture.md:24`）
- tayk `main` の `src/` には `channels.json` の reader / writer はない（grep）。`channel bootstrap`（`tayk init`）は「registry への既存リポ登録を指さない」と用語定義で明示（`CONTEXT.md:120-122`）
- 未マージ worktree（`issue-389-auth`）は `~/.config/tayk/<channel>/client_secrets.json` を credential root にしており（`.claude/worktrees/issue-389-auth/src/youtube/auth.ts:232`）、同じディレクトリ名前空間を別用途で使う計画がある

### 2.3 このマシンでの実際の書き手

- `~/.config/tayk/channels.json` と `channels.json.bak` の mtime は同一（2026-08-08 13:21 JST）
- Claude Code セッション transcript（`~/.claude/projects/-Users-mba-02-yt-00-automation/d1aed146-d811-4b7d-bd2d-bc19e02ef9e2.jsonl`）に、`cat` で旧内容を確認 → `cp ... channels.json.bak` → `Write /Users/mba/.config/tayk/channels.json` の順で 6 件を `youtube-channels-workspace/channels/00Nch-*` へ書き換えた記録がある（2026-08-08T04:21Z）。動機は「dashboard が読む registry が存在しない古いパスを指していた」こと
- `.bak` 以前の作成時期・作成手段は transcript からは確定できない（未確認事項）

## 3. consumer

| consumer | registry を読むか | 根拠 |
|---|---|---|
| `yt-dashboard`（`commands/analytics/dashboard.py`） | **読む**。`--registry`（既定 `DEFAULT_CHANNEL_REGISTRY`）→ `load_channel_registry` → 収集（`refresh_dashboard_channels`）と read model（`build_dashboard_read_model`）へ登録順のまま渡す | `dashboard.py:24-27, 233, 266-271, 280-293`、`infrastructure/analytics/dashboard_refresh.py:110-126`、`dashboard_read_model.py:630-638` |
| `yt-workspace-status` | **読まない**。cwd 祖先から `find_workspace_root` / `workspace_channels` で workspace の `channels/` を列挙 | `src/youtube_automation/commands/channel/workspace_status.py:14-18, 61-70`、`loader.py:109-128` |
| `yt-workspace-guard` | **読まない**。同上の workspace 列挙 | `src/youtube_automation/commands/channel/workspace_guard.py:9` |
| `yt-channel list` | **読まない**。同上 | `src/youtube_automation/commands/channel/channel.py:11, 75` |
| hook（Claude Code） | なし | `.claude/settings.json` hooks |
| tests | `test_channel_registry.py`（loader 契約）、`tests/commands/analytics/test_dashboard_server.py:149`（fixture が tmp registry を書く）と `:642, 680, 727, 780`（`load_channel_registry` を monkeypatch）、`tests/repo/test_dashboard_packaging.py:30-31`（空配列 registry で wheel smoke）、`dashboard/e2e/dashboard.spec.ts:273-274`（2 件 registry で `yt-dashboard --skip-refresh --registry`） | 各行 |
| 契約テスト / CI | ファイル位置を `infrastructure/analytics/channel_registry.py` に固定。`dashboard.yml` の path filter にも列挙 | `tests/contracts/architecture/test_repository_reorganization_contract.py:1695-1699`、`.github/workflows/dashboard.yml:10, 20`、`docs/architecture/repository-reorganization-receipt.json:50-57` |
| 下流 workspace の起動設定 | `uv run yt-dashboard` / `--skip-refresh` を workspace ルートから起動する launch 設定がある。cwd は workspace ルートだが、対象チャンネルは registry で決まる | `/Users/mba/ghq/github.com/daiki-beppu/youtube-channels-workspace/.claude/launch.json:4-15` |

`yt-dashboard` 内部の per-channel 実行は、`CHANNEL_DIR` を差し替えて `reset_config()` する in-process のコンテキスト切替で行う（`dashboard_refresh.py:36-56`）。ADR-0022 が「プロセス内での singleton 切替による横断実行は恒久禁止、将来は subprocess 分離のランナー」と定めている点（`docs/adr/0022-multi-channel-workspace.md:44`）と併せて §5 で扱う。

## 4. このマシン上の実値（2026-09-03）

### 4.1 `~/.config/tayk/channels.json`（mtime 2026-08-08 13:21）

```json
[
  "/Users/mba/02-yt/youtube-channels-workspace/channels/001ch-afro-deep-noir",
  "/Users/mba/02-yt/youtube-channels-workspace/channels/002ch-deepfocus365",
  "/Users/mba/02-yt/youtube-channels-workspace/channels/003ch-soulful-grooves",
  "/Users/mba/02-yt/youtube-channels-workspace/channels/004ch-veluvia",
  "/Users/mba/02-yt/youtube-channels-workspace/channels/005ch-abyss",
  "/Users/mba/02-yt/youtube-channels-workspace/channels/006ch-harana-island-sounds"
]
```

| 確認項目 | 結果 |
|---|---|
| 件数 | 6 件（issue の「7ch」想定に対し **007ch-slowpour が未登録**） |
| 6 件の実体 | すべてディレクトリとして存在し、`config/channel/meta.json` を持つ（`channel.name` は順に AFRO DEEP NOIR / DeepFocus365 / Soulful Grooves / Veluvia / ABYSS MI / Harana Island Sounds） |
| git | 6 件とも自身の `.git` を持たない。git toplevel は workspace ルート `/Users/mba/ghq/github.com/daiki-beppu/youtube-channels-workspace`（remote `git@github.com:daiki-beppu/youtube-channels-workspace.git`） |
| `pyproject.toml` | workspace ルートにのみ存在し、`youtube-channels-automation = { git = "https://github.com/daiki-beppu/youtube-automation.git", branch = "main" }` を依存に持つ（同 `pyproject.toml:12`）。`channels/<slug>/` 配下には存在しない |
| パス表記 | `/Users/mba/02-yt/youtube-channels-workspace` は symlink → `/Users/mba/ghq/github.com/daiki-beppu/youtube-channels-workspace`（`ls -la /Users/mba/02-yt/`）。registry は symlink 側の表記で登録されている |
| 独立リポ時代のパス | `channels.json` には残っていない |

### 4.2 `~/.config/tayk/channels.json.bak`（同 mtime）

```json
[
  "/Users/mba/02-yt/1ch-afro-deep-noir",
  "/Users/mba/02-yt/2ch-deepfocus365",
  "/Users/mba/02-yt/3ch-soulful-grooves",
  "/Users/mba/02-yt/4ch-veluvia",
  "/Users/mba/02-yt/5ch-abyss",
  "/Users/mba/02-yt/6ch-harana-island-sounds"
]
```

- 6 パスとも現在は存在しない（`/Users/mba/02-yt/` 直下にあるのは `00-automation` / `tayk` / `youtube-channels-workspace` の symlink、`1ch-test`、`takt-worktrees`、`worktrees`、`yt-research` のみ）
- これが「独立リポ時代のパス」の唯一の痕跡。ADR-0022:42 の「旧リポは archive として残す」は GitHub 側の話で、ローカルの実体は消えている

### 4.3 workspace 側の実体

- `/Users/mba/ghq/github.com/daiki-beppu/youtube-channels-workspace/channels/` には `001ch`〜`007ch` の 7 ディレクトリがある。`007ch-slowpour` は `config/channel/meta.json`（`channel.name` = "slowpour"、handle `@lowpour.playlists`）を含む完全な channel 構成を持つが、registry にも workspace `README.md` の Channels 一覧（001〜006 の 6 件）にも載っていない
- `~/.config/tayk/` 直下にあるのは `channels.json` と `channels.json.bak` の 2 ファイルだけ（tayk 側の credential ディレクトリはまだ作られていない）

## 5. ADR-0013 の責務境界と fan-out 流用時の衝突

### 5.1 ADR-0013 / architecture が定める境界

| 契約 | 根拠 |
|---|---|
| registry は `yt-dashboard` の担当（channel registry・起動時収集・read model・JSON API・loopback 配信を一括所有） | `docs/adr/0013-multi-channel-dashboard.md:15`、`docs/architecture.md:281`、`docs/development.md:110` |
| 通常起動は registry の全チャンネルを**登録順に API 収集**してから配信。1 件の失敗は部分エラー隔離 | ADR-0013:18-19、`docs/dashboard.md:22` |
| 配列の順序 = UI の表示順 | `docs/dashboard.md:7` |
| 「表示名などは `meta.json` から解決し、dashboard が消費する」 | `docs/architecture.md:78` |
| registry は「設定ファイルとして増える」consequence（バックアップ・git 管理・スキーマ進化の方針なし） | ADR-0013:58 |
| 単一チャンネル用 CLI（`yt-kpi-dashboard` / `--collect`）の責務は変えない | ADR-0013:22 |
| ADR-0022 による再解釈: registry は「dashboard の起動時収集・表示対象を発見する手段」であり、workspace 内 `channels/<slug>/` を指してよい | `docs/adr/0022-multi-channel-workspace.md:15, 52` |
| 横断一括実行は v1 スコープ外。将来は subprocess 分離ランナーで実現し、in-process singleton 切替は恒久禁止 | ADR-0022:44 |

### 5.2 fan-out（#4871 の確定事項: チャンネルごとに `uv add -U` → `yt-skills sync --force` → `git commit`、部分エラー隔離、`--dry-run` / `--no-commit`）に流用したときの衝突

| # | 衝突 | 事実（根拠） | 影響 |
|---|---|---|---|
| 1 | **エントリ意味論の二重化** | schema は属性なしのパス配列（§1.1）。「dashboard に出すが更新しない」「更新するが dashboard に出さない」を表現できない | 例: 007ch-slowpour のような立ち上げ中チャンネル、archive 予定チャンネルを片方だけから外せない。属性を足すには object 形式を受理する schema 変更が必要で、`channel_registry.py:28-29` と `test_channel_registry.py:27` の契約を変える |
| 2 | **現行エントリが fan-out の単位になれない** | 6 件とも workspace 内ディレクトリで、`.git` も `pyproject.toml` も持たない（§4.1）。fan-out の 3 手順はいずれも「チャンネルリポのルート」を前提とする | 逆移行完了までの移行期間、registry には workspace 内エントリと独立リポエントリが混在する。fan-out は各エントリで「git toplevel == エントリ」「`pyproject.toml` 存在」を判定して skip / 部分エラーにする設計が要る（あるいは workspace 内エントリは workspace ルートへ集約して 1 回だけ更新する、という別意味論） |
| 3 | **書き込み経路・登録 UX の不在** | writer は本リポにも tayk にもなく、手動編集前提（§2）。`yt-channel-export`（#4876）で生まれる独立リポの登録、workspace slug の登録解除はすべて手作業になる | fan-out が「1 操作化」を目的とするなら、registry の add / remove（少なくとも export 時の自動登録）を誰が持つかを決める必要がある。#4871「Not yet specified」の dashboard 側 registry 更新 UX と同じ論点 |
| 4 | **配置と CI の所有権** | loader は `infrastructure/analytics/` にあり、契約テストと receipt がその位置を固定（`test_repository_reorganization_contract.py:1695-1699`、`repository-reorganization-receipt.json:50-57`）。CI の `dashboard.yml` path filter に載る（`:10, 20`） | 配布層（`yt-skills sync` 系）の fan-out コマンドが analytics 配下の loader を import すると、依存方向（配布 → analytics）が新設される。中立な場所（`configuration/` 等）への移設は契約テスト・receipt・CI filter の 3 点更新を伴う |
| 5 | **`~/.config/tayk/` 名前空間の共有** | tayk（TS 版）が同じファイルを自らの registry と定義し（§2.2）、credential root としても同ディレクトリを使う計画がある | Python 側が writer を持つと、2 製品が同一ファイルを書く状態になる。tayk は現状 reader も writer も実装していないので衝突は潜在的だが、schema を拡張（#1）するなら tayk ADR-0001:24 の「絶対パス文字列の JSON 配列」との乖離が生じる |
| 6 | **symlink とパス同一性** | loader は `resolve()` しない（`channel_registry.py:39`）。実値は symlink 表記（§4.1）。`_channel_id` はパス文字列の hash（`dashboard_read_model.py:248-250`）、`load_config_from_path` は `resolve()` 済みで読む（`loader.py:238-240`） | fan-out が「commit 先がエントリ自身のリポか」を `git rev-parse --show-toplevel`（実体パスを返す）と比較する場合、resolve なしでは一致しない。symlink と実体の二重登録も重複検出をすり抜ける |
| 7 | **順序の意味** | 順序 = UI 表示順（`docs/dashboard.md:7`） | fan-out の実行順に流用しても害はないが、「表示順を変えると更新順も変わる」という暗黙結合が生まれる |
| 8 | **横断実行の方式** | `yt-dashboard` は in-process の env 差し替え + `reset_config()` で横断する（`dashboard_refresh.py:36-56`）。ADR-0022:44 はこれを横断バッチの正規手段と認めていない | fan-out は各チャンネルで `uv run` を subprocess 起動する前提（#4871）なので ADR-0022:44 と整合するが、dashboard の `_channel_context` を再利用してはいけない。「同じ registry を読むが実行方式は別」を明文化する必要がある |
| 9 | **バックアップ・履歴の不在** | git 管理外、backup は手動 `.bak` のみ（§2.3、ADR-0013:58） | fan-out が registry を書き換える（#3）なら、dashboard の唯一の設定ファイルを別責務のコマンドが壊し得る。原子的書き込みと `.bak` 相当の退避を writer 側に持たせる論点 |

### 5.3 流用に有利な事実

- loader は dashboard 固有の知識を持たず、`list[Path]` を返すだけ（`channel_registry.py:14-44`）。fan-out から `load_channel_registry(path)` を呼ぶこと自体に障害はない
- 例外は `ConfigError` 系（`errors.py:22`）で、fan-out の `--dry-run` 前検証にそのまま使える
- 部分エラー隔離のパターン（`refresh_dashboard_channels`、`dashboard_refresh.py:110-126`: `dict[Path, str]` で失敗を返し継続）は fan-out の要件（#4871）と同型で、実装の参照モデルになる
- `--registry <path>` で差し替える test 手法（`test_dashboard_server.py:149`、`dashboard.spec.ts:273-274`）が確立しており、fan-out の tests も同じ fixture 流儀に乗れる

## 一次情報

- `src/youtube_automation/infrastructure/analytics/channel_registry.py`（loader 全 44 行）
- `tests/infrastructure/analytics/test_channel_registry.py`（loader 契約）
- `src/youtube_automation/commands/analytics/dashboard.py`（`yt-dashboard`）
- `src/youtube_automation/infrastructure/analytics/dashboard_read_model.py:248-250, 318-326, 370-378, 630-638`
- `src/youtube_automation/infrastructure/analytics/dashboard_refresh.py:36-56, 110-126`
- `src/youtube_automation/configuration/loader.py:109-128, 218-224, 238-240`
- `src/youtube_automation/commands/channel/workspace_status.py:14-18, 61-70`、`workspace_guard.py:9`、`channel.py:11, 75`、`channel_import.py:16`
- `src/youtube_automation/core/errors.py:22-23`
- `tests/commands/analytics/test_dashboard_server.py:149, 642, 680, 727, 780`、`tests/repo/test_dashboard_packaging.py:30-31`、`dashboard/e2e/dashboard.spec.ts:273-274`
- `tests/contracts/architecture/test_repository_reorganization_contract.py:1695-1699`、`docs/architecture/repository-reorganization-receipt.json:50-57`、`.github/workflows/dashboard.yml:10, 20`
- `dashboard/src/App.tsx:996-999`
- `docs/adr/0013-multi-channel-dashboard.md:15-22, 58`、`docs/adr/0022-multi-channel-workspace.md:15, 42-44, 52`
- `docs/architecture.md:72-80, 281`、`docs/dashboard.md:5-14, 22, 38`、`docs/development.md:110`、`docs/channel-workspace-migration.md`（見出し）
- `.claude/skills/analytics/SKILL.md:107`、`.claude/skills/analytics/references/collect.md:68`、`.claude/settings.json`（hooks）
- `CHANGELOG.md:736, 859, 1040`、git log: `4b745724`（#2387 で loader 追加）、`1b77c508`（#3022 で `utils/` → `infrastructure/analytics/` へ移設）
- `~/.config/tayk/channels.json`、`~/.config/tayk/channels.json.bak`（2026-08-08 13:21 JST）
- `~/.claude/projects/-Users-mba-02-yt-00-automation/d1aed146-d811-4b7d-bd2d-bc19e02ef9e2.jsonl`（2026-08-08 の書き換え記録）
- `/Users/mba/ghq/github.com/daiki-beppu/youtube-channels-workspace/`（`channels/`、`README.md`、`pyproject.toml:12`、`.claude/launch.json`）
- `/Users/mba/ghq/github.com/daiki-beppu/tayk/CONTEXT.md:117-122`、`/Users/mba/ghq/github.com/daiki-beppu/tayk/docs/adr/0001-thin-architecture.md:24`

## 未確認事項

- `channels.json` が 2026-08-08 より前にいつ・どの手段で作られたか（transcript には `.bak` 退避以前の作成記録がない。内容は `.bak` と同一と推定できるが確認手段がない）
- `007ch-slowpour` が workspace リポの git 管理下にあるか（本調査は worktree 隔離のため他リポで git を実行していない。ディレクトリと `meta.json` の存在のみ確認）
- tayk 側が将来 registry の reader / writer を実装する予定があるか（`main` の src にはなく、CONTEXT.md / ADR-0001 の定義のみ）
- fan-out が registry を書き換える設計を採るか（#4874 / #4876 の判断待ち。本稿は「現状 writer がない」事実の提示まで）
