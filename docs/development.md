# 開発環境・パッケージング詳細

CLAUDE.md の「パッケージング」「extensions」「Git hooks」節の詳細版。要点（規約として常に守るもの）は CLAUDE.md を参照。

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
```

- **既定は直列**（`addopts` には入れない）。単一ファイル・単一テストのデバッグ実行で worker 起動オーバーヘッドを毎回払わないため、また `-x` / `--pdb` など直列前提のオプションと干渉しないため。フルスイートを回すときに明示的に `-n auto` を付ける
- **CI では `-n auto` を有効化済み**（`.github/workflows/ci.yml` の test ジョブ）
- worker ごとの分離: `tests/conftest.py` が `CHANNEL_DIR` の tmp コピーを **worker プロセスごとに独立して** 作り直す（controller が自動設定した値を環境変数継承でそのまま共有しない）。ユーザーが明示的に `CHANNEL_DIR` を指定した場合は全 worker がその指定を尊重する
- 注意: `tests/test_lefthook_installation_contract.py` の nix devShell 契約テストなど実 subprocess を叩くテストはホスト負荷に敏感で、混雑したマシンでは並列時に所要時間が大きく伸びることがある

## パッケージング

- `.claude/skills/` は `[tool.hatch.build.targets.wheel.force-include]` で wheel 内 `_skills/` に同梱され、`yt-skills sync` が `importlib.resources` で参照する
- `.claude/CLAUDE.template.md` も同様に `[tool.hatch.build.targets.wheel.force-include]` で wheel 内 `_claude_md/CLAUDE.template.md` に同梱され、`yt-skills sync --asset claude-md` で `.claude/CLAUDE.md` として展開される
- 配布アセットの追加は `src/youtube_automation/cli/skills_sync/__init__.py::_ASSET_SPECS` に entry を追加するだけで `list/sync/diff` が自動的にサポートされる（`kind="dir" | "file"` を選ぶ）
- `skills` asset を標準レイアウト（`.claude/skills`）へ sync すると、下流リポにも `.agents/skills -> ../.claude/skills` の相対 symlink を併設する（Codex CLI 探索パス規約）。既存の正しい symlink は冪等にスキップし、張り直しは `--force`、symlink 非対応環境では警告のみで sync は継続する（`_ops.py::_ensure_agents_skills_symlink`）
- バージョン bump は `pyproject.toml::version` のみを更新する（`src/youtube_automation/__init__.py::__version__` は `importlib.metadata` 経由で動的に読み込むため触らない）。リリース運用全体は `/automation-release` スキルで一気通貫に実行する

## 依存ポリシー: deprecated 表明済み依存の取り扱い（詳細）

- **`google-auth-httplib2`（PyPI 0.4.0 で deprecated 表明）**:
  - `src/youtube_automation/` / `tests/` 配下に `google_auth_httplib2` の **直 import を新規追加しない**（現状 0 件、回帰テスト `tests/test_no_google_auth_httplib2_direct_import.py` で機械担保）
  - 既存の transitive 依存は `googleapiclient.discovery.build(..., credentials=credentials)` 経由で残置する（上流 `google-api-python-client` が内部で `google_auth_httplib2.AuthorizedHttp` を要求しているため、即時撤去不可）
  - 上流が non-httplib2 transport（`google.auth.transport.requests` など）を正式サポートした際の移行手順・撤去判断は `docs/migration/google-auth-httplib2.md` を参照
  - `pyproject.toml::dependencies` の `"google-auth-httplib2"` 直接宣言の撤去は transport 切替完了後に別 issue で再検証する

## extensions（Chrome 拡張開発）

`extensions/` 配下の Chrome 拡張は **WXT + React + TypeScript + Tailwind CSS** スタックで開発する（Python 本体とは独立した Node ツールチェーン）。詳細は `extensions/README.md`。

- **ディレクトリ規約**: 各拡張は `extensions/<name>/` に WXT 規約（`entrypoints/` 構成）で配置。複数拡張で再利用する共通コードは `extensions/shared/`（契約定数 / API client / origin allowlist / DOM ヘルパ）に集約し、各拡張から相対 import（`../../shared/*`）で参照する
- **manifest は自動生成**: `manifest.json` を手書きせず `wxt.config.ts` から生成する。権限は最小権限を `lib/manifest.ts` の `MANIFEST_PERMISSIONS` 単一定数で宣言し、`wxt.config.ts` がそれを参照する（過剰権限の混入は Vitest で機械担保）
- **型安全**: 全 source を TypeScript で書き、`@types/chrome` で `chrome.*` を型付け。message は `@webext-core/messaging`、`chrome.storage` は `@wxt-dev/storage` の型付き wrapper を経由する
- **契約文字列**: サーバー（`yt-collection-serve`）との互換契約値（storage key / 配信ルート / phase 値）は `extensions/shared/constants.ts` の定数として 1 箇所で定義する。メッセージ種別（`run` / `stop` / `progress`）は各拡張の `lib/messaging.ts` で `@webext-core/messaging` の ProtocolMap として型付け定義する。ハードコーディング禁止
- **テスト必須**: unit は Vitest（`nix develop .#extensions --command pnpm -C extensions/<name> test`）、e2e は Playwright（初回に `nix develop .#extensions --command pnpm -C extensions/<name> exec playwright install --with-deps chromium`、実行は `nix develop .#extensions --command pnpm -C extensions/<name> test:e2e`。Suno UI / DistroKid UI mock への DOM 注入スモーク）。CI は `.github/workflows/extensions.yml` が同じ Nix 入口で lint / 型チェック / Vitest / Playwright を実行する
- **成果物は commit しない**: `node_modules/` / `dist/` / `.wxt/` / `.output/` は `.gitignore` 済み。配布は `release-extensions.yml` が tag push 時に zip を GitHub Release へ添付する
- **パッケージマネージャ**: 両拡張とも Nix extensions shell の Node 24 / pnpm 11.12.0 固定（`ni`/`nr`、ambient `pnpm`、`npx` は使わない）。`nix develop .#extensions --command pnpm ...` により、各 `package.json::packageManager`、コミット済み lockfile、`pnpm-workspace.yaml::allowBuilds` の依存 build script 承認、CI を揃える契約である。install は `--frozen-lockfile` を必須とし、`--ignore-workspace` は使用しない。両拡張共通の install / build / zip、生成 manifest / 期待名 zip の確認と lockfile 無差分確認は `extensions/README.md::pnpm バージョン契約` を正とする
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
- **診断**: 親 checkout / worktree のそれぞれで `bash .lefthook/setup-worktree.sh sh -c 'command -v lefthook && lefthook version'` を実行する。`git commit` / `git push` で `Can't find lefthook in PATH` が出る場合は `bash .lefthook/setup-worktree.sh` を再実行する。直接の Nix 診断・再生成には `nix develop --command sh -c 'command -v lefthook && lefthook version'` と `nix develop --command bash .lefthook/install.sh` も利用できる
- **失敗時の扱い**: shellHook は `lefthook` 不在や hook 再生成失敗を `|| true` で握りつぶさない。devShell 入室時に明示的に失敗させ、commit / push 時の hook no-op を防ぐ
- **TMPDIR の worktree 分離**: macOS の TMPDIR は per-user のグローバル値のため、複数 worktree の並列実行（takt concurrency 5 / 手動 worktree の並行 pytest）が同一パスへ書くと一時ディレクトリが run 間で干渉しうる（issue #2088）。shellHook は `.lefthook/worktree-tmpdir.sh` の出力を `TMPDIR` へ export し、共有 TMPDIR 配下の worktree ごとの決定的なサブディレクトリ（`yt-automation-tmp-<slug>-<cksum>`）へ分離する。takt worker のように TMPDIR が既に checkout 内へ隔離済みの場合はその値を尊重し、解決に失敗した場合は共有 TMPDIR のまま fail-open で続行する
- **sandbox / takt worker での挙動**: sandbox 化された takt worker はホーム配下（direnv の allow ストア `~/.local/share/direnv/allow` や共有 hooks ディレクトリ）へ書込みできないため、`.takt/config.yaml` の `runtime.prepare`（`.takt/runtime-prepare.sh`）が全 worker へ `XDG_DATA_HOME=<worktree>/.takt/.runtime/data`（direnv allow の書込み先を worktree 内に完結）と `YOUTUBE_AUTOMATION_SKIP_LEFTHOOK=1` を注入する。後者が設定された環境では shellHook / `.lefthook/install.sh` が lefthook install を明示メッセージつきでスキップする（CHANGELOG 等のゲートは CI 側で担保）。また `.lefthook/setup-worktree.sh` は `direnv allow` 失敗時に hard fail せず `nix develop` 経路へフォールバックする
- **全 hook をスキップ**: `LEFTHOOK=0 git push` / `LEFTHOOK=0 git commit`
- **CHANGELOG ゲートのみ省く**: `SKIP_CHANGELOG=1 git push`（CI 側は PR の `skip-changelog` ラベル）
- **テスト差分警告のみ省く**: `SKIP_TEST_DIFF=1 git push`
- refactor / fix でも src を触れば CHANGELOG 追記が要る。tests / docs だけの変更はゲート対象外（hook も CI も自動 skip）
