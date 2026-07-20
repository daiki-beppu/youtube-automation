# 開発環境・パッケージング詳細

CLAUDE.md の「パッケージング」「extensions」「Git hooks」節の詳細版。要点（規約として常に守るもの）は CLAUDE.md を参照。

## 開発者 bootstrap（正規入口）

この節を、本リポジトリを変更する人間・agent向け bootstrap の単一ソースとする。README / ONBOARDING / CLAUDE は読者別の短い入口だけを持ち、詳細手順はこの節を参照する。

初回 clone 後の親 checkout は、環境と hook を初期化する場所であり、実装場所にはしない。

```bash
git clone git@github.com:daiki-beppu/youtube-automation.git
cd youtube-automation
bash .lefthook/setup-worktree.sh
```

変更は必ず issue 用の linked worktree 上で行う。worktree を作成・移動した後も、その checkout で最初に `bash .lefthook/setup-worktree.sh` を実行する。親 checkout の `.venv` / `node_modules` は共有しない。

- **対話 shell**: setup wrapper は direnv があれば `.envrc` を allow して Nix devShell へ入り、なければ `nix develop` へ fallback する。どちらも toolchain、worktree-local依存、lefthook を同じ状態へ収束させる
- **非対話 shell / agent**: `bash .lefthook/setup-worktree.sh <command> [args...]` を正規入口とする。例: `bash .lefthook/setup-worktree.sh uv run pytest tests/test_doctor.py -q`。依存同期に失敗した場合は command を起動せず fail-closed で停止する
- **直接 devShell を使う場合**: direnv の自動入室後は `uv run ...` を直接実行できる。`nix develop` は wrapper の fallback / 診断手段であり、初回 bootstrap の同格入口ではない

worktree の生成・命名・issue / PR 運用は [`docs/takt-operations.md`](takt-operations.md) を参照する。

## プロジェクト固有コマンド（全量）

```bash
uv run yt-skills sync                                # チャンネルリポジトリへ .claude/skills を配布
uv run yt-skills sync --asset claude-md              # .claude/CLAUDE.md (BGM 運営方針テンプレ) を配布
uv run yt-skills list                                # 同梱スキル一覧
uv run yt-skills list --asset claude-md              # 同梱 CLAUDE.md テンプレ一覧
uv run yt-skills diff                                # 同梱版と target の差分確認
uv run yt-skills diff --asset claude-md              # CLAUDE.md テンプレの差分確認
```

## テスト実行（pytest-xdist による並列化）

ユニットテストスイートは待ち時間支配（実 sleep / subprocess 待ち。#2087 の計測で wall 213.5s に対し CPU 合計 ~43s）のため、[pytest-xdist](https://pytest-xdist.readthedocs.io/) による並列実行が有効。dev dependency に含まれている。

```bash
uv run pytest -n auto                            # 全スイートを CPU コア数の worker で並列実行
uv run pytest tests/ --ignore=tests/integration -n auto   # ユニットのみ並列実行
uv run pytest tests/ --ignore=tests/integration -n auto -m "not repo_contract and not slow"  # behavioral fast lane
uv run pytest tests/ --ignore=tests/integration -n auto -m repo_contract  # docs / CI / packaging 契約
uv run pytest tests/ --ignore=tests/integration -n auto -m slow           # 実 tool / process / 待機を含む lane
```

- **既定は直列**（`addopts` には入れない）。単一ファイル・単一テストのデバッグ実行で worker 起動オーバーヘッドを毎回払わないため、また `-x` / `--pdb` など直列前提のオプションと干渉しないため。フルスイートを回すときに明示的に `-n auto` を付ける
- **marker の境界**: `repo_contract` は production behavior を起動せず repository 内の docs / CI / workflow / packaging を読むテスト、`slow` は実 Nix・ffmpeg・socket TTL・外部 tool/process・意図的待機を含むテストに付ける。分類の単一 registry は `tests/conftest.py`、存在・CI無選別の回帰契約は `tests/test_pytest_lane_contract.py` が担う。両方に該当するテストは両 marker を持つ
- **fast lane の位置づけ**: behavioral fast lane は Python product code の短い red/green loop 用で、repository-only / slow test と `tests/integration/` を除く。変更した対象の直接テストは marker にかかわらず別途実行し、PR 前または CI では無選別の全スイートを必ず通す

変更種別ごとの最小入口:

| 変更 | 最初に実行 | PR 前の追加確認 |
|---|---|---|
| Python product code | behavioral fast lane + 変更 module の直接 test | unit-only full suite |
| skill / skill reference script | 対応する `tests/test_*skill*.py` / script test | repository contract lane + unit-only full suite |
| docs / CI / packaging / hook | repository contract lane + 対応 file の直接 test | slow lane（tool 契約を含む場合）+ unit-only full suite |
| extensions | 対象 workspace の既存 pnpm lint / type / Vitest / Playwright | Extensions CI（pytest marker 対象外） |
- **CI では `-n auto` を有効化済み**（`.github/workflows/ci.yml` の test ジョブ）
- worker ごとの分離: `tests/conftest.py` が `CHANNEL_DIR` の tmp コピーを **worker プロセスごとに独立して** 作り直す（controller が自動設定した値を環境変数継承でそのまま共有しない）。ユーザーが明示的に `CHANNEL_DIR` を指定した場合は全 worker がその指定を尊重する
- 注意: `tests/test_lefthook_installation_contract.py` の nix devShell 契約テストなど実 subprocess を叩くテストはホスト負荷に敏感で、混雑したマシンでは並列時に所要時間が大きく伸びることがある

## パッケージング

- `.claude/skills/` は `[tool.hatch.build.targets.wheel.force-include]` で wheel 内 `_skills/` に同梱され、`yt-skills sync` が `importlib.resources` で参照する
- `.claude/CLAUDE.template.md` も同様に `[tool.hatch.build.targets.wheel.force-include]` で wheel 内 `_claude_md/CLAUDE.template.md` に同梱され、`yt-skills sync --asset claude-md` で `.claude/CLAUDE.md` として展開される
- 配布アセットの追加は `src/youtube_automation/cli/skills_sync/__init__.py::_ASSET_SPECS` に entry を追加するだけで `list/sync/diff` が自動的にサポートされる（`kind="dir" | "file"` を選ぶ）
- `skills` asset を標準レイアウト（`.claude/skills`）へ sync すると、下流リポにも `.agents/skills -> ../.claude/skills` の相対 symlink を併設する（Codex CLI 探索パス規約）。既存の正しい symlink は冪等にスキップし、張り直しは `--force`、symlink 非対応環境では警告のみで sync は継続する（`_ops.py::_ensure_agents_skills_symlink`）
- バージョン bump は `pyproject.toml::version` のみを更新する（`src/youtube_automation/__init__.py::__version__` は `importlib.metadata` 経由で動的に読み込むため触らない）。リリース運用全体は `/automation-release` スキルで一気通貫に実行する

## skill 開発ループ（編集 → 検証 → 配布）

`.claude/skills/` 配下の skill を編集してから下流チャンネルリポジトリへ届くまでの一連手順（issue #2098）。

### 1. 編集（経路が takt provider 設定で分岐する）

- 実体は常に `.claude/skills/<name>/` を編集する（`.agents/skills` は Codex CLI 探索パス用の symlink）。付属スクリプトは `.claude/skills/<name>/references/` に置く（ルート直下 `scripts/` は設けない）
- `.claude/skills/**` は Claude Code の **protected paths** のため、編集経路は takt の provider 設定で分岐する:
  - `coder` persona が **codex provider**（現行のグローバル設定から継承）→ takt から問題なく回せる
  - `coder` を **Claude provider** に戻している環境 → takt からの Edit/Write が deny される。通常の Claude Code 対話セッションで直接編集し、commit / PR は手動で行う
  - 詳細は `docs/takt-operations.md` の「skill 編集と takt の関係」。**設定を確認せず takt に投げると deny で初めて気づく**ので、skill を触る issue を takt に載せる前に provider 設定を確認すること
- 書き方の規約: frontmatter `description:` は必ず double-quoted string、新規作成・改訂時は `docs/skill-design/skill-authoring-guidelines.md` の 7 ルールに従う

### 2. 検証（編集後に実行するもの）

SKILL.md frontmatter だけを検証する最短入口は `yt-skills lint`。全 skill は引数なし、変更対象だけなら skill 名を列挙する。

```bash
uv run yt-skills lint [<skill>...]
```

これは strict YAML / `description:` double-quote の軽量検証であり、skill 本文・docs・features catalog・配布経路の契約は対象外。広い契約は目的を分けて pytest で確認する:

```bash
# 全 skill 横断の契約（frontmatter strict YAML / docs 整合 / features カタログ整合）
uv run pytest tests/test_skill_frontmatter_yaml.py tests/test_skill_docs_consistency.py \
  tests/test_features_catalog_documentation.py -n auto

# 編集した skill に個別契約テストがあれば併走する。探し方:
rg -l '<skill-name>' tests/

# 配布経路（sync / packaging）を触った場合のみ:
uv run pytest tests/test_skills_sync.py tests/test_skills_sync_package.py tests/test_skills_sync_claude_md.py -n auto

# candidate wheel を隔離 venv へ installし、擬似下流への全 asset sync / diff を貫通確認:
uv run pytest tests/test_skills_sync_installed_wheel.py -q
```

最終的な担保は CI の全体 pytest。上記はローカルの高速フィードバック用で、全体スイートの代替ではない。

### 3. 動作確認（upstream と下流で `yt-skills` が読むソースが異なる）

- **upstream（本リポジトリ内）**: `uv run yt-skills list/diff/sync` は editable fallback によりリポジトリ直下の `.claude/skills/` を直接読む（wheel ビルド不要。編集が即反映される）
- **下流（チャンネルリポジトリ）**: pin されたリリース版 wheel に焼き込まれた `_skills/` を読む。**upstream で編集しただけでは下流の `yt-skills diff/sync` には一切反映されない**
- release前の packaged-resource 経路は `uv run pytest tests/test_skills_sync_installed_wheel.py -q` で再現できる。testはcandidate wheelをrepository外の一時directoryへbuildし、隔離venvへ非editable installしてから、空の擬似下流へ全assetをsyncする。同期後のtreeをsourceとbyte単位で比較し、`.agents/skills` symlinkとinstalled `yt-skills diff` の差分なしも確認する
- CI `build-smoke` も同じpytest targetへbuild済みwheelを `YTA_CANDIDATE_WHEEL` で渡すため、ローカルとCIで判定ロジックを二重管理しない。環境変数未指定のローカル実行ではtest自身が一時領域へwheelをbuildする
- このsmokeが保証するのは、candidate wheelから資格情報を持たない標準layoutの擬似下流への配布内容と冪等性まで。実チャンネル固有差分、release作成、pin更新、認証を含む `/automation-update` の運用確認は引き続きリリース後に行う

### 4. 配布（下流反映はリリース一巡に律速される）

下流に届けるには以下の 2 リポジトリ横断の一巡が必要（skill 1 行の修正でも同じ）:

1. `CHANGELOG.md` の `[Unreleased]` に追記（`.claude/skills/` は**実コード扱い**。lefthook pre-push + CI でゲート）
2. PR 作成 → CI green → merge
3. upstream で `/automation-release`（prepare → リリース PR → tag push → Release publish）
4. 下流リポジトリで `/automation-update`（pin bump → `uv lock` → `yt-skills sync` → コミット）

### `.agents/skills` symlink の failure mode（`--target` 非標準パス）

`yt-skills sync` が `.agents/skills -> ../.claude/skills` の symlink を併設するのは、**標準レイアウト（`<repo>/.claude/skills`）へ sync したときに限る**。`--target` で非標準パスを指定した場合は repo root を推定できないため、**symlink は作成されず、警告も出ない**（`_ops.py::_ensure_agents_skills_symlink` が対象外として `None` を返す）。その環境では Codex CLI から同期済み skill が見えなくなるので、非標準パス運用時は `.agents/skills` symlink を手動で用意すること。

### 新規 skill 追加チェックリスト

- [ ] `.claude/skills/<name>/SKILL.md` を作成（frontmatter `description:` は double-quoted / `docs/skill-design/skill-authoring-guidelines.md` の 7 ルール準拠）
- [ ] 付属スクリプト・参照資料は `.claude/skills/<name>/references/` に配置
- [ ] 契約テスト `tests/test_<name>_skill_contract.py` を追加（雛形は既存の `tests/test_video_description_skill_contract.py` / `tests/test_flop_analysis_skill_contract.py` を参照。SKILL.md の必須節・参照ファイルの存在・frontmatter 記述を機械担保する）
- [ ] `docs/features.md` のカタログに 1 行追加し、冒頭の「全 **N** 個」を更新（`tests/test_features_catalog_documentation.py` が全 skill ディレクトリとの 1:1 対応と総数一致を機械担保しており、忘れると CI で落ちる）
- [ ] `CHANGELOG.md` の `[Unreleased]` に追記（`.claude/skills/` は実コード扱いでゲート対象）

## 依存ポリシー: deprecated 表明済み依存の取り扱い（詳細）

- **`google-auth-httplib2`（PyPI 0.4.0 で deprecated 表明）**:
  - `src/youtube_automation/` / `tests/` 配下に `google_auth_httplib2` の **直 import を新規追加しない**（現状 0 件、回帰テスト `tests/test_no_google_auth_httplib2_direct_import.py` で機械担保）
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
- **パッケージマネージャ**: 3拡張とも Nix extensions shell の Node 24 / pnpm 11.12.0 固定（`ni`/`nr`、ambient `pnpm`、`npx` は使わない）。`nix develop .#extensions --command pnpm ...` により、各 `package.json::packageManager`、コミット済み lockfile、`pnpm-workspace.yaml::allowBuilds` の依存 build script 承認、CI を揃える契約である。install は `--frozen-lockfile` を必須とし、`--ignore-workspace` は使用しない。全拡張共通の install / build / zip、生成 manifest / 期待名 zip の確認と lockfile 無差分確認は `extensions/README.md::pnpm バージョン契約` を正とする
- **リリース手順**: 拡張のリリース（`extensions/<name>/package.json::version` bump → `release/ext-v<VER>` PR → merge commit への `ext-v<VER>` tag push → Release asset 確認）は `/automation-release` スキルの extension release phase で実行する。tag は Python 本体の `v*` と分離した `ext-v*` 系列で、バージョンは Python 本体と完全独立（`docs/adr/0011-extension-distribution.md`）

## Git hooks（lefthook）

Git hooks は [lefthook](https://lefthook.dev) で宣言的に管理する（設定は `lefthook.yml`）。

- **pre-commit**: 変更した Python ファイルに `ruff check` / `ruff format --check` をかける（CI の lint ジョブと同等）
- **pre-push**:
  - CHANGELOG ゲート。CI（`.github/workflows/ci.yml` の `changelog` ジョブ）と同じく、実コード（`src/youtube_automation/` / `.claude/skills/` / `.claude/CLAUDE.template.md` / `pyproject.toml`）を変更したのに `CHANGELOG.md` の `[Unreleased]` が未更新なら push を止める。ロジック本体は `.lefthook/pre-push/changelog-gate.sh`。lefthook は同一 hook で `use_stdin` を持てるコマンドを 1 つに制限するため、このスクリプトが pre-push の唯一の stdin 受信者としてブランチ削除 push を判定し、末尾でテスト差分警告・型注釈ゲートを連鎖実行する（削除 push はこの 3 ゲートすべてが対象外）。diff の基準点（`origin/main` との merge-base）もここで一度だけ解決し `PRE_PUSH_DIFF_BASE` として子ゲートへ export するため、3 スクリプトが個別に基準を再計算することはない（単体実行時は各スクリプトが自前で解決する）
  - テスト差分警告。`src/youtube_automation/` に差分があるのに `tests/` の差分がない場合、または `extensions/*/lib/` に差分があるのに extensions 配下の `*.test.ts` 差分がない場合に警告を出す。これは粗い検出なので push は止めない。意図的に省く場合は `SKIP_TEST_DIFF=1 git push` とし、skip した事実を hook 出力に残す。ロジック本体は `.lefthook/pre-push/test-diff-gate.sh`
  - 広すぎる型注釈ゲート。`origin/main` からの新規追加行だけを対象に、ディレクトリを問わず全 `*.py` / `*.ts` / `*.tsx` の Python の typing module 経由の Any 型、または TypeScript の any 型注釈を検出したら push を止める。既存行は対象外。ロジック本体は `.lefthook/pre-push/any-usage-gate.sh`
    - **Python**: `.lefthook/pre-push/any_usage_python_resolver.py` が `ast` でファイルを解析し、`typing.Any` の修飾アクセス（`import typing` / `import typing as t` 経由）と `from typing import Any`（複数行の括弧 import・`as` alias 含む）の直接 import 経由の裸 `Any` の両方を、実際に参照されている行番号として解決する。コメント・docstring・文字列リテラル中の "Any" は AST 上に現れないため誤検知しない。`python3` が無い場合は警告を出して Python 側の検出のみ省略する
    - **TypeScript**: `: any` 直書きに加え、`Array<any>` / `Record<string, any>` のようなジェネリック引数、union / intersection、tuple 要素、型エイリアス代入（`type X = any;`）、アロー関数戻り値（`() => any`）、型アサーション（`value as any`）などの型位置の `any` を検出する。正規表現で候補行を検出したのち `.lefthook/pre-push/any_usage_ts_line_cleaner.py` で行コメント（`//...`）と文字列・テンプレートリテラルの中身を取り除いてから再判定するため、コメントや文字列リテラル中の "any"（型注釈っぽい表記を含む）は誤検知しない

Python 側の未使用コード検出は、追加依存なしで CI / pre-commit に載っている Ruff `F` 系（未使用 import / 変数、未定義名など）を継続採用する。vulture は新規依存追加が必要で、Ruff `ARG` は既存コードに多数の既存違反があるため #1510 では採用しない。

有効化と運用:

- **有効化**: 親 checkout / 新規 worktree のどちらでも、最初に `bash .lefthook/setup-worktree.sh` を 1 回実行する。direnv があればルートの `.envrc`（nix-direnv 経由の `use flake`）を allow して devShell に入り、なければ `nix develop` を使う。どちらの経路でも shellHook と `.lefthook/install.sh` が hook wrapper を再生成する
- **devShell 入場コスト**: `.envrc` は [nix-direnv](https://github.com/nix-community/nix-direnv) をブートストラップし、評価済み dev 環境を `.direnv/` にキャッシュする。`flake.nix` / `flake.lock` / `.envrc` が変わらない限り入場時に nix を起動しないため、dirty worktree でも 2 回目以降の `direnv exec` は 1 秒未満で安定する（direnv stdlib の `use_flake` は入場のたびに `nix print-dev-env` を実行するため、flake 評価コストが毎回壁時計に乗り 7〜80 秒まで変動していた。issue #2097）。shellHook（lefthook install / `uv sync`）はキャッシュヒット時も毎入場で実行される。worktree ごとの初回入場のみキャッシュ生成（20 秒前後）が走る。nix-direnv の direnvrc 本体は初回のみ GitHub から取得しハッシュ検証のうえ `~/.cache/direnv/cas/` に永続キャッシュされる（オフライン初回のみ失敗し得る。その場合は `nix develop` 経路を使う）
- **devShell 内での実行**: direnv の自動入室が有効な shell ではそのまま `uv run pytest` 等を実行できる。agent や非対話 shell では `bash .lefthook/setup-worktree.sh uv run pytest` のように引数を渡すと、同じ devShell 内でコマンドを実行できる
- **依存同期の方針差（対話 vs explicit setup）**: 対話入場（direnv / `nix develop`）の shellHook は `uv sync` 失敗を warning に留めて入場を継続する（入場をブロックしない）。一方 `bash .lefthook/setup-worktree.sh [<command>...]` の explicit setup 経路は fail-closed で、devShell 入場後に `.lefthook/sync-deps.sh` が `uv sync` を明示実行し、失敗すると後続コマンドを実行せず exit 非 0 で停止する。nix-direnv のキャッシュ命中時は shellHook 自体が再実行されないため、explicit 経路の同期保証はこのラッパーが担う（issue #2125）
- **skill script の直接実行**: project import / entry point を使う skill script は通常の `uv run` で worktree-local `.venv` を lockfile へ同期してから実行する。環境準備に失敗した場合は外部 API / Codex 呼び出し前に停止し、`bash .lefthook/setup-worktree.sh <command> [args...]` で再実行する。標準ライブラリだけの補助 Python は `uv run --no-sync` を許容するが、project code には使わない
- **worktree 間の依存境界**: 共有するのは uv cache と pnpm content-addressable store だけとし、`.venv` / `node_modules` は各 worktree で生成する。親 checkout や sibling worktree の環境を symlink・コピーせず、branch ごとの lockfile、editable path、entry point を実行中 checkout と一致させる
- **診断**: 親 checkout / worktree のそれぞれで `bash .lefthook/setup-worktree.sh sh -c 'command -v lefthook && lefthook version'` を実行する。`git commit` / `git push` で `Can't find lefthook in PATH` が出る場合は `bash .lefthook/setup-worktree.sh` を再実行する。直接の Nix 診断・再生成には `nix develop --command sh -c 'command -v lefthook && lefthook version'` と `nix develop --command bash .lefthook/install.sh` も利用できる
- **失敗時の扱い**: shellHook は `lefthook` 不在や hook 再生成失敗を `|| true` で握りつぶさない。devShell 入室時に明示的に失敗させ、commit / push 時の hook no-op を防ぐ
- **TMPDIR の worktree 分離**: macOS の TMPDIR は per-user のグローバル値のため、複数 worktree の並列実行（takt の `concurrency > 1` / 手動 worktree の並行 pytest）が同一パスへ書くと一時ディレクトリが run 間で干渉しうる（issue #2088）。shellHook は `.lefthook/worktree-tmpdir.sh` の出力を `TMPDIR` へ export し、共有 TMPDIR 配下の worktree ごとの決定的なサブディレクトリ（`yt-automation-tmp-<slug>-<cksum>`）へ分離する。takt worker のように TMPDIR が既に checkout 内へ隔離済みの場合はその値を尊重し、解決に失敗した場合は共有 TMPDIR のまま fail-open で続行する
- **Nix キャッシュの worktree 分離**: 並列 worktree が同一 fingerprint の flake を同時評価すると、ユーザーグローバルの Nix キャッシュ（既定 `~/.cache/nix` の eval-cache / fetcher-cache SQLite）への同時書込みが競合し、「error (ignored): SQLite database ... is busy」を stderr へ出しつつキャッシュ書込みを破棄し続ける（issue #2089）。`.envrc` / `.lefthook/setup-worktree.sh` / shellHook は Nix 専用の `NIX_CACHE_HOME` を worktree 分離 TMPDIR 配下（`<worktree_tmpdir>/nix-cache`）へ export し、各 worktree が自分の評価結果だけを参照する。`XDG_CACHE_HOME` には触れないため uv 等の他ツールのキャッシュは共有のまま変わらない。継承値は別 worktree の値がシェル経由でリークし得るため尊重せず、解決に失敗した場合は共有キャッシュのまま fail-open で続行する
- **sandbox / takt worker での挙動**: repo-local takt config / workflow は持たず、taktを使う場合のprovider・workflow・runtime routingはグローバル `~/.takt/` を正とする。sandbox worker向けの `.takt/runtime-prepare.sh` は、グローバル側から明示的に呼ばれた場合に `XDG_DATA_HOME=<worktree>/.takt/.runtime/data` と `YOUTUBE_AUTOMATION_SKIP_LEFTHOOK=1` を注入する補助scriptとして残す。後者が設定された環境ではshellHook / `.lefthook/install.sh` がinstallを明示メッセージつきでskipする。また `.lefthook/setup-worktree.sh` は `direnv allow` 失敗時にhard failせず `nix develop` 経路へfallbackする
- **全 hook をスキップ**: `LEFTHOOK=0 git push` / `LEFTHOOK=0 git commit`
- **CHANGELOG ゲートのみ省く**: `SKIP_CHANGELOG=1 git push`（CI 側は PR の `skip-changelog` ラベル）
- **テスト差分警告のみ省く**: `SKIP_TEST_DIFF=1 git push`
- refactor / fix でも src を触れば CHANGELOG 追記が要る。tests / docs だけの変更はゲート対象外（hook も CI も自動 skip）

### CHANGELOG.md の union merge（conflict 緩和）

CHANGELOG ゲートにより並行 PR が `[Unreleased]` 先頭へ同時に追記するため、`.gitattributes` で `CHANGELOG.md merge=union` を指定している（issue #2155）。両側の追記行を conflict にせず機械的に取り込むが、union merge には以下の副作用があるため merge 後は `[Unreleased]` を目視確認すること:

- **重複行**: 両ブランチが同一内容の行を追記した場合、その行が 2 回残ることがある
- **順序非保証**: 追記行の並び順は merge 順に依存し、時系列と一致しない場合がある
- **削除・編集に非対応**: 行の追加以外（既存行の削除・書き換え）が絡む変更は正しく解決されない可能性がある。リリース時の `[Unreleased]` → バージョン節への移動のような大規模編集を含む PR は、merge 結果を必ず確認する
