# workspace 依存コード・docs・site ページの棚卸し（削除対象一覧）

- 調査日: 2026-09-03
- 対象 issue: #4873（Part of #4871「複数チャンネル運用を workspace から 1 チャンネル = 1 リポ + registry fan-out へ戻す道筋」）
- 対象 commit: `9502fe5f`（main、2026-09-03 時点）
- 調査方法: 本リポジトリの `src` / `tests` / `docs` / `site` / `.claude/skills` / `.claude/settings.template.json` / `pyproject.toml` / `.github/workflows` を `grep -rn "workspace\|--channel\b\|CHANNEL\b\|channel_slug\|find_workspace_root\|workspace_channels"` で走査し、hit した行を実装・契約テスト・CHANGELOG と突き合わせた。コードは実行していない（`uv run` 不使用）。根拠は `file:line` で示し、読めなかったものは「要確認」と書いて推測で埋めない
- 前提: ADR-0022（`docs/adr/0022-multi-channel-workspace.md`）を supersede し、workspace 経路（`--channel` / `CHANNEL` / workspace 検出 / `yt-workspace-guard` / `yt-workspace-status`）を deprecated → 次マイナーで削除する（#4871 Notes）

## 分類の読み方

- **警告**: 利用者が直接触る入口（公開 API・console script・共通 CLI オプション・公開ページ）。非推奨期間中は動作を維持したまま deprecation 警告を出し、次マイナーで削除する
- **削除**: 警告対象の入口経由でしか到達しない内部実装、および入口と同時に消す tests / docs / site 設定。非推奨期間中に単独で警告を出す必要はない
- **残す**: workspace 由来だが単一リポでも意味を持つもの、履歴として不変なもの、および同名だが無関係なもの

「単一リポ」は `config/channel/` をリポジトリルートに持つ従来構成（ADR-0022:7 の「単一チャンネルリポ構成は恒久サポート」）を指す。

## 結論

- workspace 経路は `configuration/loader.py::find_workspace_root` を唯一の検出点として、src 内 11 module（下表 A）がそこから枝分かれしている。deprecation 警告はこの 1 点に置けば、`channels/<slug>/` 内 cwd で `--channel` を一度も打たない利用者にも届く
- 削除の障害は 2 つ。(1) 下流 `.claude/settings.json` に merge 済みの `yt-workspace-guard` hook は template から消しても下流に残り（settings merge は追加専用）、console script を先に消すと Edit/Write が block される。(2) `run-sandwich.sh` が `yt-human-tasks --channel <slug>` を無条件に渡しており、単一チャンネル checkout では現行でも `ConfigError` になる
- skills 層は `yt-channel list` / `yt-channel-import` / `yt-workspace-*` / `CHANNEL=` を一切参照していない（repo-wide grep）。SKILL.md 側の変更は `music/references/master.md:370` の一文と `run-sandwich.sh:45` の 1 引数だけ
- 件数: 警告 11 / 削除 48 / 残す 31（表 A〜E の行数。行の数え方は各表末尾）

## A. コード（`src` / `pyproject.toml` / `.claude/settings.template.json`）

| 対象 | 種別 | 分類 | 根拠 |
|---|---|---|---|
| `src/youtube_automation/configuration/loader.py::find_workspace_root` (121-126) | workspace root 検出 | **警告** | 全 workspace 経路の唯一の入口。`find_workspace_root` / `workspace_channels` を import する src module は 11 件（`checks.py` / `channel.py` / `channel_import.py` / `workspace_guard.py` / `workspace_status.py` / `doctor.py` / `hybrid_runner.py` / `skills_sync/__init__.py` / `configuration/__init__.py` / `loader.py` / `auth/youtube.py`）。`channels/<slug>/` 内 cwd は `--channel` なしで暗黙解決される（loader.py:198-199、`tests/configuration/test_config_loader.py:1886`）ため、`--channel` / `CHANNEL` 側だけで警告しても workspace 利用者に届かない |
| `configuration/loader.py::workspace_channels` (109-119) | slug 列挙 | **警告** | 公開 API（`configuration/__init__.py:9,30,51`）。`find_workspace_root` と同時に削除 |
| `configuration/loader.py::select_channel` / `explicit_channel_selection` / `_explicit_channel` (77, 129-142) | `--channel` の一時状態 | **警告** | 公開 API（`configuration/__init__.py:7,10,24,27,45,48`）。共通 `--channel` の受け皿。`_instance` 解決後の変更禁止（134）は workspace 専用契約 |
| `configuration/loader.py::_resolve_slug` (153-162) と `_resolve_channel_dir` の workspace 分岐 (171-173, 175-195, 202-206) | `--channel` / `CHANNEL` 解決チェーン | **警告** | ADR-0022:36 の優先順位 `--channel` > env > cwd。非推奨期間中は動作維持 + 警告、次マイナーで `CHANNEL_DIR` → cwd 祖先の 2 段（167-170, 196-201）へ戻す（ADR-0022:49「既存 2 段は不変」） |
| `configuration/loader.py::reset(preserve_channel_selection=)` (218-224) | 内部 kwarg | 削除 | `_explicit_channel` 専用。`tests/configuration/test_config_loader.py:1848` と同時削除 |
| `configuration/__init__.py` の export `explicit_channel_selection` / `find_workspace_root` / `select_channel` / `workspace_channels` (7-10, 24-30, 45-51) | 公開 API 面 | **警告** | export 一覧は `tests/contracts/architecture/test_repository_reorganization_contract.py:188-194` と `tests/configuration/test_configuration_migration_contract.py:108-114` が固定 |
| `src/youtube_automation/entrypoints.py::_consume_channel_option` / `_CHANNEL_OPTION_CONFLICTS` / `_run` の `select_channel` 呼び出し (12-20, 23-52, 60-64) | 全 `yt-*` 共通 `--channel` | **警告** | v5.6.0 #2049 で追加（CHANGELOG.md:1136）。競合 CLI の旧 `--channel` 拒否は parser 側（`commands/_shared/arguments.py`）で独立しているため、`_CHANNEL_OPTION_CONFLICTS` も共通 option と同時に削除できる |
| `src/youtube_automation/commands/channel/channel.py`（`yt-channel list`）全体、`pyproject.toml:50`、`entrypoints.py:83` | console script | **警告** | ADR-0022:44「v1 は `yt-channel list` の列挙のみ」。参照は `docs/channel-workspace-migration.md:54` と `docs/investigations/2026-08-11-3760-workspace-runtime-bottleneck.md:24` だけ |
| `src/youtube_automation/commands/channel/channel_import.py`（`yt-channel-import`）全体、`pyproject.toml:51`、`entrypoints.py:84` | console script | **警告** | ADR-0022:43。逆方向の `yt-channel-export` が対称に新設される（#4871 Notes）。`_validate_config` の `CHANNEL` env 退避（190-207）と `GITIGNORE_MARKER`（37）も同時削除 |
| `src/youtube_automation/commands/channel/workspace_status.py`（`yt-workspace-status`）全体、`pyproject.toml:57`、`entrypoints.py:97` | console script | **警告** | v5.7.0 #4116 で追加（CHANGELOG.md:188、`docs/release-notes/v5.7.0.md:84`）。skill / docs / workflow からの参照ゼロ（repo-wide grep。`plans/README.md:85` も同じ指摘）。固有 `--channel`（196）は credential 提供元の指定で、共通 option とは別物 |
| `src/youtube_automation/commands/channel/workspace_guard.py`（`yt-workspace-guard check` / `context`）全体、`pyproject.toml:64`、`entrypoints.py:98` | console script（hook 本体） | **警告** | #3370〜#3372（CHANGELOG.md:506-510）。下流 `.claude/settings.json` に hook として merge 済み。console script を template より先に消すと下流 hook が失敗して Edit/Write を block する（「発見 2」） |
| `.claude/settings.template.json:26` PreToolUse `Edit|Write` の `yt-workspace-guard check` hook | hook 配布 | 削除 | root 専用レイアウト判定と slug 越境判定は workspace root 検出後にしか発火しない（`workspace_guard.py:88-91` は root 不在で空を返す）。`skills_sync/_settings.py::missing_hooks`（40-67）は追加専用で prune しない |
| `.claude/settings.template.json:56` SessionStart `yt-workspace-guard context` hook | hook 配布 | 削除 | 単一リポでは `channel_dir=<path>` 1 行しか出さない（`workspace_guard.py:112-115`）。#4871 の「SessionStart 自動追従（補助）」が同じ slot の置換候補 |
| `src/youtube_automation/commands/system/hybrid_runner.py::_resolve_channel_dir` の `workspace_channels` 分岐 (12, 58-69) | cloud sandwich runner | 削除 | v5.7.1 で追加（CHANGELOG.md:51）。`channels` が空なら root を返す fallback（61-62）が単一リポ経路。`--channel-slug` 引数自体は残す（下記） |
| `src/youtube_automation/commands/system/doctor.py::resolve_channel_dir` の `explicit_channel_selection()` / `CHANNEL` / `find_workspace_root` 条件 (45-46, 484-497) | doctor 入口 | 削除 | #2463（CHANGELOG.md:1000）。`CHANNEL_DIR` 条件（493）だけ残す |
| `src/youtube_automation/application/channel_readiness/checks.py::_workspace_root_for_channel` / `_bootstrap_root` (33-34, 562-574) と `CwdSemantics.BOOTSTRAP_ROOT` (132, 258) | doctor bootstrap root | 削除 | workspace 不在なら `channel_dir` に畳まれる（574）ため、`BOOTSTRAP_ROOT` 指定の 7 check（`doctor.py:140-168`）は `CHANNEL` と同値になる。`check_streaming_vps_state`（1311）も同じ helper 経由 |
| `application/channel_readiness/checks.py::check_oauth_client_sharing` (1169-1194)、`doctor.py:108,186` | doctor check | 削除 | workspace 外では常に `ok` を返すだけ（1173-1178）。#1950（`git log 1a2c6224`） |
| `src/youtube_automation/infrastructure/auth/youtube.py:28,60-64` `<workspace_root>/auth/client_secrets.json` 候補 | OAuth client 解決順 | 削除 | v5.6.0（CHANGELOG.md:1128）。候補列は `docs/oauth-setup.md:136-137` と `tests/test_oauth_onboarding_contract.py:165-195` が機械担保するため 3 点同時更新 |
| `src/youtube_automation/infrastructure/vcs/state_git.py::_workspace_state_gitignore_block` / `_uses_workspace_gitignore` (65-73) と呼び出し (193, 277, 303) | state Git 移行 | 削除 | #4332（CHANGELOG.md:121）。`channel_dir != repository` は workspace でしか成立しない（73） |
| `src/youtube_automation/commands/system/skills_sync/__init__.py:45-49,192-196`、`_diff.py:16,63-65`、`_sync.py:15,138-142` `_is_workspace_gitignore_target` | skills sync の `channel-gitignore` skip | 削除 | #4331（CHANGELOG.md:120） |
| `commands/system/skills_sync/_ops.py:123-129` `channels/*/config/skills` 走査 | skills sync の孤児 config 警告 | 削除 | CHANGELOG.md:353。root の `config/skills` 走査（124）は残す |
| `src/youtube_automation/commands/system/automation_update.py::_channel_roots` の `channels/*` glob (182-189) | automation-update smoke check | 削除 | CHANGELOG.md:434。root の `config/channel` 判定（183）は残す |
| `src/youtube_automation/infrastructure/analytics/dashboard_refresh.py:41-43,53-55` `CHANNEL` env の退避 / 復元 | dashboard 収集の隔離 | 削除 | `CHANNEL_DIR` 退避（40,42,49-52）は単一リポでも必要なので残す |
| `.claude/skills/wf-new/references/run-sandwich.sh:45` `yt-human-tasks --channel "$channel_slug"` | cloud runner の呼び出し | 削除 | `yt-human-tasks` は `_CHANNEL_OPTION_CONFLICTS` 外なので共通 `--channel` として `select_channel` に渡る。checkout は `$workspace/channel`（25）の単一チャンネルで workspace root が無く、`loader.py:154-155` が `ConfigError` を投げる（「発見 3」）。`tests/application/test_hybrid_runner.py:651-657` は `uv` を stub して引数を記録するだけ（749-751）なので未検出 |
| `src/youtube_automation/commands/_shared/arguments.py::CompetitorArgumentParser` (10-20) | 旧 `--channel` の拒否メッセージ | 残す | ADR-0022:40,49 の breaking リネームは戻さない。#3923（CHANGELOG.md:423）で共通 option より先に拒否する契約 |
| `--competitor` 引数: `commands/analytics/benchmark_collector.py:1303`、`video_analyze.py:246`、`thumbnail/compare_thumbnails.py:233`、`analytics/fetch_benchmark_comments.py:257` | CLI 引数 | 残す | v5.6.0 Breaking（CHANGELOG.md:1131、`docs/release-notes/v5.6.0.md:35`）。単一リポでも競合 slug は必要 |
| `configuration/loader.py` の `CHANNEL_DIR` env と cwd 祖先探索 (145-150, 167-170, 196-201, 207) | 解決チェーン既存 2 段 | 残す | ADR-0022:49「単一チャンネルリポの external user には破壊的変更なし」 |
| `commands/system/hybrid_runner.py --channel-slug` (23, 98-101) と `application/hybrid_runner.py::SandwichRequest.channel` (76) | cloud runner の識別子 | 残す | handoff key / 通知 channel に使う（`application/hybrid_runner.py:144,176,316`）。`infrastructure/resources/channel/youtube-automation.yml:58`、`wf-new/references/schedule.md:62` も同じ |
| `commands/system/codex_canary_notify.py:20 --channel`、`infrastructure/resources/channel/codex-canary.yml:48` | 通知ラベル | 残す | workspace slug ではなく `NotificationEvent` の channel 名（24-25）。ただし現行は共通 `--channel` に先に消費される（「発見 4」） |
| `dashboard_refresh.py::_channel_context` の `CHANNEL_DIR` 退避 (40,42,49-52) | 隔離 | 残す | registry 経由の複数チャンネル収集は ADR-0013 で workspace と独立 |
| `infrastructure/auth/youtube.py:65-69` main worktree fallback | OAuth 解決順 | 残す | #1721。`docs/oauth-setup.md:138-139` |
| `channel-gitignore` asset と `state_git.py::state_gitignore_block` (59-62) | 単一チャンネルの Git 管理ポリシー | 残す | `infrastructure/resources/channel/gitignore.template` に workspace 記述なし（grep 0 件） |
| benchmark の `channel_slug`: `domains/analytics/benchmark.py:59`、`commands/analytics/video_analyze.py:184`、`fetch_benchmark_comments.py:186`、`domains/channel_readiness/readiness.py:490`、`commands/thumbnail/compare_thumbnails.py:65` | 競合 slug / 自チャンネル short | 残す | `analytics.benchmark.channels[].slug` と `config.meta.channel_short` 由来。workspace slug とは無関係 |
| `commands/channel/channel_init_templates.py:229`、`.claude/skills/music/config.default.yaml:7` `workspace_name` | Suno UI の workspace 名 | 残す | `setup/references/config-generation-rules.md:115`「Suno UI 上のワークスペース名」 |

行数: 警告 10 / 削除 14 / 残す 10。

## B. tests

| 対象 | 種別 | 分類 | 根拠 |
|---|---|---|---|
| `tests/configuration/test_config_loader.py:1822-1949`（`test_workspace_detection_and_channel_listing` 〜 `test_workspace_root_requires_channel_selection` の 12 test） | 解決チェーン | 削除 | 非推奨期間中は警告発生を検証する test に置換し、次マイナーで削除 |
| `tests/commands/channel/test_channel_cli.py` 全体 | `yt-channel list` | 削除 | A 表の CLI と同時 |
| `tests/commands/channel/test_channel_import.py` 全体 | `yt-channel-import` | 削除 | 同上 |
| `tests/commands/channel/test_workspace_guard.py` 全体 | `yt-workspace-guard` | 削除 | 同上 |
| `tests/commands/channel/test_workspace_status.py` 全体 | `yt-workspace-status` | 削除 | 同上 |
| `tests/test_entrypoints.py:17-56`（`test_consume_channel_*` 5 test） | 共通 `--channel` | 削除 | `_consume_channel_option` と同時 |
| `tests/test_cli_stdio.py:183`（`test_cli_entrypoint_consumes_channel_before_importing_target`）、`:34-35` の mapping 2 行 | 共通 `--channel` / CLI 対応表 | 削除 | `:380` の wrapper dispatch test が mapping を走査する |
| `tests/repo/test_cli_harness_gate.py:32-34`（`channel` / `channel_import` / `workspace_guard` の allowlist 行） | 契約 | 削除 | 「移行した module は削除する」（同 file:14） |
| `tests/contracts/architecture/test_repository_reorganization_contract.py:188-194`、`tests/configuration/test_configuration_migration_contract.py:108-114` の export 4 名 | 契約 | 削除 | `configuration/__init__.py` の export と同時 |
| `tests/commands/system/test_doctor.py:664`、`1171-1215`（`oauth_client_sharing` 4 test）、`1246`、`1256`、`2235`、`2300`、`2401`、`2417`、`2426` | doctor | 削除 | bootstrap root / OAuth 共有 / 共通選択の workspace 分岐と同時 |
| `tests/commands/system/test_doctor_apply.py:95` | doctor apply | 削除 | 同上 |
| `tests/commands/system/test_automation_update.py:1153,1180` | automation-update | 削除 | `_channel_roots` の glob と同時 |
| `tests/commands/system/test_skills_sync.py:174,412,1029` | skills sync | 削除 | `_is_workspace_gitignore_target` / `_ops.py` 走査と同時 |
| `tests/commands/system/test_skills_sync_settings.py:40-56,122-140,208-236` | hook 配布 | 削除 | template の hook 2 件と同時。SessionStart を置換する場合は新 hook の test に差し替え |
| `tests/commands/system/test_state_git_migration.py:52-59,97-150`（`test_workspace_*` 5 test） | state Git 移行 | 削除 | `_uses_workspace_gitignore` と同時 |
| `tests/infrastructure/auth/test_oauth_worktree_fallback.py:149-190`（`TestClientSecretsCandidates` の workspace 4 test） | OAuth 解決順 | 削除 | 候補削除と同時 |
| `tests/test_oauth_onboarding_contract.py:150-195` の workspace 候補と `<workspace_root>/auth/` token | docs 契約 | 削除 | 候補列 4 → 3 に縮める。test 自体は残す |
| `tests/commands/test_pipeline_notification_wiring.py:139,186` | cloud runner | 削除 | `hybrid_runner._resolve_channel_dir` の分岐と同時 |
| `tests/test_codex_image_batch.py:134-139,145-150,253-290,313`（`CHANNEL` 経路） | Codex batch | 削除 | `CHANNEL_DIR` 経路の test は残す |
| `tests/repo/test_music_master_loudness_deviation.py:45-50` の `nested-channel` param | 配布 script 起動 | 削除 | `single-channel` 側を残す。`git rev-parse` の挙動は不変 |
| `tests/application/test_hybrid_runner.py:749-751` の `--channel 003ch` 期待値 | cloud runner | 削除 | `run-sandwich.sh:45` の修正と同時 |
| `tests/repo/test_site_repository_contract.py:26` | site 契約 | 削除 | D 表の allowlist と同時 |
| `tests/test_generate_videos_script.py:2419-2421` | 動画生成 | 残す | `channels/focus` は任意の nested path。#3208 の canonical root 解決は単一リポでも有効。docstring の「nested workspace」だけ言い換え |
| `tests/commands/analytics/test_benchmark_competitor_cli.py`、`test_video_analyze_cli.py:787`、`test_fetch_benchmark_comments_cli.py:180`、`tests/test_entrypoints.py:74`、`tests/test_cli_stdio.py:205` | `--competitor` 契約 | 残す | A 表の `CompetitorArgumentParser` と対 |
| `tests/commands/system/test_doctor.py:2470`（`channel-import` orphan skill） | 旧 skill 名 | 残す | v5.5.x で削除された `/channel-import` skill（CHANGELOG.md:1562）で workspace と無関係 |

行数: 削除 22 / 残す 3。

## C. docs

| 対象 | 種別 | 分類 | 根拠 |
|---|---|---|---|
| `docs/adr/0022-multi-channel-workspace.md` | ADR | 残す | 新 ADR から supersede 注記を追加する。ADR は履歴として不変 |
| `docs/channel-workspace-migration.md` | 移行ガイド（公開ページ原本） | **警告** | 非推奨期間中は冒頭に deprecation 告知と `yt-channel-export` 手順への導線を置き、次マイナーで削除。D 表の allowlist / watch paths と連動 |
| `docs/architecture.md:72`（workspace）、`:74`（channel slug） | 用語集 | 削除 | ADR-0022:52「architecture 文書に定義を統合済み」の逆操作 |
| `docs/architecture.md:76`（competitor） | 用語集 | 残す | 定義は維持し、「`--channel` は自チャンネル指定に予約する」の後半だけ削る |
| `docs/architecture.md:294` の allowlist 行 | 公開原本一覧 | 削除 | `site/operator-doc-source.ts` と対 |
| `docs/oauth-setup.md:136-137` | OAuth 解決順 | 削除 | `tests/test_oauth_onboarding_contract.py:189-195` が文言を固定 |
| `docs/release-notes-deployment.md:21,59,72` | Cloudflare Pages 設定表 / watch paths / 受け入れ確認 | 削除 | watch paths 9 → 8、公開 navigation 6 → 5 ページ。同 doc 36-41 のとおり `.github/workflows/site.yml` と Cloudflare Dashboard は自動同期されない |
| `docs/investigations/2026-08-11-3760-workspace-runtime-bottleneck.md` | 調査記録 | 残す | 履歴。`tests/repo/test_site_repository_contract.py:39` の `NONPUBLIC_DOC_PREFIXES` で非公開 |
| `docs/release-notes/v5.6.0.md:35`、`v5.7.0.md:84`、`CHANGELOG.md` | リリース履歴 | 残す | 過去リリースの記述は不変。削除時は `changelog.d/<issue>-<slug>.removed.md` を追加 |
| `docs/architecture/reorganization-followups.md:15`、`docs/architecture/b6-integration-receipt.json:1335,1531` | 整理メモ / receipt | 残す | 履歴。followups の「workspace 診断へ分割」は任意で言い換え |
| `ONBOARDING.md`、`README.md`、`CLAUDE.md`、`AGENTS.md`、`.claude/CLAUDE.template.md` | 契約文書 | 残す | workspace 言及なし。`ONBOARDING.md:3,15,48-109` の `/setup --channel` は setup skill の mode flag、`AGENTS.md:40` の `/workspace/` は Codex Cloud の path |
| `docs/adr/0013-multi-channel-dashboard.md` | ADR | 残す | ADR-0022:52 は「registry は workspace 内パスも指せる定義に更新済み」と書くが、ADR-0013 本文に `channels/<slug>` の記述はない（grep 0 件）。変更不要 |
| `plans/README.md:85` | plan メモ | 残す | `yt-workspace-status` の参照ゼロ指摘。削除後に自然解消 |

行数: 警告 1 / 削除 4 / 残す 8。

## D. site（公開ドキュメントサイト）

| 対象 | 種別 | 分類 | 根拠 |
|---|---|---|---|
| `site/operator-doc-source.ts:26-29` | 公開原本 allowlist | 削除 | `docs/channel-workspace-migration.md` の削除と同時。非推奨期間中は残してページ内で告知する |
| `site/blume.config.ts:60` | sidebar「使う」 | 削除 | 同上 |
| `site/pages/index.astro:77-81` | トップページ「workspace 移行」カード | 削除 | 同上 |
| `site/tests/operator-doc-source.test.mjs:21`、`site/tests/release-notes.test.mjs:36,404-407` | site test | 削除 | 同上 |
| `.github/workflows/site.yml:17,42` | GitHub Actions の paths | 削除 | `docs/release-notes-deployment.md:36-41` |
| Cloudflare Pages の Build watch paths（`docs/release-notes-deployment.md:21`） | 外部設定 | 削除 | Dashboard で手動更新。リポジトリからは変更できない |
| `site/skill-docs/{analytics,setup,audit,wf-new,channel-research}.md` の `/setup --channel` | skill page | 残す | setup skill の mode flag |
| `site/skill-docs/streaming.md:38` | skill page | 残す | Terraform workspace |

行数: 削除 6 / 残す 2。

## E. skills（`.claude/skills`）

| 対象 | 種別 | 分類 | 根拠 |
|---|---|---|---|
| `.claude/skills/music/references/master.md:370` | 文言 | 削除 | 「したがって `channels/<channel>` を CWD にするマルチチャンネル workspace でも…」の後半のみ。`git rev-parse` で同期済み script を解決する挙動は単一リポでも必要（`tests/repo/test_music_master_loudness_deviation.py:45-50` の `single-channel` 側） |
| `.claude/skills/wf-new/references/run-sandwich.sh:45` | cloud runner | 削除 | A 表参照 |
| `.claude/skills/wf-new/references/run-sandwich.sh` の `--workspace`（5-25）、`references/schedule.md:61` | checkout 先ディレクトリ名 | 残す | multi-channel workspace ではなく sandwich runner の一時 checkout 先 |
| `.claude/skills/setup/SKILL.md:20,35,42,82`、`references/channel-mode.md`、`references/setup-mode-guard.py:10,18` の `--channel` | setup skill の mode flag | 残す | `/setup --channel` は新規開設 mode（CHANGELOG.md:404 #3983）。CLI 共通 `--channel` とは無関係 |
| `.claude/skills/setup/references/import-mode.md` | `/setup --import` | 残す | 既存 YouTube チャンネルの config 取り込み（同 file:1-6）。`yt-channel-import` とは無関係 |
| `.claude/skills/music/config.default.yaml:7`、`setup/references/config-template/skills/music.yaml:8-9`、`config-generation-rules.md:115`、`import-mode.md:72`、`regeneration-mode.md:107` の `workspace_name` | Suno UI workspace 名 | 残す | 無関係 |
| `.claude/skills/streaming/SKILL.md:70,92,105`、`references/select_channel.sh` | Terraform workspace / `channel_slug` 変数 | 残す | Vultr instance の label 用（SKILL.md:105）。issue の除外対象 |
| `.claude/skills/thumbnail/references/codex-image-batch.sh:107-115` | channel 解決 | 残す | `channel_dir()` 共通 resolver 経由（CHANGELOG.md:568）。resolver 側の変更に自動追従 |
| `.claude/skills/thumbnail/references/compare.md:44-45`、`analytics/SKILL.md` の `{channel_slug}` | ファイル名 | 残す | `config.meta.channel_short` 由来 |
| `.claude/skills/skill-feedback/SKILL.md:15-16,26` `data/feedback/` | feedback 保存先 | 残す | 下流リポ相対 path。guard の root 許可（#3838、`workspace_guard.py:21,60-67`）は guard と共に消えるが skill 側は不変 |

行数: 削除 2 / 残す 8。

SKILL.md / `config.default.yaml` / references に `yt-channel list`、`yt-channel-import`、`yt-workspace-status`、`yt-workspace-guard`、`CHANNEL=<slug>` の参照はない（repo-wide grep。hit は `.claude/settings.template.json`、`docs/channel-workspace-migration.md`、`docs/adr/0022`、`docs/investigations/...3760...`、`plans/README.md` のみ）。

## deprecation 計画に効く発見

1. **警告点は `find_workspace_root` の 1 箇所でよい。** src 内の全 workspace 分岐（11 module）がこの関数を経由する。`channels/<slug>/` 内 cwd の暗黙解決（`loader.py:198-199`）は `--channel` / `CHANNEL` を通らないため、CLI option 側だけの警告では first-party 7ch の日常運用に届かない。プロセス内 1 回の `DeprecationWarning` + stderr 表示をここに置き、`SessionStart` の `yt-workspace-guard context`（`workspace_guard.py:117-125`）にも 1 行足すのが最小
2. **`yt-workspace-guard` console script は template より長く残す必要がある。** `skills_sync/_settings.py::missing_hooks`（40-67）は template に無い hook を下流 `.claude/settings.json` から prune しない。template から hook を消しても下流には `uv run yt-workspace-guard check ...; exit $?` が残り、console script を消した時点で `uv run` の失敗（exit 2）が Edit/Write を block する。順序は「template から hook 削除 + 下流へ removal 手順を配布 → 1 マイナー後に script 削除」か、`--accept-hooks` に prune 機能を足す
3. **`run-sandwich.sh:45` は単一チャンネル checkout で現行でも壊れている可能性が高い。** `yt-human-tasks --channel <slug>` は共通 option として `select_channel` に渡り、workspace root が無い checkout（`run-sandwich.sh:25`）では `loader.py:154-155` が `ConfigError` を投げる。test は `uv` を stub して引数文字列しか見ない（`tests/application/test_hybrid_runner.py:651-657,749-751`）。deprecation とは独立に `--channel` を外す修正が要る
4. **`yt-codex-canary-notify --channel` は共通 option に先に消費される。** module が `_CHANNEL_OPTION_CONFLICTS` に無いため（`entrypoints.py:12-20`）、console script 経由では `--channel` が argv から除去され、`codex_canary_notify.py:20` の `required=True` を満たせない。test は `main(argv)` を直接呼ぶ（`tests/commands/system/test_codex_canary_notify.py:58`）。共通 option 削除で自然に直るが、それまでの配布 workflow（`codex-canary.yml:48`）は要確認
5. **公開 site の変更は 3 箇所を同時に触る。** `site/operator-doc-source.ts` の allowlist、`.github/workflows/site.yml` の paths、Cloudflare Pages Dashboard の Build watch paths は自動同期されない（`docs/release-notes-deployment.md:36-41`）。公開 navigation は 6 → 5 ページ
6. **契約テストが export / CLI 対応表 / docs 文言を固定している。** `configuration` の export 一覧 2 件、`tests/test_cli_stdio.py:34-35`、`tests/repo/test_cli_harness_gate.py:32-34`、`tests/repo/test_site_repository_contract.py:26`、`tests/test_oauth_onboarding_contract.py:165-195` は削除 PR で同時更新しないと red になる
7. **skills 層はほぼ無傷。** 削除対象は `master.md:370` の一文と `run-sandwich.sh:45` の 1 引数だけ。`/setup --channel` / `/setup --import` は同名でも無関係で、grep の hit に釣られて消してはいけない
8. **`yt-workspace-status` は参照ゼロで単独削除可能。** ただし console script なので他の入口と同じ非推奨期間を通す方が説明しやすい
9. **doctor は `oauth_client_sharing` check の丸ごと削除と `CwdSemantics.BOOTSTRAP_ROOT` の畳み込みで済む。** `_bootstrap_root` は workspace 不在で `channel_dir` を返す（`checks.py:574`）ため、7 check の semantics を `CHANNEL` に揃えても単一リポの挙動は変わらない
10. **`--competitor` は残す。** ADR-0022:40,49 の即時リネームは deprecated alias なしで v5.6.0 に出ており（CHANGELOG.md:1131）、戻すと 2 度目の breaking になる。`CompetitorArgumentParser` の拒否メッセージも当面維持

## 無関係な "workspace"（除外根拠）

| 語 | 場所 | 意味 |
|---|---|---|
| Terraform workspace | `.claude/skills/streaming/*`、`infra/terraform/streaming/README.md`、`checks.py:1310,1357`、`state_reconciliation.py:102`、`tests/repo/streaming/*`、`site/skill-docs/streaming.md:38` | チャンネル別の Terraform state |
| pnpm / Vite workspace | `site/pnpm-workspace.yaml`、`extensions/*/pnpm-workspace.yaml`、`docs/adr/0006`、`0013`、`0021`、`0023`、`docs/development.md:106,266`、`tests/repo/test_extension_package_manager_contract.py`、`test_dashboard_architecture_contract.py:41` | Node package の workspace |
| Suno workspace | `workspace_name` 群（E 表） | Suno UI の作業領域名 |
| Codex sandbox | `codex exec --sandbox workspace-write`（thumbnail references、`docs/skill-design/thumbnail-codex-json-first-experiment.md`） | Codex CLI の sandbox mode |
| Codex Cloud path | `AGENTS.md:40` `/workspace/youtube-automation` | Cloud task の checkout path |
| sandwich checkout | `run-sandwich.sh --workspace`、`schedule.md:61`、`youtube-automation.yml:56` | cloud runner の一時 checkout 先 |
| test helper 名 | `tests/commands/system/test_setup_chain_state.py::_commit_workspace` | git repo を commit する helper。workspace 構造は作らない |
| cmux workspace | global skill `cmux` / `cmux-workspace`（本リポの `.claude/skills` には存在しない） | ターミナル multiplexer |
