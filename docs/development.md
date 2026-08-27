# 開発環境・パッケージング詳細

CLAUDE.md の「パッケージング」「extensions」「品質ゲート」節の詳細版。要点（規約として常に守るもの）は CLAUDE.md を参照。

## 開発者 bootstrap（正規入口）

この節を、本リポジトリを変更する人間・agent向け bootstrap の単一ソースとする。README / ONBOARDING / CLAUDE は読者別の短い入口だけを持ち、詳細手順はこの節を参照する。

初回 clone 後の親 checkout は、環境を初期化する場所であり、実装場所にはしない。

```bash
git clone git@github.com:daiki-beppu/youtube-automation.git
cd youtube-automation
nix develop
```

変更は必ず issue 用の linked worktree 上で行う。worktree を作成・移動した後も、その checkout で devShell（direnv または `nix develop`）に入る。親 checkout の `.venv` / `node_modules` は共有しない。

- **対話 shell**: direnv があれば `direnv allow` 一回で `.envrc`（nix-direnv 経由の `use flake`）が devShell へ自動入室させる。なければ `nix develop` を使う。どちらも shellHook が `uv sync` を自動実行する（失敗は warning で入場継続）
- **非対話 shell / agent**: `nix develop --command <command> [args...]` を正規入口とする。例: `nix develop --command uv run pytest tests/commands/system/test_doctor.py -q`
- **依存同期を fail-closed にしたい場合**: `nix develop --command uv sync` を明示実行する。exit 非 0 なら依存は同期されていないので、後続コマンドを実行しない

worktree の生成・命名・issue / PR 運用は [`docs/takt-operations.md`](takt-operations.md) を参照する。標準実装経路は takt + builtin workflow。

## プロジェクト固有コマンド（全量）

```bash
uv run yt-skills sync                                # チャンネルリポジトリへ .claude/skills を配布
uv run yt-skills sync --asset claude-md              # .claude/CLAUDE.md (BGM 運営方針テンプレ) を配布
uv run yt-skills list                                # 同梱スキル一覧
uv run yt-skills list --asset claude-md              # 同梱 CLAUDE.md テンプレ一覧
uv run yt-skills diff                                # 同梱版と target の差分確認
uv run yt-skills diff --asset claude-md              # CLAUDE.md テンプレの差分確認
uv run yt-skills migrate-state-git --channel-dir <path> --dry-run  # 既存channelの制御面Git移行を確認
uv run yt-skills migrate-state-git --channel-dir <path> --check    # 制御面JSONがcommit済みか検査
```

## テスト実行（pytest-xdist による並列化）

### テストの配置

`youtube_automation` の production module を実行して挙動を検証するテストは、`src/youtube_automation/` と同じ layer・subdirectory の `tests/<layer>/<sub>/test_<module>.py` に置く。repository の docs、CI、packaging、skill、Terraform などを静的に検査し、production module を実行しないテストは `tests/repo/` に置く。複数 layer をまたぐ実 tool の end-to-end テストは `tests/integration/`、共有 helper と fixture はそれぞれ `tests/helpers/` と `tests/fixtures/` に置く。

新しいテストの配置先は、まず検証対象の canonical owner を確認して決める。同じ module に複数テストが対応する場合は basename を変えず同じ鏡像 directory に共存させる。単一 owner に帰属できない repository 横断テストは root の許可リストへ追加せず、適切な repository または integration 境界へ置く。配置規約は `tests/repo/test_tests_layout_contract.py` が検査する。

ユニットテストスイートは待ち時間支配（実 sleep / subprocess 待ち。#2087 の計測で wall 213.5s に対し CPU 合計 ~43s）のため、[pytest-xdist](https://pytest-xdist.readthedocs.io/) による並列実行が有効。dev dependency に含まれている。

```bash
uv run pytest -n auto                            # 全スイートを CPU コア数の worker で並列実行
uv run pytest tests/ --ignore=tests/integration -n auto   # ユニットのみ並列実行
uv run pytest tests/ --ignore=tests/integration -n auto -m "not repo_contract and not slow"  # behavioral fast lane
uv run pytest tests/ --ignore=tests/integration -n auto -m repo_contract  # docs / CI / packaging 契約
uv run pytest tests/ --ignore=tests/integration -n auto -m slow           # 実 tool / process / 待機を含む lane
python .github/scripts/run-affected-tests.py                              # worktree差分へCI共通selectorを適用
```

- **既定は直列**（`addopts` には入れない）。単一ファイル・単一テストのデバッグ実行で worker 起動オーバーヘッドを毎回払わないため、また `-x` / `--pdb` など直列前提のオプションと干渉しないため。フルスイートを回すときに明示的に `-n auto` を付ける
- **marker の境界**: `repo_contract` は production behavior を起動せず repository 内の docs / CI / workflow / packaging を読むテスト、`slow` は実 Nix・ffmpeg・socket TTL・外部 tool/process・意図的待機を含むテストに付ける。分類の単一 registry は `tests/conftest.py` にあり、module は basename、個別 node は basename と test 識別子で登録するため、`tests/` 以下の配置に依存しない。同じ basename の source module は登録できない。存在・CI無選別の回帰契約は `tests/repo/test_pytest_lane_contract.py` が担う。両方に該当するテストは両 marker を持つ
- **fast lane の位置づけ**: behavioral fast lane は Python product code の短い red/green loop 用で、repository-only / slow test と `tests/integration/` を除く。変更した対象の直接テストは marker にかかわらず別途実行する。PR CI と takt `ci_verify` は marker lane ではなく共通selectorを使い、選別漏れの最終担保はCIの `main` pushが実行する無選別full suiteとする

変更種別ごとの最小入口:

| 変更 | 最初に実行 | PR 前の追加確認 |
|---|---|---|
| Python product code | behavioral fast lane + 変更 module の直接 test | unit-only full suite + `uv run pyscn check src/youtube_automation` |
| skill / skill reference script | production-importing test は `docs/architecture/tests-layout.md` の鏡像規則、repository-only 契約は `tests/repo/` | repository contract lane + unit-only full suite |
| docs / CI / packaging / hook | repository contract lane + 対応 file の直接 test | slow lane（tool 契約を含む場合）+ unit-only full suite |
| extensions | 対象 workspace の既存 pnpm lint / type / Vitest / Playwright | Extensions CI（pytest marker 対象外） |
| dashboard | `dashboard/` の lint / typecheck / test | test:e2e / build + Python server・wheel smoke |
| audio studio | `audio-studio/` の lint / typecheck / test | build + Python server・wheel smoke |
| release notes site | `site/` の check / test | build + Python 配布境界 test |
- **CI では `-n auto` を有効化済み**（`.github/workflows/ci.yml` の test ジョブ）
- **外部 GitHub Actions は full commit SHA で固定**し、追跡する stable version を同じ `uses:` 行のコメントに残す。複数 workflow で同じ action を使う場合も SHA/version を統一し、`tests/repo/test_github_actions_pinning.py` で mutable ref・drift・未棚卸し action を拒否する
- **CI の changed-path 分岐**: `.github/scripts/classify-ci-paths.sh` が PR と `main` push の差分を Python / packaging / Windows / ADR / 3 helper に分類する。branch protection の required check である `lint` / `test` job は path filter や job-level `if` で消さず、extension-only 変更では成功する軽量 step を返して Nix・uv・pytest を起動しない。空 diff は全 gate を有効化する fail-safe とし、分類変更時は `tests/repo/test_actions_parallel_workflows.py` の対応表も更新する
- **影響テスト選別エンジン**: `.github/scripts/select-affected-tests.py <changed-paths-file>` は、1行1pathの変更一覧から production import の推移的な逆参照、鏡像 test、直接変更 test、repository契約の明示対応表を統合し、pytest targetを決定的に1行1件で返す。`--format json` でも同じplanを出力する。空入力、削除・rename旧path、未知/config/docs path、解析失敗、`tests/conftest.py`・helper・fixture・依存lock等のfail-safe pathでは `ALL` を返す。markerでは絞り込まない。PR の `test` job とローカルの `python .github/scripts/run-affected-tests.py` はselected planを安全なargvで実行しtarget数/全test module数を記録する。local runnerはmerge-base以降のcommitに加えstaged・unstaged・untracked pathも統合する。`ALL` と `main` push はexact `pytest -n auto`の全suiteを実行するため、選別漏れはmerge後に検出される。extension-only の required job lightweight success は維持する
- worker ごとの分離: `tests/conftest.py` が `CHANNEL_DIR` の tmp コピーを **worker プロセスごとに独立して** 作り直す（controller が自動設定した値を環境変数継承でそのまま共有しない）。ユーザーが明示的に `CHANNEL_DIR` を指定した場合は全 worker がその指定を尊重する
- 注意: nix devShell / CLI を実 subprocess で叩く契約テストはホスト負荷に敏感で、混雑したマシンでは並列時に所要時間が大きく伸びることがある

## パッケージング

- `.claude/skills/` は `[tool.hatch.build.targets.wheel.force-include]` で wheel 内 `_skills/` に同梱され、`yt-skills sync` が `importlib.resources` で参照する
- `.claude/CLAUDE.template.md` も同様に `[tool.hatch.build.targets.wheel.force-include]` で wheel 内 `_claude_md/CLAUDE.template.md` に同梱され、`yt-skills sync --asset claude-md` で `.claude/CLAUDE.md` として展開される
- 配布アセットの追加は `src/youtube_automation/commands/system/skills_sync/__init__.py::_ASSET_SPECS` に entry を追加するだけで `list/sync/diff` が自動的にサポートされる（`kind="dir" | "file"` を選ぶ）
- `skills` asset を標準レイアウト（`.claude/skills`）へ sync すると、下流リポにも `.agents/skills -> ../.claude/skills` の相対 symlink を併設する（Codex CLI 探索パス規約）。既存の正しい symlink は冪等にスキップし、張り直しは `--force`、symlink 非対応環境では警告のみで sync は継続する（`_ops.py::_ensure_agents_skills_symlink`）
- バージョン bump は `pyproject.toml::version` のみを更新する（`src/youtube_automation/__init__.py::__version__` は `importlib.metadata` 経由で動的に読み込むため触らない）。リリース運用全体は `/automation-release` スキルで一気通貫に実行する

## dashboard 開発

dashboard は ADR-0013 / ADR-0021 で許可された本リポジトリ唯一の dashboard 限定 TypeScript 例外。frontend workspace は `dashboard/`、完成済み Vite asset は `src/youtube_automation/dashboard_dist/` に置く。tayk core や削除済み `packages/` を追加してはならない。

### frontend 品質ゲート

Node.js / pnpm は Nix の extensions shell と同じ固定 toolchain を使い、ambient `pnpm` や `npx` は使わない。依存 install は lockfile を使い fail-closed にする。

```bash
nix develop .#extensions --command pnpm -C dashboard install --frozen-lockfile
nix develop .#extensions --command pnpm -C dashboard lint
nix develop .#extensions --command pnpm -C dashboard typecheck
nix develop .#extensions --command pnpm -C dashboard test
nix develop .#extensions --command pnpm -C dashboard test:e2e
nix develop .#extensions --command pnpm -C dashboard build
```

component 追加前は対象 workspace で `shadcn info` と registry/公式 docs を確認する。shadcn/ui の Base UI、Tailwind CSS v4、semantic token を使い、`extensions/shared-ui` は package/release 境界が異なるため直接 import しない。

### Python と配布の境界

- Python は channel registry、起動時収集、read model、JSON API、`127.0.0.1` の HTTP server を所有する。frontend は同一 origin API の読み取りだけを行う。
- 通常の `yt-dashboard` は全登録チャンネルについて YouTube Data API / YouTube Analytics API を使う standard 収集を直列実行してから配信する。失敗はチャンネル単位で隔離する。OAuth のない frontend E2E / wheel smoke は `yt-dashboard --skip-refresh` を使い、保存済み fixture を読む。
- `dashboard build` は Vite output を `src/youtube_automation/dashboard_dist/` へ生成する。Vite の production build は明示的に実行し、Python build backend から Node.js を暗黙起動しない。
- `dashboard_dist/` は package data として wheel / sdist に同梱し、runtime は `importlib.resources` で解決する。candidate wheel の非 editable install smoke で `index.html` と hashed asset、API 配信を確認する。

## Audio Studio 開発

Audio Studio は ADR-0028 / ADR-0021 で許可された collection 音源編集 UI。frontend workspace は `audio-studio/`、完成済み Vite asset は `src/youtube_automation/audio_studio_dist/` に置く。`dashboard/` や `extensions/shared-ui` を import しない。

```bash
nix develop .#extensions --command pnpm -C audio-studio install --frozen-lockfile
nix develop .#extensions --command pnpm -C audio-studio lint
nix develop .#extensions --command pnpm -C audio-studio typecheck
nix develop .#extensions --command pnpm -C audio-studio test
nix develop .#extensions --command pnpm -C audio-studio build
```

- Python server は `127.0.0.1` にだけ bind し、track allowlist、duration probe、HTTP Range、server-kind 別 lifecycle を所有する。
- cleanup 調整 API は skill-config の既定値と `audio-adjustments.json::tracks.<filename>` の差分を分けて返し、PUT は full settings を再検証して差分だけを原子的に保存する。
- 曲順 API は `order` が実トラックの filename 集合と完全一致する場合だけ、seed と先頭固定順を cleanup 差分と同じ文書へ原子的に保存する。frontend の同一 seed は同じ並びを再現し、手動変更では seed を破棄する。
- `yt-generate-master` と `BAHMetadataGenerator` は保存済み `order` を共有する。CLI の順序フラグがあれば保存順より優先し、保存順に過不足があれば master / chapter のどちらも fail-loud で停止する。
- master 調整 API は `audio-adjustments.json::master` の EQ・loudnorm・limiter 完全設定を保存し、POST apply は `yt-master-adjust` と同じ処理を呼ぶ。初回適用時の master.mp3 は `01-master/originals-pre-adjust/master.mp3` へ退避し、以後は必ずその原本から一時ファイルを作って atomic replace するため、調整を累積しない。master.mp3 不在時は明示エラーにする。
- `yt-finalize-master` と `yt-master-adjust` の適用順は ambient finalize → master 全体調整とする。両 CLI は同じ master lock を共有し、finalize 成功時に master 全体調整用原本を同期する。
- ambient finalize API は `audio-adjustments.json::finalize` を skill-config より優先し、`01-master/originals-pre-finalize/master.mp3` を常に入力にする。成功時は `originals-pre-adjust/master.mp3` を新しい ambient 合成結果へ更新し、UI route は保存済み master 全体調整を続けて再適用する。CLI フラグ > 保存値 > skill-config > 組み込み default の順とし、保存値不在・layer 0 件では従来どおり pass-through する。
- finalize UI は対象 layer 名を表示し、layer directory / glob、共通および per-file の音量・fade-in curve、loudnorm、mix を編集する。対象 layer 0 件または master 不在では理由を表示し、対象依存 controls と apply を無効化する。layer directory / glob と保存は誤指定から UI 内で復旧できるよう維持する。
- EQ preview は Web Audio の 2 つの peaking `BiquadFilterNode` であり、保存後に適用する ffmpeg `equalizer` と完全一致するものとして扱わない。
- build は Vite output を `src/youtube_automation/audio_studio_dist/` へ生成する。Python build backend から Node.js を暗黙起動しない。
- `audio_studio_dist/` は wheel / sdist に同梱し、candidate wheel の非 editable install smoke で CLI と asset 配信を確認する。
- frontend source を変えた PR は build output の同期差分、frontend 5 gate、Python server test、wheel smoke を通す。

## リリースノートサイト開発

`site/` は ADR-0023 / ADR-0021 で許可された Blume ベースの公開静的サイトで、`docs/release-notes/*.md`、明示 allowlist の運用文書、`.claude/skills/*/SKILL.md` の公開可能な規定フィールドだけを読む。skill ページ生成も `site/` の TypeScript 内で完結し、Python CLI を起動しない。Node.js / pnpm は dashboard・extensions と同じ Nix toolchain を使い、ambient `pnpm` や `npx` は使わない。

```bash
nix develop .#extensions --command pnpm -C site install --frozen-lockfile
nix develop .#extensions --command pnpm -C site check
nix develop .#extensions --command pnpm -C site build
nix develop .#extensions --command pnpm -C site test
```

- `site/.blume/` と `site/dist/` は再生成可能な build output であり commit しない。CI は content/schema check、一覧・詳細の契約 test、production build を実行する。
- `site/tests/color-contrast.test.mjs` は production build の `index.html` が参照する stylesheet closure から実際の色値を解決するため、`test` は必ず `build` の後に実行する。light / dark それぞれの body text、muted text、accent / link、main / extension の kind badge 前景と合成後の背景、card の default / hover border を検証する。
- contrast threshold は text が `4.5:1`、border などの non-text が `3:1`。基準未達時は failure に pair 名、実測比 `x.xx:1`、必要比 `4.50:1` または `3.00:1` が出るため、該当 theme と用途の DADS token / mix を見直す。
- contrast gate は既存の site CI job と `pnpm -C site test` に含まれる Node test で完結する。新しい CI job、headless browser、外部サービスによるブラウザ監査は不要。
- 静的サイトは Cloudflare Pages へ独立して配信する。preview / production の公開処理は Cloudflare Pages Git integration が所有し、この品質ゲートは deploy しない。
- Cloudflare Pages の production / preview 設定、公開 URL、障害復旧用 Direct Upload は [`docs/release-notes-deployment.md`](release-notes-deployment.md) を参照する。
- `site/` の source、lockfile、生成物は Python wheel / sdist には同梱しない。Hatch は `src/youtube_automation/` と明示した force-include だけを扱い、配布境界 test が実 archive に `site/` が無いことを確認する。

## skill 開発ループ（編集 → 検証 → 配布）

`.claude/skills/` 配下の skill を編集してから下流チャンネルリポジトリへ届くまでの一連手順（issue #2098）。

### 実 skill 挙動のローカル E2E

`evals/` は、静的な skill lint / repository contract では検証できない LLM の実挙動を `promptfoo` + `claude -p` で確認する独立レーンです。モデル利用料金と Claude Code の認証を伴うため、`pytest` や pull request CI からは起動しません。

```bash
nix develop --command pnpm dlx promptfoo@0.122.0 eval -c evals/promptfooconfig.yaml
```

GitHub Actions では独立した `evals.yml` を nightly / `workflow_dispatch` で起動します。Actions secret の `CLAUDE_CODE_OAUTH_TOKEN` または `ANTHROPIC_API_KEY` がどちらも未設定なら、有料の eval job を理由付きで skip します。現在の対象、権限制限、fixture 不変確認、禁止事項 assertion の検出力確認、CI の summary 契約は [`evals/README.md`](../evals/README.md) を参照してください。

### 1. 編集

- 実体は常に `.claude/skills/<name>/` を編集する（`.agents/skills` は Codex CLI 探索パス用の symlink）。付属スクリプトは `.claude/skills/<name>/references/` に置く（ルート直下 `scripts/` は設けない）
- skill も通常コードと同じ issue 専用 linked worktree で編集する。利用中の agent が `.claude/skills/**` を protected path として扱い書き込みを拒否する場合は、権限を迂回せず Codex または許可済みの対話セッションへ同じ issue worktree を引き継ぐ
- 書き方の規約: frontmatter の記法は `CLAUDE.md`「### skill frontmatter」、SKILL.md 本文の書き方は `docs/skill-design/skill-authoring-guidelines.md` に従う

### 2. 検証（編集後に実行するもの）

SKILL.md frontmatter だけを検証する最短入口は `yt-skills lint`。全 skill は引数なし、変更対象だけなら skill 名を列挙する。

```bash
uv run yt-skills lint [<skill>...]
```

これは strict YAML / `description:` double-quote の軽量検証であり、skill 本文・docs・features catalog・配布経路の契約は対象外。広い契約は目的を分けて pytest で確認する:

```bash
# 全 skill 横断の実行契約（frontmatter strict YAML / docs・配布参照整合）
uv run pytest tests/commands/system/test_skill_frontmatter_yaml.py tests/repo/test_skill_docs_consistency.py -n auto

# 編集した skill に個別契約テストがあれば併走する。探し方:
rg -l '<skill-name>' tests/

# 配布経路（sync / packaging）を触った場合のみ:
uv run pytest tests/commands/system/test_skills_sync.py tests/commands/system/test_skills_sync_package.py tests/commands/system/test_skills_sync_claude_md.py -n auto

# candidate wheel を隔離 venv へ installし、擬似下流への全 asset sync / diff を貫通確認:
uv run pytest tests/repo/test_skills_sync_installed_wheel.py -q
```

最終的な担保は CI の全体 pytest。上記はローカルの高速フィードバック用で、全体スイートの代替ではない。

### 3. 動作確認（upstream と下流で `yt-skills` が読むソースが異なる）

- **upstream（本リポジトリ内）**: `uv run yt-skills list/diff/sync` は editable fallback によりリポジトリ直下の `.claude/skills/` を直接読む（wheel ビルド不要。編集が即反映される）
- **下流（チャンネルリポジトリ）**: pin されたリリース版 wheel に焼き込まれた `_skills/` を読む。**upstream で編集しただけでは下流の `yt-skills diff/sync` には一切反映されない**
- release前の packaged-resource 経路は `uv run pytest tests/repo/test_skills_sync_installed_wheel.py -q` で再現できる。testはcandidate wheelをrepository外の一時directoryへbuildし、隔離venvへ非editable installしてから、空の擬似下流へ全assetをsyncする。同期後のtreeをsourceとbyte単位で比較し、`.agents/skills` symlinkとinstalled `yt-skills diff` の差分なしも確認する
- CI `build-smoke` も同じpytest targetへbuild済みwheelを `YTA_CANDIDATE_WHEEL` で渡すため、ローカルとCIで判定ロジックを二重管理しない。環境変数未指定のローカル実行ではtest自身が一時領域へwheelをbuildする
- このsmokeが保証するのは、candidate wheelから資格情報を持たない標準layoutの擬似下流への配布内容と冪等性まで。実チャンネル固有差分、release作成、pin更新、認証を含む `/automation --update` の運用確認は引き続きリリース後に行う

### 4. 配布（下流反映はリリース一巡に律速される）

下流に届けるには以下の 2 リポジトリ横断の一巡が必要（skill 1 行の修正でも同じ）:

1. `CHANGELOG.md` の `[Unreleased]` に追記（`.claude/skills/` は**実コード扱い**。CI の changelog ジョブでゲート）
2. PR 作成 → CI green → merge
3. upstream で `/automation-release`（prepare → リリース PR → tag push → Release publish）
4. 下流リポジトリで `/automation --update`（pin bump → `uv lock` → `yt-skills sync` → コミット）

### `.agents/skills` symlink の failure mode（`--target` 非標準パス）

`yt-skills sync` が `.agents/skills -> ../.claude/skills` の symlink を併設するのは、**標準レイアウト（`<repo>/.claude/skills`）へ sync したときに限る**。`--target` で非標準パスを指定した場合は repo root を推定できないため、**symlink は作成されず、警告も出ない**（`_ops.py::_ensure_agents_skills_symlink` が対象外として `None` を返す）。その環境では Codex CLI から同期済み skill が見えなくなるので、非標準パス運用時は `.agents/skills` symlink を手動で用意すること。

### 新規 skill 追加チェックリスト

- [ ] `.claude/skills/<name>/SKILL.md` を作成（`docs/skill-design/skill-authoring-guidelines.md` 準拠。frontmatter 記法は `CLAUDE.md`「### skill frontmatter」）
- [ ] 付属スクリプト・参照資料は `.claude/skills/<name>/references/` に配置
- [ ] 契約テスト `tests/repo/test_<name>_skill_contract.py` を追加（雛形は既存の `tests/repo/test_video_description_skill_contract.py` / `tests/repo/test_flop_analysis_skill_contract.py` を参照。SKILL.md の必須節・参照ファイルの存在・frontmatter 記述を機械担保する）
- [ ] `docs/features.md` のカタログに 1 行追加し、冒頭の「全 **N** 個」を更新
- [ ] `CHANGELOG.md` の `[Unreleased]` に追記（`.claude/skills/` は実コード扱いでゲート対象）

### fork 運用者向け: upstream owner 参照の一覧

本リポジトリは `daiki-beppu/youtube-automation` を official upstream として前提にしている。fork して独自運用する場合、GitHub owner の固定参照が fork とズレて生成物・案内コマンドに齟齬を生むため、以下を書き換える。

**単一ソース（コード）**: `src/youtube_automation/commands/system/automation_update_refs.py` の `UPSTREAM_REPO` 定数。`yt-automation-update` の official upstream 検証（サプライチェーン保護の意図的ガード）と `yt-doctor` の suggested command、`/automation --update` / `/extension` の `gh` / `curl` コマンドはすべて実行時にここから導出される。fork ではまずこの定数を変更する。

**`UPSTREAM_REPO` から導出されず、手で書き換えが要るファイル**:

| ファイル | 残存箇所 |
|---|---|
| `.claude/CLAUDE.template.md` | 冒頭と「このリポジトリの規約」の upstream 表記 |
| `.claude/skills/setup/SKILL.md` | bootstrap 用 `uv add git+...`（パッケージ導入前に実行するため定数から導出できない） |
| `.claude/skills/automation/SKILL.md` | 冒頭 prose と Step 1-0 の既定値表記、cleanup guide への doc リンク |
| `.claude/skills/extension/SKILL.md` | `gh` 未導入時の手動ダウンロード fallback 用 Release ページ URL、install reference の既定値表記 |
| `.claude/skills/automation-release/references/*.md` | リリースチェックリスト / CHANGELOG 昇格手順内の URL 例 |
| `.claude/skills/setup/references/claude-md-template.md` / `.claude/skills/setup/references/gcp-bootstrap.md` | upstream リポジトリ名の説明 |
| `src/youtube_automation/commands/system/skills_sync/__init__.py` | module docstring の導入コマンド例 |

上表は代表箇所のポインタであり、全箇所は `rg -n "daiki-beppu/youtube-automation"` で列挙する。

## 依存ポリシー: deprecated 表明済み依存の取り扱い（詳細）

- **`google-auth-httplib2`（PyPI 0.4.0 で deprecated 表明）**:
  - `src/youtube_automation/` / `tests/` 配下に `google_auth_httplib2` の **直 import を新規追加しない**（現状 0 件、回帰テスト `tests/repo/test_no_google_auth_httplib2_direct_import.py` で機械担保）
  - 既存の transitive 依存は `googleapiclient.discovery.build(..., credentials=credentials)` 経由で残置する（上流 `google-api-python-client` が内部で `google_auth_httplib2.AuthorizedHttp` を要求しているため、即時撤去不可）
  - 上流が non-httplib2 transport（`google.auth.transport.requests` など）を正式サポートした際の移行手順・撤去判断は `docs/migration/google-auth-httplib2.md` を参照
  - `pyproject.toml::dependencies` の `"google-auth-httplib2"` 直接宣言の撤去は transport 切替完了後に別 issue で再検証する

## extensions（Chrome 拡張開発）

`extensions/` 配下の Chrome 拡張は **WXT + React + TypeScript + Tailwind CSS** スタックで開発する（Python 本体とは独立した Node ツールチェーン）。詳細は `extensions/README.md`。

- **ディレクトリ規約**: 各拡張は `extensions/<name>/` に WXT 規約（`entrypoints/` 構成）で配置。複数拡張で再利用する runtime 契約コードは `extensions/shared/`（契約定数 / API client / origin allowlist / DOM ヘルパ）に集約し、各拡張から相対 import（`../../shared/*`）で参照する。shadcn/ui primitive・`cn()`・theme CSS は依存解決を自己完結させる workspace package `extensions/shared-ui/` に集約し、公開 package `@youtube-automation/ui` だけを参照する
- **manifest は自動生成**: `manifest.json` を手書きせず `wxt.config.ts` から生成する。権限は最小権限を `lib/manifest.ts` の `MANIFEST_PERMISSIONS` 単一定数で宣言し、`wxt.config.ts` がそれを参照する（過剰権限の混入は Vitest で機械担保）
- **型安全**: 全 source を TypeScript で書き、`@types/chrome` で `chrome.*` を型付け。message は `@webext-core/messaging`、`chrome.storage` は `@wxt-dev/storage` の型付き wrapper を経由する
- **契約文字列**: サーバー（`yt-collection-serve`）との互換契約値（storage key / 配信ルート / phase 値）は `extensions/shared/constants.ts` の定数として 1 箇所で定義する。メッセージ種別（`run` / `stop` / `progress`）は各拡張の `lib/messaging.ts` で `@webext-core/messaging` の ProtocolMap として型付け定義する。ハードコーディング禁止
- **テスト必須**: unit は Vitest（`nix develop .#extensions --command pnpm -C extensions/<name> test`）、e2e は Playwright（初回に `nix develop .#extensions --command pnpm -C extensions/<name> exec playwright install --with-deps chromium`、実行は `nix develop .#extensions --command pnpm -C extensions/<name> test:e2e`。Suno UI / DistroKid UI mock への DOM 注入スモーク）。CI は `.github/workflows/extensions.yml` が同じ Nix 入口で lint / 型チェック / Vitest / Playwright を実行する
- **成果物は commit しない**: `node_modules/` / `dist/` / `.wxt/` / `.output/` は `.gitignore` 済み。配布は `release-extensions.yml` が tag push 時に zip を GitHub Release へ添付する
- **パッケージマネージャ**: 3拡張とも Nix extensions shell の Node 24 / pnpm 11.15.1 固定（`ni`/`nr`、ambient `pnpm`、`npx` は使わない）。`nix develop .#extensions --command pnpm ...` により、各 `package.json::packageManager`、コミット済み lockfile、`pnpm-workspace.yaml::allowBuilds` の依存 build script 承認、CI を揃える契約である。install は `--frozen-lockfile` を必須とし、`--ignore-workspace` は使用しない。全拡張共通の install / build / zip、生成 manifest / 期待名 zip の確認と lockfile 無差分確認は `extensions/README.md::pnpm バージョン契約` を正とする
- **リリース手順**: 拡張のリリース（`extensions/<name>/package.json::version` bump → `release/ext-v<VER>` PR → merge commit への `ext-v<VER>` tag push → Release asset 確認）は `/automation-release` スキルの extension release phase で実行する。tag は Python 本体の `v*` と分離した `ext-v*` 系列で、バージョンは Python 本体と完全独立（`docs/adr/0011-extension-distribution.md`）

## 品質ゲート（CI）

品質ゲートはローカル git hook ではなく CI（`.github/workflows/ci.yml`）で一元的に担保する（issue #2534 で lefthook を廃止。sandbox 化された worker が `.git/hooks` へ書き込めず bootstrap が反復失敗していたため、ローカル hook は持たない）。

- **lint ジョブ**: `ruff check` / `ruff format --check`（旧 pre-commit と同等）/ `pyscn check src/youtube_automation`（構造品質ゲート。Fallow の Python 対応物として issue #4615 で導入）
  - **pyscn の閾値方針**: 複雑度（`max_complexity`）と関数長（`function_sloc_critical_threshold`）は導入時点の `src/youtube_automation` 実測最大値を `pyproject.toml::[tool.pyscn]` に固定してあり、既存債務は通しつつ実測値を超える新規の悪化だけを fail させる。dead code と循環 import は導入時点で 0 件のため即時 fail が有効。債務返済で実測値が下がったら閾値も追随して締め直す。code clone の検出は informational（fail しない）
  - **pyscn の new-only 差分ゲート**: 閾値ゲートは既存債務を追認した実測値がそのまま上限になるため、独立した step `.github/scripts/pyscn-diff-gate.py` が PR の base commit を一時 worktree へ展開して base / HEAD の 2 回 `pyscn analyze --json` を実行し、**base に無い finding（complexity high risk 関数 / dead code）が増えたときだけ** fail する（issue #4616。`extensions/` の Fallow `audit.gate: new-only` と同じ運用モデル）。突き合わせ鍵はファイルパス + finding 種別 + シンボル名で、行番号を含めないため無関係な行ずれでは fail しない。比較元をリポジトリにコミットした baseline にしないのは、再生成忘れによる亡霊エントリ（`extensions/.fallow-dupes-baseline.json` の既知の運用負債）を再生産しないため。基準点は CI がイベント種別から解決して `PYSCN_DIFF_BASE` で渡し（PR は base sha、`main` push は `github.event.before`、空・全 0 は `HEAD^`）、ローカル単体実行（`nix develop --command uv run python .github/scripts/pyscn-diff-gate.py`）では `origin/main` → `main` の merge-base へフォールバックする。突き合わせ契約は `tests/repo/test_pyscn_diff_gate_contract.py` が機械担保する
- **changelog ジョブ**: 実コード（`src/youtube_automation/` / `.claude/skills/` / `.claude/CLAUDE.template.md` / `pyproject.toml`）を変更したのに `changelog.d/` の fragment 追加または `CHANGELOG.md` の更新が無ければ fail する。加えて、ラベルや path filter に関係なく `changelog.d/` 全件のファイル名 type と bullet 体裁を `.github/scripts/validate-changelog-fragments.py` が `yt-changelog-compile` と同じ実装で検証する（ローカルでも `python .github/scripts/validate-changelog-fragments.py` で単体実行できる）。fragment の書式は `changelog.d/README.md` を参照する。意図的に省く場合は PR に `skip-changelog` ラベルを付与する
- **any-gate ジョブ**: 広すぎる型注釈ゲート。基準点からの新規追加行だけを対象に、ディレクトリを問わず全 `*.py` / `*.ts` / `*.tsx` の Python の typing module 経由の Any 型、または TypeScript の any 型注釈を検出したら fail する。既存行は対象外。ロジック本体は `.github/scripts/any-usage-gate.sh`（ローカルでも `bash .github/scripts/any-usage-gate.sh` で単体実行できる）
  - **基準点の解決順**: `PRE_PUSH_DIFF_BASE`（CI の any-gate ジョブが PR の base sha を渡す）→ `origin/main` → `main`。実際の diff 基準は解決した ref と HEAD の merge-base。`main` へのフォールバックは、remote を 1 つも持たない隔離クローンで takt がタスクを実行するため（クローンのローカル `main` はクローン時点の main そのものなので基準点は変わらない）。この経路が無いと `ci_verify` が push 前に再現すべき 4 ゲートのうち any-gate だけが常に self-skip する（issue #3048）。どの ref も解決できないときは、試した ref を列挙して skip する。解決順そのものは `tests/repo/test_any_usage_gate.py` が機械担保する
  - **Python**: `.github/scripts/any_usage_python_resolver.py` が `ast` でファイルを解析し、`typing.Any` の修飾アクセス（`import typing` / `import typing as t` 経由）と `from typing import Any`（複数行の括弧 import・`as` alias 含む）の直接 import 経由の裸 `Any` の両方を、実際に参照されている行番号として解決する。コメント・docstring・文字列リテラル中の "Any" は AST 上に現れないため誤検知しない。`python3` が無い場合は警告を出して Python 側の検出のみ省略する
  - **TypeScript**: `: any` 直書きに加え、`Array<any>` / `Record<string, any>` のようなジェネリック引数、union / intersection、tuple 要素、型エイリアス代入（`type X = any;`）、アロー関数戻り値（`() => any`）、型アサーション（`value as any`）などの型位置の `any` を検出する。正規表現で候補行を検出したのち `.github/scripts/any_usage_ts_line_cleaner.py` で行コメント（`//...`）と文字列・テンプレートリテラルの中身を取り除いてから再判定するため、コメントや文字列リテラル中の "any"（型注釈っぽい表記を含む）は誤検知しない

Python 側の未使用コード検出は、追加依存なしで CI に載っている Ruff `F` 系（未使用 import / 変数、未定義名など）を継続採用する。vulture は新規依存追加が必要で、Ruff `ARG` は既存コードに多数の既存違反があるため #1510 では採用しない。#4615 以降は lint ジョブの pyscn が CFG ベースの到達不能コード検出（return / raise 後のコードなど）を併用する。

devShell の運用:

- **devShell 入場コスト**: `.envrc` は [nix-direnv](https://github.com/nix-community/nix-direnv) をブートストラップし、評価済み dev 環境を `.direnv/` にキャッシュする。`flake.nix` / `flake.lock` / `.envrc` が変わらない限り入場時に nix を起動しないため、dirty worktree でも 2 回目以降の `direnv exec` は 1 秒未満で安定する（direnv stdlib の `use_flake` は入場のたびに `nix print-dev-env` を実行するため、flake 評価コストが毎回壁時計に乗り 7〜80 秒まで変動していた。issue #2097）。shellHook（`uv sync`）はキャッシュヒット時も毎入場で実行される。worktree ごとの初回入場のみキャッシュ生成（20 秒前後）が走る。nix-direnv の direnvrc 本体は初回のみ GitHub から取得しハッシュ検証のうえ `~/.cache/direnv/cas/` に永続キャッシュされる（オフライン初回のみ失敗し得る。その場合は `nix develop` 経路を使う）
- **devShell 内での実行**: direnv の自動入室が有効な shell ではそのまま `uv run pytest` 等を実行できる。agent や非対話 shell では `nix develop --command uv run pytest` のように実行すると、同じ devShell 内でコマンドを実行できる
- **skill script の直接実行**: project import / entry point を使う skill script は通常の `uv run` で worktree-local `.venv` を lockfile へ同期してから実行する。環境準備に失敗した場合は外部 API / Codex 呼び出し前に停止し、`nix develop --command <command> [args...]` で再実行する。標準ライブラリだけの補助 Python は `uv run --no-sync` を許容するが、project code には使わない（Claude Code hook は次項の例外）
- **Claude Code hook の実行**: 本リポジトリ用 `.claude/settings.json` の hook コマンドは devShell の外で、しかも pytest 実行中にも発火するため、上の「project code には `--no-sync` を使わない」規約の対象外とし、project entry point（`yt-progress-hook`）でも `uv run --no-sync` を使う。hook が lockfile 同期を試みると nix 外の CPython が解決されて `.venv` を丸ごと作り直し、実行中テストの console script subprocess を壊す（issue #4605）。`.venv` の正規の構築経路は devShell の shellHook（`uv sync`）であり、hook は既存 `.venv` を読むだけに留める。下流配布用 `.claude/settings.template.json` は uv が venv を管理する前提なので従来どおり `uv run`（`--no-sync` なし）を保つ
- **worktree 間の依存境界**: 共有するのは uv cache と pnpm content-addressable store だけとし、`.venv` / `node_modules` は各 worktree で生成する。親 checkout や sibling worktree の環境を symlink・コピーせず、branch ごとの lockfile、editable path、entry point を実行中 checkout と一致させる
- **TMPDIR の worktree 分離**: macOS の TMPDIR は per-user のグローバル値のため、複数 worktree の並行 pytest が同一パスへ書くと一時ディレクトリが run 間で干渉しうる（issue #2088）。shellHook は `.nix/worktree-tmpdir.sh` の出力を `TMPDIR` へ export し、共有 TMPDIR 配下の worktree ごとの決定的なサブディレクトリ（`yt-automation-tmp-<slug>-<cksum>`）へ分離する。TMPDIR が既に checkout 内へ隔離済みの場合はその値を尊重し、解決に失敗した場合は共有 TMPDIR のまま fail-open で続行する
- **Nix キャッシュの worktree 分離**: 並列 worktree が同一 fingerprint の flake を同時評価すると、ユーザーグローバルの Nix キャッシュ（既定 `~/.cache/nix` の eval-cache / fetcher-cache SQLite）への同時書込みが競合し、「error (ignored): SQLite database ... is busy」を stderr へ出しつつキャッシュ書込みを破棄し続ける（issue #2089）。`.envrc` / shellHook は Nix 専用の `NIX_CACHE_HOME` を worktree 分離 TMPDIR 配下（`<worktree_tmpdir>/nix-cache`）へ export し、各 worktree が自分の評価結果だけを参照する。`XDG_CACHE_HOME` には触れないため uv 等の他ツールのキャッシュは共有のまま変わらない。継承値は別 worktree の値がシェル経由でリークし得るため尊重せず、解決に失敗した場合は共有キャッシュのまま fail-open で続行する
- **sandbox worker での挙動**: takt worker は `.takt/runtime-prepare.sh` が TMPDIR / XDG_* / UV_CACHE_DIR を run ごとの runtime root 配下へ再構成する（issue #2163）
- refactor / fix でも src を触れば changelog fragment が要る。tests / docs だけの変更はゲート対象外（CI が自動 skip）

### changelog fragment（conflict 回避）

通常の PR は `changelog.d/<issue>-<slug>.<type>.md` という PR 固有ファイルへ変更履歴を
書き、リリース prepare で `uv run yt-changelog-compile` を実行して `[Unreleased]` へ
集約する。移行中の PR との後方互換のため、CI は `CHANGELOG.md` の直接編集も許容する。

### CHANGELOG.md の union merge（移行期の conflict 緩和）

CHANGELOG ゲートにより並行 PR が `[Unreleased]` 先頭へ同時に追記するため、`.gitattributes` で `CHANGELOG.md merge=union` を指定している（issue #2155）。両側の追記行を conflict にせず機械的に取り込むが、union merge には以下の副作用があるため merge 後は `[Unreleased]` を目視確認すること:

- **重複行**: 両ブランチが同一内容の行を追記した場合、その行が 2 回残ることがある
- **順序非保証**: 追記行の並び順は merge 順に依存し、時系列と一致しない場合がある
- **削除・編集に非対応**: 行の追加以外（既存行の削除・書き換え）が絡む変更は正しく解決されない可能性がある。リリース時の `[Unreleased]` → バージョン節への移動のような大規模編集を含む PR は、merge 結果を必ず確認する
