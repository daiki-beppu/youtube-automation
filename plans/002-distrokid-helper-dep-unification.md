# Plan 002: distrokid-helper の dev ツールチェーンを suno-helper と同一バージョンに統一する

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat fa296fe..HEAD -- extensions/distrokid-helper/package.json extensions/distrokid-helper/pnpm-lock.yaml extensions/distrokid-helper/vitest.config.ts extensions/distrokid-helper/playwright.config.ts`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none（ただし Plan 003 がこのプランの完了を前提とする）
- **Category**: tech-debt
- **Planned at**: commit `fa296fe`, 2026-06-12
- **Issue**: https://github.com/daiki-beppu/youtube-automation/issues/954

## Why this matters

同一リポジトリの 2 つの WXT 拡張（`extensions/suno-helper` と `extensions/distrokid-helper`）が共有コード `extensions/shared/` を相対 import で共用しているのに、dev ツールチェーンのバージョンが大きく乖離している: Vitest **2.1.8 vs 4.1.8**（メジャー 2 つ差）、Playwright **1.49.1 vs 1.60.0**、TypeScript **5.7.2 vs 5.9.3**、jsdom **25 vs 26**。さらに distrokid-helper はキャレット（`^`）指定、suno-helper は exact pin と指定スタイルも不一致。`shared/` にテストユーティリティや新しい TS 構文を追加するたびに両方のツールチェーンで動くか確認する負担が生じ、CI の挙動も拡張ごとに微妙に異なる。このプランで dev ツールチェーンを suno-helper の exact pin に揃える。

**意図的にスコープ外とするもの**: React のメジャー統一（distrokid 19 vs suno 18）と `@webext-core/messaging` のメジャー統一（2.1.0 vs 3.0.2）、`@wxt-dev/storage`（1.1.0 vs 1.2.8）。これらは**ランタイム依存**でリスクの質が違うため、別プランで実機スモーク（unpacked ロード → 実フォームでの fill 確認）込みでやるべき。本プランは devDependencies と指定スタイルの統一に限定する。

## Current state

- `extensions/distrokid-helper/package.json` — 対象ファイル。現状の関連バージョン（line 17-35）:

```json
  "dependencies": {
    "@webext-core/messaging": "^2.1.0",
    "@wxt-dev/storage": "^1.1.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "@playwright/test": "^1.49.1",
    "@types/react": "^19.0.2",
    "@types/react-dom": "^19.0.2",
    "@wxt-dev/module-react": "^1.1.3",
    "autoprefixer": "^10.4.20",
    "jsdom": "^25.0.1",
    "postcss": "^8.4.49",
    "tailwindcss": "^3.4.17",
    "typescript": "^5.7.2",
    "vitest": "^2.1.8",
    "wxt": "^0.20.0"
  }
```

- `extensions/suno-helper/package.json` — 揃える先の基準。関連 devDependencies（exact pin）:
  `@playwright/test 1.60.0` / `@wxt-dev/module-react 1.2.2` / `autoprefixer 10.5.0` / `jsdom 26.1.0` / `postcss 8.5.15` / `tailwindcss 3.4.19` / `typescript 5.9.3` / `vitest 4.1.8` / `wxt 0.20.26`。`pnpm.onlyBuiltDependencies: ["esbuild"]` も持つ。
- `extensions/distrokid-helper/vitest.config.ts` — 16 行。`defineConfig({ test: { setupFiles, include: ["tests/**/*.test.ts"], exclude: ["tests/e2e/**"] } })` のみのシンプル構成。Vitest 4 でもこの API は互換（`test.include/exclude/setupFiles` は 2→4 で存続）。
- `extensions/distrokid-helper/tests/setup.ts` — 12 行。fakeBrowser を chrome/browser グローバルへ注入。
- `extensions/distrokid-helper/playwright.config.ts` — Playwright 設定。1.49→1.60 は後方互換のはずだが、e2e 実行で確認する。
- パッケージマネージャ規約: extensions/ 配下は **`pnpm` を直接使う**（リポジトリ全体の ni 規約の例外。`extensions/README.md` / ルート CLAUDE.md 参照）。
- CHANGELOG ゲートの対象は `src/youtube_automation/` 等で `extensions/` は対象外だが、リポジトリの習慣として `CHANGELOG.md` の `[Unreleased]` に追記しておくのが安全。

## Commands you will need

| Purpose | Command（cwd: `extensions/distrokid-helper`） | Expected on success |
|---|---|---|
| Install | `pnpm install` | exit 0、lock 更新 |
| 型チェック | `pnpm compile` | exit 0（wxt prepare + tsc --noEmit） |
| Unit | `pnpm test` | all pass |
| Build | `pnpm build` | exit 0、`.output/chrome-mv3/` 生成 |
| e2e 準備 | `pnpm exec playwright install chromium` | exit 0（初回のみ） |
| e2e | `pnpm test:e2e` | all pass |

## Scope

**In scope** (the only files you should modify):

- `extensions/distrokid-helper/package.json`
- `extensions/distrokid-helper/pnpm-lock.yaml`（`pnpm install` による再生成）
- `extensions/distrokid-helper/vitest.config.ts` / `tests/setup.ts` / `tests/**/*.test.ts`（Vitest 4 の breaking change への追従が必要な場合のみ）
- `extensions/distrokid-helper/playwright.config.ts`（同上）
- `CHANGELOG.md`（`[Unreleased]` への追記）

**Out of scope** (do NOT touch, even though they look related):

- `dependencies`（react / react-dom / @webext-core/messaging / @wxt-dev/storage / @types/react / @types/react-dom）— ランタイム依存の統一は別プラン。バージョンを変えず、**キャレットの exact pin 化のみ**行う（lock の解決済みバージョンに固定）。
- `extensions/suno-helper/**` — 基準側。一切変更しない。
- `extensions/shared/**` — 変更不要。
- `lib/` / `entrypoints/` のソースコード — ツールチェーン更新で型エラーが出た場合は STOP（コード改変で握りつぶさない）。

## Git workflow

- worktree 必須: `git -C /Users/mba/02-yt/automation pull --ff-only && git -C /Users/mba/02-yt/automation worktree add .worktrees/dk-dep-unification -b chore/distrokid-helper-dep-unification`
- Commit 規約: 日本語 Conventional Commits。例: `chore(distrokid-helper): dev ツールチェーンを suno-helper と同一バージョンに統一`
- push / PR 作成はオペレーターの指示があるまで行わない。

## Steps

### Step 1: 現状の解決済みバージョンを記録する

`extensions/distrokid-helper` で `pnpm list --depth 0` を実行し、`dependencies` 4 件の解決済みバージョンを控える（Step 2 の exact pin 化に使う。例: react が `19.2.7` に解決されていればその値で pin）。

**Verify**: `pnpm list --depth 0` → エラーなく一覧が出る

### Step 2: package.json を更新する

`extensions/distrokid-helper/package.json` を編集:

1. devDependencies を suno-helper の値で exact pin に置換:
   - `@playwright/test`: `1.60.0`
   - `@wxt-dev/module-react`: `1.2.2`
   - `autoprefixer`: `10.5.0`
   - `jsdom`: `26.1.0`
   - `postcss`: `8.5.15`
   - `tailwindcss`: `3.4.19`
   - `typescript`: `5.9.3`
   - `vitest`: `4.1.8`
   - `wxt`: `0.20.26`
2. `dependencies` と `@types/react` / `@types/react-dom` は **Step 1 で控えた解決済みバージョンで exact pin 化のみ**（アップグレードしない）。
3. suno-helper に倣い `"pnpm": { "onlyBuiltDependencies": ["esbuild"] }` を追加する（未追加だと pnpm v10 系で esbuild の postinstall がブロックされ build が壊れることがある）。

その後 `pnpm install` を実行して lock を再生成する。

**Verify**: `pnpm install` → exit 0

### Step 3: 型チェックとユニットテスト

```
pnpm compile && pnpm test
```

Vitest 2→4 の主な breaking change で影響しうるのは workspace 設定・`poolOptions`・mock タイマー API だが、本プロジェクトの `vitest.config.ts` は素朴な構成のため原則そのまま通るはず。落ちた場合はエラーメッセージが指す**設定 API の名称変更のみ**追従する（テストの意味を変える書き換えはしない）。

**Verify**: `pnpm compile` → exit 0 / `pnpm test` → 全 pass（既存 9 テストファイル）

### Step 4: build と e2e

```
pnpm build && pnpm exec playwright install chromium && pnpm test:e2e
```

**Verify**: `pnpm build` → exit 0 / `pnpm test:e2e` → 全 pass

### Step 5: CHANGELOG 追記

`CHANGELOG.md` の `[Unreleased]` に追記（例: `### Changed` 配下に「distrokid-helper の dev ツールチェーン（Vitest 4 / Playwright 1.60 / TS 5.9 等）を suno-helper と統一し exact pin 化」）。

**Verify**: `git diff --stat` → in-scope ファイルのみが変更されている

## Test plan

新規テストは書かない（依存更新プラン）。既存スイートが回帰ゲート:

- `pnpm test` → Vitest unit 全 pass
- `pnpm test:e2e` → Playwright（モックフォーム `tests/e2e/fixtures/distrokid-new.html` への注入スモーク）全 pass

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `extensions/distrokid-helper` で `pnpm compile && pnpm test && pnpm build && pnpm test:e2e` がすべて exit 0
- [ ] `grep -c '"\^' extensions/distrokid-helper/package.json` → `0`（キャレット指定が残っていない）
- [ ] `grep '"vitest"' extensions/distrokid-helper/package.json` → `"vitest": "4.1.8"`
- [ ] `dependencies` の 4 パッケージの**メジャーバージョンが変わっていない**（`git diff extensions/distrokid-helper/package.json` で確認）
- [ ] `git status` で in-scope 外のファイルが変更されていない
- [ ] `plans/README.md` の status 行を更新済み

## STOP conditions

Stop and report back (do not improvise) if:

- Vitest 4 への更新で **2 つ以上のテストファイル**が設定変更では直らない実質的エラーを出す（API 互換性の想定が崩れている）。
- `pnpm compile` が `lib/` / `entrypoints/` のソース起因の型エラーを出す（TS 5.7→5.9 の挙動差。ソース改変はこのプランの権限外）。
- e2e が落ち、原因が Playwright のバージョン差と特定できない。
- wxt 0.20.26 への固定で `wxt prepare` / `wxt build` が失敗する。

## Maintenance notes

- 今後 `extensions/shared/` にテストを追加する場合、両拡張の Vitest が 4.x で揃ったため共通テストユーティリティを置きやすくなる。
- **明示的に先送りした follow-up**: ① React 19 vs 18 の統一（推奨: suno-helper を 19 へ上げる方向で実機スモーク込みの別プラン）、② `@webext-core/messaging` 2→3（メッセージング API の breaking change 調査が必要）、③ `@wxt-dev/storage` 1.1→1.2。
- レビューで見るべき点: `dependencies` のバージョン数値が lock の解決値と一致していること（pin 化に紛れた意図しない upgrade がないこと）。
