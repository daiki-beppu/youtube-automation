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
uv run yt-config-migrate diff                        # 旧 channel_config.json → 責務別分割のプレビュー
uv run yt-config-migrate migrate --apply             # 実際に分割実行
uv run yt-config-migrate verify                      # 新 loader で読み込み検証
```

## パッケージング

- `.claude/skills/` は `[tool.hatch.build.targets.wheel.force-include]` で wheel 内 `_skills/` に同梱され、`yt-skills sync` が `importlib.resources` で参照する
- `.claude/CLAUDE.template.md` も同様に `[tool.hatch.build.targets.wheel.force-include]` で wheel 内 `_claude_md/CLAUDE.template.md` に同梱され、`yt-skills sync --asset claude-md` で `.claude/CLAUDE.md` として展開される
- 配布アセットの追加は `src/youtube_automation/cli/skills_sync.py::_ASSET_SPECS` に entry を追加するだけで `list/sync/diff` が自動的にサポートされる（`kind="dir" | "file"` を選ぶ）
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
- **テスト必須**: unit は Vitest（`pnpm test`）、e2e は Playwright（`pnpm test:e2e`、Suno UI mock への DOM 注入スモーク）。CI は `.github/workflows/extensions.yml` が lint / 型チェック / Vitest / Playwright を実行する
- **成果物は commit しない**: `node_modules/` / `dist/` / `.wxt/` / `.output/` は `.gitignore` 済み。配布は `release-extensions.yml` が tag push 時に zip を GitHub Release へ添付する
- **パッケージマネージャ**: `pnpm`（`ni`/`nr` ではなく直接 `pnpm` を使う。WXT/Playwright の前提）

## Git hooks（lefthook）

Git hooks は [lefthook](https://lefthook.dev) で宣言的に管理する（設定は `lefthook.yml`）。

- **pre-commit**: 変更した Python ファイルに `ruff check` / `ruff format --check` をかける（CI の lint ジョブと同等）
- **pre-push**:
  - CHANGELOG ゲート。CI（`.github/workflows/ci.yml` の `changelog` ジョブ）と同じく、実コード（`src/youtube_automation/` / `.claude/skills/` / `.claude/CLAUDE.template.md` / `pyproject.toml`）を変更したのに `CHANGELOG.md` の `[Unreleased]` が未更新なら push を止める。ロジック本体は `.lefthook/pre-push/changelog-gate.sh`。lefthook は同一 hook で `use_stdin` を持てるコマンドを 1 つに制限するため、このスクリプトが pre-push の唯一の stdin 受信者としてブランチ削除 push を判定し、末尾でテスト差分警告・型注釈ゲートを連鎖実行する（削除 push はこの 3 ゲートすべてが対象外）
  - テスト差分警告。`src/youtube_automation/` に差分があるのに `tests/` の差分がない場合、または `extensions/*/lib/` に差分があるのに extensions 配下の `*.test.ts` 差分がない場合に警告を出す。これは粗い検出なので push は止めない。意図的に省く場合は `SKIP_TEST_DIFF=1 git push` とし、skip した事実を hook 出力に残す。ロジック本体は `.lefthook/pre-push/test-diff-gate.sh`
  - 広すぎる型注釈ゲート。`origin/main` からの新規追加行だけを対象に、ディレクトリを問わず全 `*.py` / `*.ts` / `*.tsx` の Python の typing module 経由の Any 型（`typing.Any` の修飾形と、`from typing import Any` の直接 import 経由で使う裸の `Any` の両方）、または TypeScript の any 型注釈を検出したら push を止める。既存行は対象外。ロジック本体は `.lefthook/pre-push/any-usage-gate.sh`

Python 側の未使用コード検出は、追加依存なしで CI / pre-commit に載っている Ruff `F` 系（未使用 import / 変数、未定義名など）を継続採用する。vulture は新規依存追加が必要で、Ruff `ARG` は既存コードに多数の既存違反があるため #1510 では採用しない。TS 側の未使用 export / dead code は CI の `ts-knip` で検出する。

有効化と運用:

- **有効化**: `nix develop`（または direnv `use flake`）で devShell に入ると `flake.nix` の shellHook が `lefthook install` を自動実行する。手動なら `lefthook install`（クローン後 1 回）
- **全 hook をスキップ**: `LEFTHOOK=0 git push` / `LEFTHOOK=0 git commit`
- **CHANGELOG ゲートのみ省く**: `SKIP_CHANGELOG=1 git push`（CI 側は PR の `skip-changelog` ラベル）
- **テスト差分警告のみ省く**: `SKIP_TEST_DIFF=1 git push`
- refactor / fix でも src を触れば CHANGELOG 追記が要る。tests / docs だけの変更はゲート対象外（hook も CI も自動 skip）
