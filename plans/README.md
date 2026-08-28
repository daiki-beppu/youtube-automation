# Implementation Plans

このリポジトリの規約: 作業は必ず worktree 上で行う（`$REPO_ROOT/.claude/worktrees/<slug>/`）。`src/youtube_automation/` / `.claude/skills/` / `.claude/CLAUDE.template.md` / `pyproject.toml` を触るプランは `CHANGELOG.md` の `[Unreleased]` 追記が必須（CI ゲート。lefthook は issue #2534 で廃止済み — ローカル git hook は無い）。docs / tests のみの変更はゲート対象外。

Status values: TODO | IN PROGRESS | DONE | BLOCKED (with one-line reason) | REJECTED (with one-line rationale)

## 第 7 回監査（CI 過剰性の監査、2026-08-23、基準 commit `9996de7b`）

フォーカス指定 /improve（「CI が過剰すぎないか監査、最適化したい」）。advisor が全 workflow 9 本 + CI スクリプト + contract test 群を実読し、`gh run list` 直近 200 run の実測（回数・所要・conclusion 内訳）で裏取り。
総評: **コア CI（ci.yml）は過剰ではなく最適化済み**（path 分類 + import グラフ affected-test 選定で PR CI 実測 60〜70 秒、main push フル実行は直近 15 run 中 3 failure を実際に捕捉する現役の安全網）。過剰は後付けの AI ゲート層に集中 — このリポジトリは public で runner 分は無料のため、実コストは Claude クォータ消費・マージ待ち latency・ノイズの 3 つ。(1) stacked PR の rebase 連鎖で Code review が 1 PR あたり 5〜9 run（diff 不変でも sonnet 全再レビュー）、(2) CI autofix が info-only 指摘でも Opus を起動しほぼ全 PR でパイプラインが実質 2 周、(3) 日次 Skill E2E eval は認証不備で 10 日以上空回り → secret 追加後の初実走（run 32591953739）が既定 devShell に無い pnpm を呼び `exec: pnpm: not found` で即死。3 件とも plan 化（ユーザー選択: 全件）。

### Execution order & status

| Plan | Title | Priority | Effort | Depends on | Issue | PR | Status |
|------|-------|----------|--------|------------|-------|-----|--------|
| 034 | Code review を patch-id で重複排除し rebase-only push の sonnet 再レビューを skip | P1 | M | — | [#4601](https://github.com/daiki-beppu/youtube-automation/issues/4601) | [#4662](https://github.com/daiki-beppu/youtube-automation/pull/4662) | DONE |
| 035 | CI autofix の発火しきい値を critical+warning に上げ info-only での Opus 起動を止める | P1 | S | — | [#4602](https://github.com/daiki-beppu/youtube-automation/issues/4602) | — | DONE |
| 036 | Skill E2E eval の pnpm devShell 不整合を修理し日次 → 週次化 | P2 | S | — | [#4603](https://github.com/daiki-beppu/youtube-automation/issues/4603) | — | TODO |

### Dependency notes

- 034 / 035 / 036 は触るファイルが完全非重複で並列実行可。いずれも `.github/workflows/*.yml` + 対応する `tests/repo/test_*_workflow.py` の 2 ファイルペアを更新する（CI 構造は contract test で機械担保されているため、workflow 単独の変更は必ず test が赤くなる — 各 plan に更新すべき assertion を明記済み）
- いずれも CHANGELOG ゲート対象パス外のため changelog fragment 不要
- 034 と 035 は相互作用がある（レビューコメントのメタ行が autofix の severity パーサに誤検出されない語彙 `crit=` を使う契約）— 034 の Step 1 に明記済み

### Findings considered and rejected（再監査不要）

- **lint / test job の setup 重複（checkout + nix + uv sync ×2）**: 並列実行が latency を稼いでおり、public repo で runner 分は無料。統合すると PR CI が遅くなるだけで益なし
- **非 Python 変更時に lint / test が echo だけの runner を起動**: required check を安定させる定石パターン。1 job 数秒
- **`fetch-depth: 0` の多用**: .git は 67MB・3,321 commits で full clone は数秒差。削る価値なし
- **main push CI のキュー滞留懸念**: 実測で全 run の startedAt−createdAt = 0 秒。concurrency の pending 置き換えにより中間 run は自動 cancel されており設計どおり
- **Extensions / Dashboard / Audio Studio / site workflow の負荷**: path フィルタが効いており直近 200 run にほぼ出現しない（Dashboard 5 / site 3 / Extensions 0）。対処不要
- **main push CI のフルスイート実行を選択実行化する案**: 却下。PR 側の affected-test 選定の安全網であり、直近 15 run 中 3 failure を実際に捕捉している

### 監査で plan 化を見送った残課題

- **main の CI failure の通知経路追加**: 不要と裁定（ユーザー判断 2026-08-23）— GitHub の失敗 workflow メール通知で捕捉できるため、Discord webhook / issue 自動起票いずれも追加しない
- **autofix 適用後の効果測定**（035 の Maintenance notes に記載）— 1〜2 週間後に `gh run list --workflow "CI autofix"` の 70 秒超 run 数で半減を確認し、不足なら critical-only へ再調整

## 第 6 回監査（未参照ファイル・不要ファイル特化、2026-08-22、基準 commit `0030e636`）

フォーカス指定 /improve（「いらないファイル、参照されていないファイルがないか監査」）。並列 4 subagent（Python 本体 / skills・.takt / docs・ルート / TypeScript 表示層）→ 全 findings を advisor が実読 vet。Python 側は AST import graph（450 モジュール全数、entrypoints の文字列 dispatch 込み）で機械的に到達可能性を判定。
総評: **完全孤児ファイルは少数**（.takt / site / .github scripts / evals / dashboard / audio-studio はゼロ）だが、**「契約テストだけが延命させている dead code」が主要パターン**として広範に存在する（video_validator クラスタ、CodexGenerator、B3/B4 facade、skill references の test-only 契約スクリプト群、b6 receipt の 47 doc パス存在ロック）。非対話実行のため、レバレッジ上位 5 件を既定選択として plan 化した（028〜032）。

### Execution order & status

| Plan | Title | Priority | Effort | Depends on | Issue | PR | Status |
|------|-------|----------|--------|------------|-------|-----|--------|
| 033 | changelog fragment 基盤（`changelog.d/` + `yt-changelog-compile`）を導入し CHANGELOG の並列マージ conflict を解消 | P1 | M | — | [#4483](https://github.com/daiki-beppu/youtube-automation/issues/4483) | — | DONE |
| 028 | music skill 内の stale fork `generate_suno_prompts.py`（19KB・95 行乖離・wheel 配布に混入）を削除 | P1 | S | 033 (soft) | [#4460](https://github.com/daiki-beppu/youtube-automation/issues/4460) | — | DONE |
| 029 | 到達不能な video_validator クラスタ（446 行 + テスト 278 行）と B3 facade `domains/media/{video,audio}.py` を削除 | P1 | S | 033 (soft) | [#4461](https://github.com/daiki-beppu/youtube-automation/issues/4461) | — | DONE |
| 030 | 構築経路が封鎖済みの CodexGenerator（未監査自動返信の footgun）を削除 | P1 | S | 033 (soft) | [#4462](https://github.com/daiki-beppu/youtube-automation/issues/4462) | — | DONE |
| 031 | suno-helper の廃止済み popup 残骸（#892 の「後続 PR」約 2000 PR 分未着手）を物理削除し README を実態に合わせる | P1 | S | 033 (soft) | [#4463](https://github.com/daiki-beppu/youtube-automation/issues/4463) | — | TODO |
| 032 | 参照ゼロの小粒残骸一括掃除（legacy image_provider shim ×5 / 廃止スキーマ fixture / bench_real_apis / .prettierignore ×2 / fallow baseline 亡霊 / commit 済み .lock） | P2 | S | 033 (soft) | [#4464](https://github.com/daiki-beppu/youtube-automation/issues/4464) | — | TODO |

### Dependency notes

- **033 はマージ済み**（オペレーター決定 2026-08-22 の「033 を最初に」を完了）。028〜032 は CHANGELOG.md 直接編集の代わりに `changelog.d/<issue>-<slug>.<type>.md` の fragment を追加する（各 plan の CHANGELOG step に条件分岐を記載済み）ため、**5 本が完全並列でマージ可能**
- 033 の site（リリースノート静的サイト）/ 下流 `/automation --update` への影響はゼロを確認済み — site は `docs/release-notes/*.md` のみを読み（`git grep CHANGELOG site/` → 0 件）、release notes の生成契約はリリース済み version section を入力とし `[Unreleased]` を混ぜない（release-notes-authoring.md:9）。下流は GitHub Release body → リリース済み section fallback。fragment 化が変えるのは `[Unreleased]` への書き溜め経路だけ
- 028〜032 は触るファイルが完全に非重複。並列実行可
- 031 / 032 は extensions 側で `pnpm install` が必要（nix devShell `.#extensions`）

### Findings considered and rejected（再監査不要）

- **shadcn skill の `agents/openai.yml` / `evals.json` / `assets/*.png` が未参照**: by design。upstream verbatim vendoring（`skills-lock.json` の computedHash + `test_official_shadcn_skill_is_copied_without_symlinks` が保護）で、dev-only-skills のため wheel にも載らない
- **`extensions/shared/origin.ts` の production importer ゼロ**: by design。`collection_serve.py::is_origin_allowed` の契約パリティミラーで、ファイル自身のコメントが「CORS はサーバー担保のためクライアント消費者は存在し得ない」と明記済み
- **`src/youtube_automation/{dashboard_dist,audio_studio_dist}` の commit 済みビルド成果物**: by design。sdist force-include のための追跡で、CI（dashboard.yml / audio-studio.yml）が `pnpm build` 後の `git diff --exit-code` で鮮度を機械担保。基準 commit 時点で同期確認済み
- **extensions の oxlint / ultracite devDependencies が 3 重定義**: 正当。各 helper のコピーは PATH 上のバイナリ提供、`extensions/package.json` は `oxlint.config.ts` の resolve 用（package.json の description に明記あり）
- **test 専用 export ~170 シンボル（shared/dom.ts の SELECTORS 等）**: house style。セレクタ定数は変更検知契約（distrokid-helper README 161-169 行に明文化）
- **dashboard / audio-studio 間の shadcn 5 ファイル byte 一致重複**: 統合は ADR-0013 / ADR-0028 の shared-ui import 禁止に抵触。~200 行の生成 scaffolding に新共有パッケージ + ADR 改訂は見合わない
- **`.takt/` / `site/` / `.github/scripts/` / `evals/` の孤児疑い**: 全ファイル到達可能を確認（workflow 7 / steps 11 / facets 42 全参照、site は operatorDocMap と blume.config で全消費、.github scripts 6 本全 CI 接続、evals 12 ファイル全使用）
- **`skills-lock.json` に first-party skill が無い**: by design。外部 vendored skill（shadcn）専用の lock で、契約テストが `set(lock["skills"]) == {"shadcn"}` を assert 済み
- **`examples/channel_config.example/` ほか examples 14 ファイル**: 全て README / ONBOARDING / docs / tests から参照あり。孤児は minimax-music-engine.example.json のみ（下記・未選択）

### 監査で plan 化を見送った残課題（ユーザー判断待ち）

**削除系（判断が要るもの）**:
- **b6 receipt の存在ロック解除 + audits raw/ 7 ファイル削除**（M、MED リスク）— `test_b6_integration_contract.py:287-290` が receipt の全 `exact_new_owner`（doc 47 パス含む）の存在を恒久 assert しており、docs/ の約 45% が削除不能。双子の `skills-operational-risk-audit/raw` は削除済み（同テスト :452 で不在 assert）なのに `skills-generalization-consistency/raw/`（中間 scratch 1,736 行）だけ残存。ロック解除が今後の docs 掃除全部の前提
- **`docs/release-skill-update-253.md` 削除**（S）— 別リポジトリ（dotfiles）の skill 本文の手渡しコピー。参照ゼロ。dotfiles 側の反映確認後に削除
- **`.codex/takt-open-issues-execution-notes.md`**（S、要 issue 確認）— 2026-07-14 の作業メモ（マシン固有絶対パス入り）が `test_b6_integration_contract.py:113` の legacy-27 として CI 固定されている。merge disposition の完了確認後に削除
- **`examples/minimax-music-engine.example.json`**（S）— 参照ゼロ。削除か README/ONBOARDING への掲載 + スキーマ検証テスト追加かの二択
- **references/ の vestigial symlink 5 本**（M、MED リスク）— `get_channel_status.py`（配布テンプレが「廃止」と明言）/ `fetch_benchmark_comments.py` / `finalize_master.py` / `compare_thumbnails.py` / `setup/generate_image.py`。契約テスト（`test_analytics_consolidation.py:91` 等）が存在を凍結しており、downstream 互換 shim か否かの意図確認が先
- **`bench/` ディレクトリ全体の去就**（S〜M）— perf #131 時限計測フェーズ産・CI 非接続。`bench_strategic_analytics.py` は `time.sleep` を計測しており実コードを測っていない。032 は孤児 1 本のみ削除、残りは「削除 or CI smoke 接続」の判断待ち
- **`domains/uploads/descriptions_md.py`**（S-M、MED リスク）— 現役 `load_description_document` と重複する第 2 実装。B4 契約テストが「public owner」と assert しており契約変更を伴う
- **4 CLI（yt-ad-coverage / yt-document-review / yt-media-acceptance / yt-workspace-status）**— skill / doc / workflow から参照ゼロ。power-user 用か忘れ物かの判断待ち（keeper は SKILL.md へ配線、残りは削除）
- **legacy_utils の未契約 shim 3 本（cli_arguments / genai_client / setup_directory_contract）**— downstream 契約リスト外。`profile` / `worktree` の削除前例に倣い「契約に載せる or removed へ」の判断待ち

**修正系（stale 参照・誤名）**:
- **ADR 7 本の stale Status 行**（S）— 0002〜0006 / 0015 / 0017 / 0018 が「`feat/ts-rewrite` で進行中」のまま（ブランチも packages/ も消滅、ADR-0021 が supersede）。`superseded by ADR-0021` へ status 修正（削除はしない）
- **`docs/strategy/growth-gap-analysis.md:19` の消滅パス `utils/reporting_api.py`**（S）— reorganization の rename 漏れ 1 箇所
- **popup-compatibility テスト 3 本の誤名 rename**（S）— 計 6,021 行が overlay UI のテストなのに popup 名。suno 側 4,495 行の god-file 分割は別途 L
- **`docs/roadmap.html`**（S）— 公開向け移行アナウンスが site の配信経路（operatorDocMap / site.yml paths）に未接続。publish or delete の二択

**構造系（再発防止・仕組み）**:
- **docs/ index（`docs/README.md`）新設**（S）— 106 doc 中 41 本がどこからも到達不能（現行 wf アーキテクチャの設計記録 `2026-08-10-wf-skills-takt-migration.md` 含む）。index + 「全 doc が index に載る」契約テストで将来の orphan 化を構造的に防げる
- **fallow audit の distrokid / community CI ジョブ展開**（S、初回 triage 必要）— dead code gate が suno の PR 時のみ実行。TS 側残骸（031 の popup 等）が生き延びた根本原因
- **`yt-skills lint` に未参照 references ファイル検知が無い**— skills 側残骸（028 の fork 等）が蓄積する根本原因。lint への検査追加は S-M
- **`infra/terraform/r2/` の配線**（M）— ADR-0024 のデータプレーンを provision する module が doc / skill / CI から完全孤立。同梱の `r2.tftest.hcl` は一度も実行されていない。`test_terraform_bootstrap.py` 型の parse 契約 + architecture.md からのリンクを推奨
- **shared-ui barrel の未使用 export ~10 本 trim**（S）— ScrollBar / SelectLabel / fieldVariants / AlertDialogPortal 等は全 extension で参照ゼロ、`Label` は「export があるから存在するテスト」のみが消費
- **skills の test-only 契約スクリプト群の配線 or 降格**（S〜M）— `validate_experiments.py`（参照完全ゼロ。双子の validate_insights は 6 箇所でゲート）/ `master-audio-review.md`（どの SKILL.md からも不到達）/ `freshness_action.py` / `persona_flow.py` / `market_research_contract.py`（いずれもテストのみが実行、skill 本文は不参照 — CI は通るが実行時に契約が効いていない）
- **overlay bootstrap の 3 拡張重複統合**（M）— 5 ファミリ × 3 拡張がブランド定数以外同一で、import パス表記（`wxt/utils/storage` vs `@wxt-dev/storage`）の乖離が既に発生
- **icon-assets.test.ts 3 本 byte 一致 / overlay.css 2 本 byte 一致の共通化**（S）
- **extensions/{lint,compile}-bench.sh の docs/investigations/scripts/ への移設**（S）— 完了済み調査の再現スクリプトがツールチェーン最前列に残置

**ローカル残骸（repo 外・オペレーター向けメモ、plan 不要）**: 追跡外で ignore されていないファイルはゼロ（作業ツリー健全）。gitignore/exclude 済みのローカル成果物として `utils/`（空ディレクトリ）、`dist/`、`reports/`（256KB）、`.tmp/`（7.3MB）、`execution-notes.md`、`issue-{2050,2053,2166}-implementation-spec.md` が残っており、不要なら手動削除してよい

## 第 5 回監査（セキュリティ専門監査、2026-07-21、基準 commit `37b362ce`）

セキュリティ集中監査（フォーカス指定 /improve）。並列 4 subagent（シークレット/認証 / インジェクション・パス / ネットワーク・サーバー / Chrome 拡張・配布）→ 全 findings を advisor が実読 vet。
総評: **HIGH / MEDIUM 脆弱性ゼロ**。shell=True / eval / unsafe yaml / curl|bash ゼロ、全 subprocess が argv 形式、zip-slip・path traversal・CORS・CSRF・token 0o600・redact・webhook 許可リストいずれも防御済み。第 4 回以降の新サーフェス（live-chat 自動返信 daemon / streaming VPS）も、プロンプトインジェクション対策（`<viewer_input>` ラップ + stdin 渡し + `--sandbox read-only` + 出力監査 + 3 段レート制限）と systemd hardening を実装済みで健全。残ったのは LOW の hardening 3 件のみ。

### Execution order & status

| Plan | Title | Priority | Effort | Depends on | Issue | PR | Status |
|------|-------|----------|--------|------------|-------|-----|--------|
| 025 | 1Password フォールバックの client_secrets を tempfile 経由から in-memory 化（SIGKILL 残留解消） | P2 | M | — | [#2394](https://github.com/daiki-beppu/youtube-automation/issues/2394) | [#2410](https://github.com/daiki-beppu/youtube-automation/pull/2410) | DONE |
| 026 | streaming VPS の stream key / webhook staging を素の /tmp から 0700 ディレクトリへ | P3 | S | — | [#2395](https://github.com/daiki-beppu/youtube-automation/issues/2395) | [#2411](https://github.com/daiki-beppu/youtube-automation/pull/2411) | DONE |
| 027 | open / ffmpeg へ渡すパス引数の絶対パス化（defense-in-depth） | P3 | S | — | [#2396](https://github.com/daiki-beppu/youtube-automation/issues/2396) | [#2412](https://github.com/daiki-beppu/youtube-automation/pull/2412) | DONE |

### Dependency notes

- 025〜027 は完全に独立（触るファイル非重複）。並列実行可
- 026 の `terraform apply` は実 VPS の再 provisioning を伴うためオペレーターが別途実施（プランは fmt / validate / pytest まで）

### Findings considered and rejected（再監査不要）

- **CORS 既定で任意の Chrome 拡張が collection-serve の read ルートを読める**（collection_serve.py:666-668）: by design（#896 コメントに意図明記）。第 1 回監査で同系 finding を裁定済み — `--allow-origin` lock が存在し、mutating 側は extension lock + token 必須（Plan 001）。露出は未公開プロンプト・下書きのみで受容
- **suno.com ページから拡張 bridge メッセージ（MAIN→ISOLATED postMessage）を偽装可能**: MAIN world の構造的制約で完全防御は不可能。悪用には suno.com 自体の侵害が前提、影響も自動化進捗状態の撹乱のみ。受容
- **SSH ホスト秘密鍵の cloud-init user-data 埋め込み**（infra/terraform/streaming/main.tf:66-72）: host-key pinning（provisioner の `host_key` 検証）のための意図的トレードオフ。鍵は当該サーバー自身の identity 鍵で、state / tfvars は gitignore 済み。受容
- **skill 配布（wheel → yt-skills sync）に内容署名なし**: 脆弱性ではなく trust model（wheel が trust root）。sync 自体は traversal 安全を確認済み。メンテナンスモードのリポジトリに L 工数の署名基盤は見合わない
- **`--` セパレータによる argv hardening 提案**（subagent 報告）: 手法が誤り。**ffmpeg は `--` end-of-options 非対応**。正しい対策（絶対パス化）に修正して Plan 027 とした

### クリーン確認済み領域（次回セキュリティ監査の短縮用）

- secrets.py（env → op read → ConfigError、値は stdin/ヘッダーのみ、argv 露出なし）/ oauth_handler（0o600 + `_redact`、READONLY_SCOPES 分離 #1699）/ fetch_stream_key（TTY 検知 + `::add-mask::`）/ notification（HTTPS + Discord ホスト許可リスト）
- suno ZIP 展開（zip-slip + entry 数 + サイズ上限）/ CollectionPaths・thumbnail_archive の `relative_to` 境界 / channel slug regex 検証
- collection_serve（localhost bind、mutating は extension lock + X-Serve-Token、body 上限、path traversal 防御）/ live_chat（上記総評参照）
- 拡張 manifest 最小権限（`<all_urls>` なし、CSP 緩和なし、innerHTML/eval ゼロ、background は sender 由来 tab のみ操作）/ pnpm-lock 全て registry.npmjs.org + integrity / lefthook・flake に remote fetch なし / コミット済みシークレットなし

## 第 4 回監査（Python コア本体の一般監査、2026-07-09、基準 commit `5394c378`）

初の `src/youtube_automation/`（~46K 行）本体監査。並列 4 subagent（正確性+セキュリティ / パフォ+依存 / テスト+負債 / DX+docs+方向性）→ 全 findings を advisor が実読 vet。
総評: subprocess・パス traversal・OAuth・シークレット・コメント冪等性は防御済み、クリティカルパスは 4,976 テストで実挙動検証済みと**健全**。実弾はアップロード経路のエラー処理・dead code・ツールチェーンのほつれに集中。

### Execution order & status

| Plan | Title | Priority | Effort | Depends on | Issue | PR | Status |
|------|-------|----------|--------|------------|-------|-----|--------|
| 020 | アップロード経路の堅牢化（tracking アトミック化 / QuotaExhaustedError 非終端化 / サムネ temp リーク） | P1 | S-M | — | — | [#1786](https://github.com/daiki-beppu/youtube-automation/pull/1786) | DONE（main マージ済み `34935fc7`） |
| 021 | bulk_update_desc の snippet 更新を read-modify-write 化（defaultAudioLanguage 消失防止） | P1 | S | — | — | [#1789](https://github.com/daiki-beppu/youtube-automation/pull/1789) | DONE（独立修正済み `fbde9a4d`） |
| 022 | analytics collect の uploads playlist 二重取得解消 + video_listing の例外/TZ 修正 | P2 | S | — | — | [#1788](https://github.com/daiki-beppu/youtube-automation/pull/1788) | DONE（main マージ済み `373f7409`） |
| 023 | dead analytics/report クラスタ 3 ファイル（1,016 行）削除 | P2 | S | — | — | [#1791](https://github.com/daiki-beppu/youtube-automation/pull/1791) | DONE（main マージ済み `d9de12f3`） |
| 024 | ツールチェーン整備（dev 依存一本化 / ruff B・RUF / seaborn 削除 / Any-gate CI / CJK フォント回帰テスト） | P2 | M | — | — | [#1790](https://github.com/daiki-beppu/youtube-automation/pull/1790) | DONE（main マージ済み `717a92b2`） |

### Dependency notes

- 020〜024 すべて main マージ済み。第 4 回監査の全プラン完了

### Findings considered and rejected（再監査不要）

- **`ci.yml` の `parallel:` ステップが不正構文疑い**: 誤り。現行 GitHub Actions の正規のステップグループ構文で、run 29001443387 で Ruff 両ステップの実行成功を確認済み
- **`collection_serve` の同時 POST `/downloaded` race**: 単一オペレーター + 単一拡張の運用モデルでは実発生確率ほぼゼロ（第 1 回監査の `write_distrokid_release` TOCTOU 棄却と同判断）。多重化するなら per-cid lock を検討
- **mypy/pyright 導入**: tayk（TS 後継、ADR-0021）移行済みのメンテナンスモードでは L+ 工数の回収期間が無い。「導入しない」を本行で明文化とする。型規律は any-usage-gate（024 で CI 化）が代替
- **`QuotaExceededError` が dormant という subagent 報告**: 二重に誤り。実名は `QuotaExhaustedError`（exceptions.py:45）で、upload_core.py:205 から raise されテスト済み。問題は「呼び出し側が握りつぶす」ことで、020 が修正する
- **`schedule.py` vs `publish_schedule.py` の重複疑い / `profile.py` 等の dead 疑い / comments の generator 3 実装**: いずれも誤検知（責務が別 / 現役 importer あり / 意図した strategy パターン）
- **CLI 起動時の pandas/matplotlib 重量 import**: 誤検知。`cli_entrypoints.py` は `import_module` の遅延 dispatcher で、重量 import は plotting 系コマンドに閉じている
- **retention の per-video Analytics クエリ**: audience retention curve にバッチ endpoint が無い API 制約。by design
- **GitHub Actions の Node 20 deprecation 注記**: 現状は自動 fallback で実害なし。actions メジャー bump は任意のついで作業

### 監査で plan 化を見送った残課題

- **doctor.py（2,650 行・61 コミット churn）の god module 分割**（L、テストは厚く安全）— TTP/branding 業務ロジックの `utils/` 移設 + GCP チェックのサブモジュール化。ユーザー未選択
- **中粒の構造整理**（M）— utils 83 モジュールの flat 化解消（suno_downloaded_* 8 分片の統合、`utils/comments/`・`configuration/` パッケージ方式に倣う）/ metadata_generator.py（1,271 行）の 4 責務分割 / doc-contract 系テスト ~25 本への pytest marker 付与と behavioral-only fast lane。ユーザー未選択
- **PERF-02: サブ分析間の `_get_video_details` / `dimensions=video` クエリ共有**（M、collect 1 回のクォータをさらに削減）— 022 の続編として設計余地
- **`strategic_analytics.py` の `comprehensive` モード**（呼び出し元ゼロ、per-video N+1 内蔵）— 使うか消すかの判断待ち。023 のスコープ外として温存
- **japanize-matplotlib の置換移行**（S-M、MED リスク）— 024 は glyph 回帰テストの設置まで。テストが fail したら `font_manager.addfont()` 直接登録へ移行
- **Direction 3 件（ユーザー未選択、spike/design プラン候補）**: (1) Data API クォータ可観測性 — cost_tracker 相当の units 台帳 + pre-flight 見積（無人運転を止める最有力因子に事前可視性）。(2) `yt-unpublish` — 公開 3 entrypoint に対する逆操作の不在。`videos().update` の既存配管で `privacyStatus=private` 一括復帰、dry-run→confirm 必須。(3) cost_tracker の `estimated_cost_usd` null 固定（Issue #132 の意図的決定）の再訪 — 単価表 1 枚でドル換算が完成する

## 第 3 回監査（takt リジェクト多発の原因調査、2026-07-06、基準 commit `bf68c73d` / dotfiles `9a030ff`）

調査テーマ: review-takt-default の REJECT 多発（`.takt/runs/` 239 run・指摘 676 件の全数解析）。
主要結果 — (1) REJECT 率 91%（171/187）は 7 観点ゼロトレランス全員一致ゲートの数理的帰結
（各観点の個別 REJECT 率 27〜41% → 通過率 ≈9%）で品質シグナルではない。(2) fix → 再レビュー
126 ペアの 91% が再 REJECT だが、前回指摘未解消（persists）は 14% のみで、77% は「同じファイル
への新規指摘」＝ fix がレビュアーの走査範囲（累積差分全体）を自己監査していない。(3) issue 品質が
効く指摘は全体の ~11%、CI ツーリング不足は ~3% のみ。(4) 上流対策（#1508 チェックリスト・
強化 plan 指示）は 2026-07-03〜05 投入でクリーンな効果測定サンプル 0 件。

**注意: 018 / 019 の変更対象は dotfiles リポジトリ（`~/01-dev/dotfiles/config/.claude/skills/`）**。
プランファイルだけが本リポジトリにある。

### Execution order & status

| Plan | Title | Priority | Effort | Depends on | Issue | PR | Status |
|------|-------|----------|--------|------------|-------|-----|--------|
| 019 | takt-review の fix を累積差分の自己監査 + finding_id 解消根拠表つきに再設計 | P1 | M | — | — | — | DONE（dotfiles main マージ済み `71d453f`） |
| 018 | issue / to-issues / takt-issue テンプレに「兄弟入口・貫通先」列挙を必須化 | P2 | S | — | — | — | DONE（dotfiles main マージ済み `3dbd88e`） |

### Findings considered and rejected（再監査不要）

- **「issue の内容が悪いから REJECT される」説**: 主因ではない。要求解釈系の指摘は 676 件中 75 件（11%）。issue 本文の長さ・テンプレ準拠と REJECT 回数に相関なし（2,105 字・影響ファイル記載ありの #1141 でも 14 REJECT）。
- **「CI / lint ツーリング不足」説**: 機械捕捉可能クラス（未使用コード・依存脆弱性・型）は指摘の ~3%。knip / oxlint / tests は機能している。
- **「/issue・/to-issues に受入条件・スコープ外が無い」**: 2026-07-05 のスキル改訂で導入済み（takt-issue の preflight 正規化も同日導入済み）。残ギャップは「兄弟入口・貫通先」の観点のみ → Plan 018。
- **takt 本体（builtin review policy のゼロトレランス設計・7 観点一致）の変更**: ユーザー前提により対象外（takt は据え置き）。

### 監査で plan 化を見送った残課題

- **効果測定基盤**（`.takt/runs` から verdict / persists / High 件数 / 欠陥クラス別の自動集計を常設し、#1508 チェックリストと本監査 018/019 の効果を 20〜30 run で判定）— 提案済み・ユーザー未選択
- **自己申告ゲートの機械化**（変更行カバレッジゲート、config キーの定義⇔loader⇔使用の貫通チェック CLI）— 指摘最頻 2 クラスの CI 昇格。効果測定の結果を見てから判断
- **運用指標の変更**（REJECT 数ではなく persists 数 + High 件数を見る）— ドキュメント化のみの小変更だが docs/takt-operations.md の改訂はユーザー確認待ち

## 第 2 回監査（スキル全般の Sonnet-safe 化、2026-07-05、基準 commit `8deb3f02`）

監査テーマ: `.claude/skills/` 全 47 スキルを「Sonnet 級のより弱いモデルが実行しても作者の期待とズレなく解釈できるか」の観点で監査（TRIGGER / AMBIG / DRIFT / ROBUST の 4 ディメンション、並列 4 subagent + 全 findings を advisor が実読 vet）。42 件の生 findings から 12 件を有効と判定し、規約 1 本 + 個別修正 12 本に plan 化した。

### Execution order & status

| Plan | Title | Priority | Effort | Depends on | Issue | PR | Status |
|------|-------|----------|--------|------------|-------|-----|--------|
| 005 | Sonnet-safe スキル記述規約を docs/skill-design/ に制定 | P1 | M | — | [#1512](https://github.com/daiki-beppu/youtube-automation/issues/1512) | [#1529](https://github.com/daiki-beppu/youtube-automation/pull/1529) | DONE |
| 006 | comments-reply / pinned-comment に dry-run→apply 承認ゲート追加 | P1 | S | 005 (soft) | [#1513](https://github.com/daiki-beppu/youtube-automation/issues/1513) | [#1537](https://github.com/daiki-beppu/youtube-automation/pull/1537) | DONE |
| 007 | analytics の CTR 解釈記述をコード実態（百分率 float）に修正 | P1 | S | — | [#1514](https://github.com/daiki-beppu/youtube-automation/issues/1514) | [#1536](https://github.com/daiki-beppu/youtube-automation/pull/1536) | DONE |
| 008 | 兄弟スキル間の frontmatter 矛盾・発動キーワード衝突を解消 | P1 | S | 005 (soft) | [#1515](https://github.com/daiki-beppu/youtube-automation/issues/1515) | [#1538](https://github.com/daiki-beppu/youtube-automation/pull/1538) | DONE |
| 009 | 工程チェーンの前提条件ガードを 4 スキルに追加 | P2 | S-M | 005 (soft) | [#1516](https://github.com/daiki-beppu/youtube-automation/issues/1516) | [#1551](https://github.com/daiki-beppu/youtube-automation/pull/1551) | DONE |
| 010 | channel-new のペルソナ生成前に TTP 中間ゲート追加 | P2 | S | — | [#1517](https://github.com/daiki-beppu/youtube-automation/issues/1517) | [#1533](https://github.com/daiki-beppu/youtube-automation/pull/1533) | DONE |
| 011 | live-clean の削除承認を明示的 2 択 + 取消不可警告に固定 | P2 | S | 005 (soft) | [#1518](https://github.com/daiki-beppu/youtube-automation/issues/1518) | [#1541](https://github.com/daiki-beppu/youtube-automation/pull/1541) | DONE |
| 012 | stale/freshness 判定を freshness-rules.md へ単一ソース化 | P2 | S | — | [#1519](https://github.com/daiki-beppu/youtube-automation/issues/1519) | [#1546](https://github.com/daiki-beppu/youtube-automation/pull/1546) | DONE |
| 013 | suno のモード判定を decision tree 化 | P2 | S | — | [#1520](https://github.com/daiki-beppu/youtube-automation/issues/1520) | [#1543](https://github.com/daiki-beppu/youtube-automation/pull/1543) | DONE |
| 014 | suno-helper → masterup の部分ダウンロード検知手順を明文化 | P2 | S | — | [#1521](https://github.com/daiki-beppu/youtube-automation/issues/1521) | [#1549](https://github.com/daiki-beppu/youtube-automation/pull/1549) | DONE |
| 015 | postmortem の閾値調整ルーブリック追加 | P3 | S | — | [#1522](https://github.com/daiki-beppu/youtube-automation/issues/1522) | [#1542](https://github.com/daiki-beppu/youtube-automation/pull/1542) | DONE |
| 016 | setup の project ID truncate 手順を一義化 | P3 | S | — | [#1523](https://github.com/daiki-beppu/youtube-automation/issues/1523) | [#1545](https://github.com/daiki-beppu/youtube-automation/pull/1545) | DONE |
| 017 | thumbnail の外部リポジトリ参照をオペレーター向け注記に隔離 | P3 | S | — | [#1524](https://github.com/daiki-beppu/youtube-automation/issues/1524) | [#1544](https://github.com/daiki-beppu/youtube-automation/pull/1544) | DONE |

全 13 件、2026-07-05〜07-06 に main へマージ済み（スポットチェックで #1529 / #1537 / #1551 の diff を実読し、要件との整合を確認済み）。

### 既存 issue との関係

- **#1489〜#1493「[skill-quality] AI 可読性改善」（親 #1487）**: 同テーマの網羅スイープ。両立方針 — 確定修正（本監査の 13 issue）を先行させ、スイープ側は適用済み修正を尊重する（各 issue にコメント済み、2026-07-05）
- **#1499（channel-new ヒアリング TTP 特化）**: #1517 と同ファイルを触るため順序注意（#1517 の issue 本文に明記）

### Dependency notes

- **005 を最初に**実行することを推奨。006 / 008 / 009 / 011 は 005 の規約（承認ゲート標準型・発動条件相互排他・前提ガード標準型）の実装例になる。ただし各 plan は自己完結しており 005 未完了でも実行可能（soft dependency）。
- 006〜017 は互いに独立（触るファイルが重複しない）。並列実行可。例外: 012 と 009 はどちらも wf 系に近いが対象ファイルは非重複。
- `.claude/skills/` を触る plan（006〜017 すべて）は CHANGELOG 追記必須。**複数 plan を連続実行する場合、CHANGELOG の [Unreleased] で追記が conflict しやすい**ので、実行順に rebase すること。

### Findings considered and rejected（再監査不要）

- **「CLAUDE.md §6 が存在しない」（wf-* の参照切れ疑い）**: 誤り。`.claude/CLAUDE.template.md:171` に「## 6. Claude が判断に迷ったら参照すべきスキル一覧」が実在し、`docs/workflow-cheatsheet.md` も wheel force-include + `yt-skills sync --asset workflow-cheatsheet` で配布される正当な参照。
- **「yt-launch-curve / yt-thumbnail-correlate / yt-theme-compare / yt-channel-trend が未登録の可能性」**: 全 4 CLI が `pyproject.toml::[project.scripts]` に実在。
- **「channel-new の description に廃止スキル channel-import のトリガー残存」**: by design。旧名で呼ぶユーザーを統合先へルーティングする意図的な alias。
- **「automation-release の awk が大文字小文字厳密で false positive」**: by design。`### Migration` の完全一致は `docs/changelog-contract.md` の契約仕様。
- **「thumbnail prompt-schema 試験導入の誤用リスク」**: 本文に「実本番フローからは未接続」と明示済み。
- **「wf-new / wf-next / wf-status のトリガー衝突」「analytics / analyze / report のトリガー衝突」**: 各 description に相互の否定トリガー（「既存の進行は /wf-next」「/analytics --analyze の前段」等）が既に記述済み。
- **「video-analyze / community-post の設定読み込みゲート文言が矛盾」**: 文言は冗長だが「存在しない override は未設定として扱い、勝手に作成しない」「fallback 元としては使わない」と一義的に書かれており誤読の余地は小さい。
- **「suno-helper 拡張 ID の形式説明不足」「ペーシング定義値が SKILL.md に無い」**: Cross References で `extensions/shared/constants.ts::BALANCED_RUN_PACING` への参照が明示済み。情報の置き場所として妥当。
- **「community-draft の poll deprecated が frontmatter 未記載」**: 本文の型一覧表に DEPRECATED と移行ガイドが明記済み。frontmatter は現行型のみ列挙しており誤誘導なし。

### Plan 作成時の再 vet による縮小（監査 finding との差分）

- **010（channel-new）**: 監査は「完了条件が埋没・Step 3 が混在」と主張したが、実読では TTP 完了条件は冒頭 48-60 行に在り、Step 3 は停止 17 チェックと許容 4 fail を理由付きで分離済み。実ギャップは「ペルソナ生成前の中間ゲート欠如」のみに縮小（M → S）。
- **014（masterup）**: 監査は「DL 状態管理の責務不明」と主張したが、責務分離は masterup:10 / suno-helper:130-131 に明文化済み。実ギャップは「部分ダウンロード検知」のみに縮小（M → S）。

### 監査で plan 化を見送った残課題

- **発動キーワード重複の機械検出**（`test_skill_docs_consistency.py` 系譜で「同一鉤括弧キーワードが複数 description に出たら fail」）— 規約 005 の合意後に検討
- **`assets.music_downloaded` の曲数型への拡張**（bool → `{downloaded, expected}`。014 の機械化。スキーマ変更のため別判断）
- **巨大 SKILL.md（collection-ideate 673 行 / automation-update 672 行）の構造分割** — 参照関係は明示されておりリスクの割に益が薄いと判断
- **automation-update の Migration 欠落 fallback の要約手順詳細化**（M、LOW-MED）
- **metadata-audit の issue 種別 → 対応スキル対応表**（S、LOW）
- **streaming の ssh-agent 毎セッション再登録の前提セクション昇格**（S、LOW）
- **修正後スキルの実測検証**: dotfiles の `empirical-prompt-tuning` スキル（バイアスを排した実行者に実行させ両面評価）で、006 / 011 / 013 など解釈が分かれやすい修正の受け入れ検証を行う選択肢がある（オペレーター判断）

---

## 第 1 回監査（distrokid-helper 本体 + yt-collection-serve、2026-06-12、基準 commit `fa296fe`）

| Plan | Title | Priority | Effort | Depends on | Issue | Status |
|------|-------|----------|--------|------------|-------|--------|
| 001 | POST /distrokid/releases の入力検証 + POST body サイズ上限 | P1 | S | — | [#953](https://github.com/daiki-beppu/youtube-automation/issues/953) | DONE |
| 002 | distrokid-helper の dev ツールチェーンを suno-helper と統一 | P2 | M | — | [#954](https://github.com/daiki-beppu/youtube-automation/issues/954) | DONE |
| 003 | distrokid-helper に lint / format ゲート + CI パリティ | P2 | M | 002 | [#955](https://github.com/daiki-beppu/youtube-automation/issues/955) | DONE |
| 004 | サーバー URL 既定値を shared/constants.ts に集約 | P3 | S | — | [#956](https://github.com/daiki-beppu/youtube-automation/issues/956) | DONE |

### Dependency notes

- 003 は 002 の後に実行する（両方が package.json と pnpm-lock.yaml を編集するため conflict）→ 両方 DONE
- 001 と 004 は完全に独立

### Findings considered and rejected

- **App.tsx:128 の「stale closure バグ」**: by design。コメント（App.tsx:113-114）が意図を明記済み
- **`write_distrokid_release` の TOCTOU race**: 単一オペレーター設計で実発生確率ほぼゼロ
- **CORS の `chrome-extension://` scheme 全許可**: `--allow-origin` が既に存在。Plan 001 で POST 側を緩和
- **`/distrokid/assets` の拡張子 whitelist**: 脅威前提が非現実的
- **`_send_json_error` のメッセージ切り詰め**: 信頼クライアント（自前拡張）のみ。実害なし
- **StatusBanner の XSS**: React JSX 自動エスケープで安全

### 監査で plan 化を見送った残課題

- **popup（App.tsx 301 行）のユニットテスト新設**（テスト, M）
- **README 運用エッジケース補強**（docs, S）
- **`waitForRemoval` のエラーメッセージ修正**（正確性, S）
- **Direction: セレクタ pre-flight check / fill 後検証チェックリスト**（M）
