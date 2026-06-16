# Plan 003: distrokid-helper に lint / format ゲートを追加し CI を suno-helper とパリティにする

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat fa296fe..HEAD -- extensions/distrokid-helper/package.json .github/workflows/extensions.yml extensions/suno-helper/eslint.config.js`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW（lint 初回適用で既存コードの違反が見つかる可能性あり — Steps 参照）
- **Depends on**: plans/002-distrokid-helper-dep-unification.md（同じ `package.json` を編集するため。002 未完了でも実行は可能だが conflict を避けるため後にする）
- **Category**: dx
- **Planned at**: commit `fa296fe`, 2026-06-12
- **Issue**: https://github.com/daiki-beppu/youtube-automation/issues/955

## Why this matters

同一リポジトリの 2 つの WXT 拡張のうち、suno-helper は CI で `pnpm lint`（ESLint flat config + typescript-eslint + react-hooks）と `pnpm format:check`（Prettier）を強制しているが、distrokid-helper には lint/format の script も設定ファイルも存在せず、CI（`.github/workflows/extensions.yml` の `distrokid-helper` ジョブ）は typecheck / build / test のみ。react-hooks の依存配列ミスのような lint で機械検出できるバグクラスが distrokid-helper だけ素通りし、コードスタイルも `extensions/shared/` を共有する suno-helper と乖離していく。このプランで suno-helper と同一の品質ゲートを distrokid-helper に張る。

## Current state

- `extensions/distrokid-helper/package.json` — scripts は現在 `dev / build / zip / compile / postinstall / test / test:watch / test:e2e` のみ（line 7-16）。`lint` / `format:check` なし。ESLint / Prettier 系の devDependencies もなし。
- `extensions/distrokid-helper/` に `eslint.config.js` は**存在しない**。
- `extensions/suno-helper/package.json:16-17` — 揃える先のパターン:

```json
    "lint": "cd .. && eslint -c suno-helper/eslint.config.js suno-helper shared",
    "format:check": "prettier --check . ../shared"
```

- `extensions/suno-helper/eslint.config.js`（23 行、全文）— これを distrokid-helper 用に複製する:

```js
import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    // suno-helper と sibling の ../shared を 1 回の実行で lint するため cwd=extensions/
    // から `--config` 経由で実行する（lint script 参照）。base path が extensions/ に
    // なるので、生成物の ignore は深さ非依存の `**/` 前置で各拡張配下を捕捉する。
    ignores: ["**/.wxt/**", "**/.output/**", "**/dist/**", "**/node_modules/**"],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    plugins: {
      "react-hooks": reactHooks,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
    },
  },
);
```

- suno-helper の lint/format 関連 devDependencies（exact pin、これと同じバージョンを追加する）: `@eslint/js 9.39.4` / `eslint 9.39.4` / `eslint-plugin-react-hooks 7.1.1` / `typescript-eslint 8.60.1` / `prettier 3.6.2`。
- `.github/workflows/extensions.yml` — `suno-helper` ジョブ（line 16-63）は install → **Lint（line 33-34: `run: pnpm lint`）→ Format check（line 35-36: `run: pnpm format:check`）** → compile → test → build → e2e。`distrokid-helper` ジョブ（line 65-91）は install（line 81）→ compile（line 83）→ build（line 85）→ test（line 87）→ playwright install（line 89）→ e2e（line 91）で、**Lint / Format check ステップがない**。
- suno-helper の `format:check` は `prettier --check . ../shared` — `../shared` は suno-helper のジョブが既にカバーしているため、distrokid-helper 側は二重チェックを避けて自拡張のみを対象にする（lint も同様に `shared` を含めない）。
- `extensions/` 配下は **`pnpm` 直接使用**（ni 規約の例外）。
- CHANGELOG ゲートの対象外（`extensions/` / `.github/` のみの変更）だが、習慣として `[Unreleased]` 追記を推奨。

## Commands you will need

| Purpose | Command（cwd: `extensions/distrokid-helper`） | Expected on success |
|---|---|---|
| Install | `pnpm install` | exit 0 |
| Lint | `pnpm lint` | exit 0 |
| Format | `pnpm format:check` | exit 0 |
| 型チェック | `pnpm compile` | exit 0 |
| Unit | `pnpm test` | all pass |
| CI 構文確認 | （リポジトリルート）`nlx action-validator .github/workflows/extensions.yml`（なければ `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/extensions.yml'))"`） | exit 0 |

## Scope

**In scope** (the only files you should modify):

- `extensions/distrokid-helper/package.json`（scripts + devDependencies 追加）
- `extensions/distrokid-helper/pnpm-lock.yaml`（再生成）
- `extensions/distrokid-helper/eslint.config.js`（新規作成）
- `extensions/distrokid-helper/.prettierignore`（必要な場合のみ新規作成 — suno-helper 側に同等ファイルがあるか `ls -a extensions/suno-helper` で確認し、あればそれに倣う）
- `.github/workflows/extensions.yml`（distrokid-helper ジョブへ 2 ステップ追加）
- `extensions/distrokid-helper/{lib,entrypoints,components,tests}/**/*.{ts,tsx}` — **lint / format の自動修正適用に限る**（`eslint --fix` / `prettier --write` 相当。ロジック変更は不可）
- `CHANGELOG.md`（推奨）

**Out of scope** (do NOT touch, even though they look related):

- `extensions/suno-helper/**` — 基準側。
- `extensions/shared/**` — suno-helper のジョブが既に lint/format 済み。二重適用しない。
- lint エラーを `eslint-disable` コメントの大量追加で黙らせること — 違反が 1〜2 件で機械修正不能な場合のみ、根拠コメント付きで個別 disable 可。それを超える場合は STOP。

## Git workflow

- worktree 必須: `git -C /Users/mba/02-yt/automation pull --ff-only && git -C /Users/mba/02-yt/automation worktree add .worktrees/dk-lint-ci -b chore/distrokid-helper-lint-format-ci`
- Commit 規約: 日本語 Conventional Commits。例: `chore(distrokid-helper): lint / format ゲートを追加し CI を suno-helper とパリティ化`
- push / PR 作成はオペレーターの指示があるまで行わない。

## Steps

### Step 1: eslint.config.js を作成し devDependencies を追加する

1. 上記 "Current state" の suno-helper の `eslint.config.js` 全文を `extensions/distrokid-helper/eslint.config.js` として作成する。コメント内の「suno-helper」への言及は「distrokid-helper」に書き換える。
2. `extensions/distrokid-helper/package.json` の devDependencies に追加（exact pin）: `"@eslint/js": "9.39.4"`, `"eslint": "9.39.4"`, `"eslint-plugin-react-hooks": "7.1.1"`, `"typescript-eslint": "8.60.1"`, `"prettier": "3.6.2"`。
3. scripts に追加:

```json
    "lint": "cd .. && eslint -c distrokid-helper/eslint.config.js distrokid-helper",
    "format:check": "prettier --check ."
```

4. `pnpm install` を実行する。

**Verify**: `pnpm install` → exit 0

### Step 2: lint / format を初回適用し、違反を機械修正する

```
pnpm lint
pnpm format:check
```

違反が出た場合:

- format 違反 → `pnpm exec prettier --write .` で一括修正。
- lint 違反のうち auto-fixable → `cd .. && pnpm --dir distrokid-helper exec eslint -c distrokid-helper/eslint.config.js distrokid-helper --fix` で修正。
- 残った違反が **5 件以下**なら、コードの意味を変えない最小修正（未使用変数の削除、`let`→`const` 等）を行う。react-hooks の依存配列警告は**安易に依存を足さず**、現挙動を変えないことを最優先に判断し、自信がなければ当該ルールのみ行単位 disable + 理由コメント。**6 件以上**残る場合は STOP。

**Verify**: `pnpm lint && pnpm format:check` → 両方 exit 0

### Step 3: 修正後の回帰確認

```
pnpm compile && pnpm test
```

（Step 2 でソースに触れていない場合もこの確認は行う。）

**Verify**: 両方 exit 0 / 全 pass

### Step 4: CI に Lint / Format check ステップを追加する

`.github/workflows/extensions.yml` の `distrokid-helper` ジョブ内、`Install dependencies`（`run: pnpm install --frozen-lockfile`、line 81 付近）の直後・compile の前に、suno-helper ジョブ（line 33-36）と同じ体裁で追加:

```yaml
      - name: Lint
        run: pnpm lint
      - name: Format check
        run: pnpm format:check
```

（step の name は suno-helper ジョブで使われている実際の name 文字列に合わせること。）

**Verify**: YAML が valid（Commands の CI 構文確認コマンド）→ exit 0

### Step 5: CHANGELOG 追記（推奨）

`CHANGELOG.md` の `[Unreleased]` に追記。

**Verify**: `git diff --stat` → in-scope ファイルのみ

## Test plan

新規テストなし。ゲート自体が成果物:

- `pnpm lint` / `pnpm format:check` / `pnpm compile` / `pnpm test` がすべて exit 0。
- Step 2 でソース修正が発生した場合、`pnpm test:e2e` も実行して全 pass を確認する。

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `extensions/distrokid-helper` で `pnpm lint && pnpm format:check && pnpm compile && pnpm test` がすべて exit 0
- [ ] `extensions/distrokid-helper/eslint.config.js` が存在する
- [ ] `grep -A1 '"lint"' extensions/distrokid-helper/package.json` が distrokid-helper を対象とした eslint 起動を含む
- [ ] `.github/workflows/extensions.yml` の distrokid-helper ジョブに Lint / Format check の 2 ステップが存在する（`grep -n "pnpm lint" .github/workflows/extensions.yml` が 2 箇所返す）
- [ ] `git status` で in-scope 外のファイルが変更されていない
- [ ] `plans/README.md` の status 行を更新済み

## STOP conditions

Stop and report back (do not improvise) if:

- 初回 lint で auto-fix 後も **6 件以上**の違反が残る（コード品質の問題が想定より深く、個別判断が必要）。
- react-hooks ルールの違反修正が popup の挙動（特に `App.tsx` の stale-closure 回避ロジック、line 113-114 のコメント参照）を変えうると判断した場合 — このファイルの依存配列は意図的な設計が含まれる。
- Plan 002 が未完了で、かつ `package.json` の devDependencies 編集が 002 の変更と衝突する場合。
- suno-helper の eslint/prettier バージョンが "Current state" の記載から変わっている場合（その時の suno-helper の値に合わせた上で続行してよいが、報告すること）。

## Maintenance notes

- 以後、distrokid-helper の PR は lint/format で落ちるようになる。開発者向けには `pnpm lint` / `pnpm exec prettier --write .` をローカルで回すのが標準フロー。
- `extensions/shared/` の lint は suno-helper ジョブが担う分担になっている。将来 suno-helper を削除・改名する場合は shared の lint 担当をこちらへ移すこと。
- レビューで見るべき点: Step 2 の自動修正 diff にロジック変更が紛れていないか（特に `App.tsx` と `distrokid-injector.ts`）。
