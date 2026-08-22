# Plan 033: changelog fragment 基盤を導入し CHANGELOG の並列マージコンフリクトを解消する

> **Executor instructions**: この plan を上から順に実行すること。各 step の
> Verify コマンドを実行し、期待結果を確認してから次へ進む。「STOP conditions」
> のいずれかが発生したら改善を試みず停止して報告する。完了したら
> `plans/README.md` の本 plan の Status 行を更新する。
>
> **Drift check (最初に実行)**: `git diff --stat 0030e636..HEAD -- .github/workflows/ci.yml .github/PULL_REQUEST_TEMPLATE.md tests/repo/test_changelog_ci_contract.py .claude/settings.json .claude/skills/automation-release/ docs/changelog-contract.md docs/development.md pyproject.toml src/youtube_automation/entrypoints.py`
> in-scope ファイルに変更があれば「Current state」の excerpt と実物を突き合わせ、
> 不一致なら STOP。

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED（リリースパイプラインの契約に触れる。ただし変更は `[Unreleased]` の書き溜め方に閉じ、リリース済み section 以降の下流契約は不変）
- **Depends on**: none（028〜032 より**先に**実行する。028〜032 は本 plan の完了後、CHANGELOG 直接編集の代わりに fragment を使う）
- **Category**: dx
- **Planned at**: commit `0030e636`, 2026-08-22
- **Issue**: https://github.com/daiki-beppu/youtube-automation/issues/4483

## Why this matters

現行の CHANGELOG 運用は「src/ 等を触る全 PR が `CHANGELOG.md` の `[Unreleased]` 先頭に 1 行足す」設計で、並列 PR が必ず同一ファイルの同一領域を編集するため、マージのたびに conflict → rebase の直列化が起きる。takt の並列駆動と構造的に噛み合わない。towncrier 型の fragment 方式（1 PR = 1 新規ファイルを `changelog.d/` に追加、リリース時にコンパイル）に切り替えると、conflict が原理的に消える。site（リリースノート静的サイト）と下流 `/automation --update` はリリース済み version section / GitHub Release body しか読まないため影響ゼロ — 変更は `[Unreleased]` を直接見る 5 消費者（CI ゲート / 契約テスト / PR テンプレート / settings hook / automation-release 昇格手順）に閉じる。

## Current state

- `CHANGELOG.md` — Keep a Changelog 1.1.0 準拠。`## [Unreleased]` が常に先頭、サブセクションは `### Added / Changed / Deprecated / Removed / Fixed / Security / Migration`（契約: `docs/changelog-contract.md`）。
- `.github/workflows/ci.yml:217-246` — `changelog` job。`skip-changelog` ラベルで免除、対象パス regex `^(src/youtube_automation/|\.claude/skills/|\.claude/CLAUDE\.template\.md$|pyproject\.toml$)` に diff が触れたら `^CHANGELOG\.md$` の diff を要求:
  ```bash
  if ! echo "$changed" | grep -q '^CHANGELOG\.md$'; then
    echo "::error::CHANGELOG.md must be updated under [Unreleased]. Add an entry or apply 'skip-changelog' label."
    exit 1
  fi
  ```
- `tests/repo/test_changelog_ci_contract.py` — この job を**行単位で固定**する契約テスト。`_CHANGELOG_GATED_PATHS`（ゲート対象パスの単一ソース）、`_CHANGELOG_FILE_PATTERN = "^CHANGELOG\\.md$"`、`_EXPECTED_RUN_LINES`、エラー文言、そして **`_PR_TEMPLATE_TEXT` が `.github/PULL_REQUEST_TEMPLATE.md` と byte 一致することも assert している**。CI 側を変えたらこのテストの定数を同時に変える必要がある。
- `.github/PULL_REQUEST_TEMPLATE.md:11-12` — チェックリスト「`CHANGELOG.md::[Unreleased]` にエントリを追加した / 免除する場合は `skip-changelog` ラベル」。
- `.claude/settings.json:43` — PostToolUse hook がゲート対象パス編集時に「CHANGELOG.md [Unreleased] に追記すること」と stderr で注意喚起する。
- `.claude/skills/automation-release/references/changelog-promotion.md` — prepare Phase 1-4 の `[Unreleased]` → `[VER]` 昇格手順（3 段階: 新セクション挿入 → 内容移動 → リンク参照追記）。`references/prepare-checklist.md` にチェックリストがある。
- `docs/changelog-contract.md` — CHANGELOG / Release body の**インターフェース契約**。パース側は (1) prepare の `### Migration` warning 検証（`[Unreleased]` 配下）、(2) 下流 `/automation --update`（Release body → リリース済み section fallback）、(3) libecity digest。**(2)(3) はリリース済み section しか読まないため本 plan の影響外**。
- `docs/development.md:275` 付近 — 品質ゲートは CI 一元担保（lefthook 廃止済み）の記述。
- 新規 CLI の規約（`CLAUDE.md`）: `yt-*` プレフィックスで `pyproject.toml::[project.scripts]` に登録、実装は `src/youtube_automation/commands/` 配下、`entrypoints.py` の文字列 dispatch に追加、引数は `choices=` / `help=` で自己記述。既存例: `src/youtube_automation/commands/system/` 配下の `preflight.py` 等。
- 例外は `core/errors.py` のドメイン例外を使う（生 `Exception` を catch しない）。パッケージ内 import は fully-qualified 固定。

## 設計（この plan で確定済みの判断）

- **fragment 置き場**: リポジトリルート `changelog.d/`。`README.md`（書き方ガイド）を常駐させ、コンパイラは `README.md` を無視する。
- **ファイル名**: `<issue番号>-<slug>.<type>.md`。`<type>` ∈ `added | changed | fixed | removed | deprecated | security | migration`（changelog-contract のサブセクション名の小文字）。issue 番号が無い場合は PR 番号または日付 slug。例: `4460-delete-suno-prompts-fork.chore.md` は**不可**（`chore` は type に無い）→ `4460-delete-suno-prompts-fork.removed.md`。
- **fragment の中身**: CHANGELOG に載せたい bullet 行そのもの（`- ` 始まり、複数行可、日本語・技術ログのトーン）。
- **コンパイル**: 新 CLI `yt-changelog-compile`。動作: `changelog.d/*.md`（README 除く）を type 別に集約し、`CHANGELOG.md` の `## [Unreleased]` 配下へ契約順（Added → Changed → Deprecated → Removed → Fixed → Security → Migration）の `### <Type>` 見出しの下に追記して fragment を削除する。既存の `### <Type>` 見出しがあればそこへ追記、無ければ作る。fragment ゼロなら何もせず exit 0（冪等）。`--dry-run` で書き込みなしのプレビュー。
- **Migration の契約は不変**: `migration` type の fragment は `### Migration` の `サマリ:` 配下 bullet としてのみ追記する。`所要時間の目安` / `local fix 衝突注意` の行は従来どおりリリース prepare 時に人手（automation-release）で整える。
- **CI ゲートは OR 判定（後方互換）**: 「`changelog.d/` に新規ファイル追加 **または** `CHANGELOG.md` に diff」で pass。移行期間中の in-flight PR（例: plans 028〜032 起票分）を壊さない。
- **リリースフローへの組み込み**: `/automation-release` prepare の昇格手順の**前**に `uv run yt-changelog-compile` を 1 step 追加。コンパイル後は従来手順のまま昇格するため、リリース済み section・Release body・`docs/release-notes/`・site の形は一切変わらない。

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| 単体テスト | `nix develop --command uv run pytest tests/commands/system/ tests/repo/test_changelog_ci_contract.py -q` | all pass |
| CLI 動作確認 | `nix develop --command uv run yt-changelog-compile --dry-run` | exit 0、fragment 一覧 or 「対象なし」表示 |
| Ruff | `nix develop --command uv run ruff check src tests` | exit 0 |
| 契約テスト全体 | `nix develop --command uv run pytest tests/repo/ -q` | all pass |
| workflow YAML 検証 | `nix develop --command uv run python -c "import yaml,io;yaml.safe_load(open('.github/workflows/ci.yml'))"` | exit 0 |

## Scope

**In scope**:
- 新規: `changelog.d/README.md`、`src/youtube_automation/commands/system/changelog_compile.py`、`tests/commands/system/test_changelog_compile.py`
- 編集: `pyproject.toml`（[project.scripts] に `yt-changelog-compile`）、`src/youtube_automation/entrypoints.py`（dispatch 追加）、`.github/workflows/ci.yml`（changelog job の判定）、`tests/repo/test_changelog_ci_contract.py`（定数・期待行・PR テンプレート本文）、`.github/PULL_REQUEST_TEMPLATE.md`（チェックリスト文言）、`.claude/settings.json`（hook 文言）、`.claude/skills/automation-release/references/changelog-promotion.md` と `references/prepare-checklist.md`（compile step 追加）、`docs/changelog-contract.md`（fragment 節の追加）、`docs/development.md`（ゲート説明の更新）、`changelog.d/4483-changelog-fragments.changed.md`（dogfood — 本変更自身のエントリを fragment で書く）

**Out of scope**:
- `CHANGELOG.md` のリリース済み section・リンク参照定義 — 一切触らない。
- `docs/release-notes/` / `site/` — 影響ゼロ（リリース済み section しか読まない）。触らない。
- `/automation --update`（下流追従）と libecity digest の抽出ロジック — Release body / リリース済み section 消費のため不変。
- `skip-changelog` ラベルの意味・免除条件 — 変えない。
- towncrier 等の外部ツール導入 — しない（契約書式が特殊なため自前の薄い実装。依存も増やさない）。

## Git workflow

- issue 専用 linked worktree 上で作業（`$REPO_ROOT/.claude/worktrees/<slug>/`）
- Branch: `advisor/033-changelog-fragments`
- Commit: `feat(dx): changelog fragment 基盤を導入し並列 PR の CHANGELOG conflict を解消 (#<issue番号>)`（1 branch 1 commit）
- push / PR 作成はオペレーター指示があるまで行わない

## Steps

### Step 1: fragment ディレクトリと書き方ガイドを作る

`changelog.d/README.md` を新規作成。内容: 上の「設計」節のファイル名規約・type 一覧・中身の書式・「リリース時に `yt-changelog-compile` が `[Unreleased]` へ集約して削除する」ことを簡潔に記す（`docs/changelog-contract.md` へのリンク付き）。

**Verify**: `test -f changelog.d/README.md` → exit 0

### Step 2: コンパイラ CLI を実装する

`src/youtube_automation/commands/system/changelog_compile.py` を新規作成:

- `main()` + argparse。`--dry-run`（書き込みなしでプレビュー）、`--changelog`（既定 `CHANGELOG.md`）、`--fragments-dir`(既定 `changelog.d`)。`help=` で自己記述。
- 処理: fragments-dir の `*.md`（`README.md` 除外）を `<name>.<type>.md` としてパースし、type を `{added, changed, deprecated, removed, fixed, security, migration}` で検証（不正 type は `ConfigError` 系のドメイン例外で明示 fail）。type 別に本文を集約し、`## [Unreleased]` 配下の対応する `### <Type>` 見出しへ追記（見出しが無ければ契約順の位置に作る）。`migration` は `### Migration` の `サマリ:` 配下へ bullet 追記のみ。成功したら fragment ファイルを削除。fragment ゼロなら「no fragments」を表示して exit 0。
- `pyproject.toml` の `[project.scripts]` に `yt-changelog-compile = "youtube_automation.entrypoints:yt_changelog_compile"` を追加し、`entrypoints.py` に既存エントリと同形式の dispatch 関数を追加する（既存の `yt_preflight` 等の実装形式を踏襲）。

**Verify**: `nix develop --command uv run yt-changelog-compile --dry-run` → exit 0

### Step 3: 単体テストを書く

`tests/commands/system/test_changelog_compile.py` を新規作成（既存の `tests/commands/system/` のテストを構造の手本にする）。tmp_path に CHANGELOG と fragments を作って検証:

1. added/fixed 混在の fragment 2 本 → `[Unreleased]` の正しい見出し配下に追記され fragment が消える
2. 既存 `### Fixed` 見出しがある場合 → 重複見出しを作らず追記
3. `migration` fragment → `### Migration` の `サマリ:` 配下にのみ追記（所要時間行を生成しない）
4. fragment ゼロ → CHANGELOG 不変・exit 0
5. 不正 type（`foo.chore.md`）→ ドメイン例外で fail
6. `--dry-run` → CHANGELOG・fragment とも不変
7. 冪等性: 2 回目の実行で変化なし
8. `README.md` が無視される

**Verify**: `nix develop --command uv run pytest tests/commands/system/test_changelog_compile.py -q` → 8 テスト pass

### Step 4: CI ゲートを OR 判定へ変更する

`.github/workflows/ci.yml` の changelog job の run スクリプトで、`^CHANGELOG\.md$` 単独チェックを次に置換:

```bash
if ! echo "$changed" | grep -qE '^(CHANGELOG\.md|changelog\.d/.+\.md)$'; then
  echo "::error::Add a changelog fragment under changelog.d/ (or update CHANGELOG.md), or apply 'skip-changelog' label."
  exit 1
fi
```

（`changelog.d/README.md` 自体の編集もマッチするが許容 — 誤 pass の実害は無い。）

**Verify**: workflow YAML 検証コマンド → exit 0

### Step 5: 契約テストと PR テンプレートを同期する

- `tests/repo/test_changelog_ci_contract.py`: `_CHANGELOG_FILE_PATTERN` を新 regex に、`_EXPECTED_RUN_LINES` とエラー文言 assert を Step 4 の実体に合わせて更新。`_CHANGELOG_GATED_PATHS`（対象パス）は**変えない**。
- `.github/PULL_REQUEST_TEMPLATE.md`: チェックリスト 1 項目目を「`changelog.d/` に fragment を追加した（書き方: `changelog.d/README.md`。`CHANGELOG.md` 直接編集も可）」の趣旨に更新。
- 同テストの `_PR_TEMPLATE_TEXT` を**新テンプレートと byte 一致**するよう更新（このテストはテンプレート全文を固定している）。

**Verify**: `nix develop --command uv run pytest tests/repo/test_changelog_ci_contract.py -q` → all pass

### Step 6: settings hook と automation-release 手順を更新する

- `.claude/settings.json:43` の hook 文言を「`changelog.d/` に fragment（`<issue>-<slug>.<type>.md`）を追加すること（CHANGELOG.md 直接編集も可、skip-changelog で escape 可）」の趣旨へ変更（hook の構造・対象パスは変えない）。
- `.claude/skills/automation-release/references/changelog-promotion.md`: 昇格手順の前に「Step 0: `uv run yt-changelog-compile` を実行し fragment を `[Unreleased]` へ集約する（fragment ゼロなら no-op）。実行後 `changelog.d/` に `README.md` 以外が残っていないことを確認」を追加。
- `references/prepare-checklist.md`: 対応するチェック項目を追加。

**Verify**: `nix develop --command uv run pytest tests/repo/ -q` → all pass（automation-release 系の契約テストが文言を pin している場合はここで検出される — fail したら該当テストの期待値を実文言に同期）

### Step 7: ドキュメントと dogfood エントリ

- `docs/changelog-contract.md`: 「fragment 運用（書き溜め方）」の節を追加 — `[Unreleased]` の実体は変わらず、書き込み経路が fragment 経由になること、パース側 3 者への影響なしを明記。
- `docs/development.md`: 品質ゲート節の CHANGELOG 記述を fragment 前提に更新。
- `changelog.d/4483-changelog-fragments.changed.md` を作成し、本変更自身のエントリを fragment として書く（CHANGELOG.md は直接編集しない — これが新ゲートの初回実証になる）。

**Verify**:
- `nix develop --command uv run yt-changelog-compile --dry-run` → 作った fragment 1 本がプレビューに出る（**実行はしない** — コンパイルはリリース時）
- `nix develop --command uv run pytest tests/ -q` → all pass
- `nix develop --command uv run ruff check src tests` → exit 0

## Test plan

Step 3 の単体テスト 8 本 + Step 5 の契約テスト同期が本体。既存の `tests/repo/` 全体（automation-release / skill docs 整合系の契約テスト群）のグリーンで、文言 pin の取りこぼしを検出する。site / 下流への無影響は「リリース済み section を触らない」ことが構造的保証なので、`tests/repo/test_site_repository_contract.py` を含む repo テスト全体が通れば十分。

## Done criteria

- [ ] `changelog.d/README.md` が存在し、`yt-changelog-compile` が pyproject / entrypoints に登録されている
- [ ] `nix develop --command uv run yt-changelog-compile --dry-run` が exit 0
- [ ] ci.yml の changelog job が fragment OR CHANGELOG.md の OR 判定になっている
- [ ] `nix develop --command uv run pytest tests/ -q` が exit 0（新規 8 テスト含む）
- [ ] `.github/PULL_REQUEST_TEMPLATE.md` と `_PR_TEMPLATE_TEXT` が byte 一致
- [ ] 本変更自身のエントリが `changelog.d/` の fragment として存在する（CHANGELOG.md の `[Unreleased]` は未編集）
- [ ] `CHANGELOG.md` のリリース済み section に diff が無い（`git diff CHANGELOG.md` が空）
- [ ] In scope 外の変更がない
- [ ] `plans/README.md` の Status 行を更新した

## STOP conditions

- `tests/repo/test_changelog_ci_contract.py` の構造が Current state の記述（定数群 + `_PR_TEMPLATE_TEXT` byte 一致 assert）と大きく異なる（契約の作り直しが挟まった可能性 — 前提再確認が必要）。
- automation-release 系の契約テストが changelog-promotion.md の**手順構造そのもの**を固定していて、Step 0 追加が「期待値の同期」で済まない場合。
- `docs/changelog-contract.md` のパース側に、`[Unreleased]` を機械パースする**第 4 の消費者**が見つかった場合（本 plan の影響範囲分析が崩れる）。
- fragment の type 体系が Keep a Changelog のサブセクションと一致しない要求が判明した場合。

## Maintenance notes

- **後続の plans 028〜032**（issue #4460〜#4464）は、本 plan マージ後は CHANGELOG.md 直接編集の代わりに `changelog.d/<issue>-<slug>.<type>.md` を追加する（各 plan にその旨の条件分岐を記載済み）。これで 5 本が完全並列でマージ可能になる。
- OR 判定（CHANGELOG.md 直接編集も pass）は移行期の互換措置。fragment 運用が定着したら、直接編集 pass を落として fragment 必須へ絞る後続変更を検討する（その際は本 plan の Step 4/5 と同じ 2 ファイル同期）。
- レビューで見るべき点: (1) コンパイラが `[Unreleased]` **以外**の section に書き込まないこと、(2) Migration の契約必須要素（所要時間行等）を生成**しない**こと（それは prepare の人手領分）、(3) `_PR_TEMPLATE_TEXT` の byte 一致。
