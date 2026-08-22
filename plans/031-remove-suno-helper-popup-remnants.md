# Plan 031: suno-helper の廃止済み popup 残骸を物理削除し README を実態に合わせる

> **Executor instructions**: この plan を上から順に実行すること。各 step の
> Verify コマンドを実行し、期待結果を確認してから次へ進む。「STOP conditions」
> のいずれかが発生したら改善を試みず停止して報告する。完了したら
> `plans/README.md` の本 plan の Status 行を更新する。
>
> **Drift check (最初に実行)**: `git diff --stat 0030e636..HEAD -- extensions/suno-helper/entrypoints/popup extensions/suno-helper/tests/popup-entrypoint.test.tsx extensions/suno-helper/wxt.config.ts extensions/README.md extensions/suno-helper/README.md`
> in-scope ファイルに変更があれば「Current state」の excerpt と実物を突き合わせ、
> 不一致なら STOP。

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: 033 (soft — CHANGELOG は fragment 方式で書く。033 が未マージの場合のみ CHANGELOG.md 直接編集に fallback)
- **Category**: tech-debt
- **Planned at**: commit `0030e636`, 2026-08-22
- **Issue**: https://github.com/daiki-beppu/youtube-automation/issues/4463

## Why this matters

suno-helper の popup は #892 で廃止され、`wxt.config.ts` の `filterEntrypoints` が build から除外している。コード上のコメントに「物理削除は後続 PR に委ねる」と明記されたまま、その後続 PR が来ないまま約 2000 PR 経過した。dead な React entry + HTML + CSS が毎 CI で typecheck / lint され、**dead code の起動だけを assert する 44 行のテスト**まで維持されている。さらに `extensions/README.md` と `extensions/suno-helper/README.md` が popup を現役サーフェスとして説明しており、新規貢献者・エージェントの mental model を汚染している。明示的に先送りされた削除を完了させる。

## Current state

- `extensions/suno-helper/wxt.config.ts:38-42` — 廃止の根拠と残置の経緯:
  ```ts
  // popup 廃止 (#892 要件5): popup entrypoint を build 対象から外し manifest の default_popup を未指定化する。
  // これにより action クリックで chrome.action.onClicked が発火し overlay 表示を toggle できる。
  // popup のソース (entrypoints/popup/) はファイルとして残置し、物理削除は後続 PR に委ねる (order.md スコープ外)。
  // suno-bridge は MAIN world の fetch 観測 bridge (#948)。
  filterEntrypoints: ["background", "content", "overlay", "suno-bridge"],
  ```
- 削除対象（tracked 4 ファイル）:
  - `extensions/suno-helper/entrypoints/popup/index.html`
  - `extensions/suno-helper/entrypoints/popup/main.tsx`（`../../components/App` を StrictMode で mount するだけの 17 行）
  - `extensions/suno-helper/entrypoints/popup/style.css`
  - `extensions/suno-helper/tests/popup-entrypoint.test.tsx`（`vi.mock("../components/App")` して popup main が mount することだけを検証）
- README の stale 記述（修正対象）:
  - `extensions/README.md:20` — `entrypoints/          # background / content / popup`
  - `extensions/README.md:21` — `components/           # popup の React UI`
  - `extensions/suno-helper/README.md:16` — `| `entrypoints/popup/` | popup の HTML / エントリ（React + Tailwind） |`
  - `extensions/suno-helper/README.md:17` — `| `components/` | popup UI（`App.tsx` / ...）|`
  - `extensions/suno-helper/README.md:24,28,101` — 本文中の「popup に理由を表示」等の記述（実際の表示先は overlay）。
- `components/App.tsx` は overlay entrypoint から現役で使われている（**削除しない**）。`extensions/suno-helper/tests/popup-compatibility.test.ts`（4495 行）は名前に popup とあるが **App = overlay UI の behavioral テスト**であり現役（**削除しない**。rename は本 plan のスコープ外）。
- リポジトリ規約: extensions のツールチェーンは pnpm + nix devShell（`.#extensions`）。CI は `.github/workflows/extensions.yml` の suno ジョブが `check`（ultracite）/ `compile` / `test` / `build` / `audit`（fallow）を回す。

## Commands you will need

すべて `extensions/suno-helper/` で実行（`nix develop .#extensions --command` プレフィックス必須。依存が無ければ最初に install）:

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install | `nix develop .#extensions --command pnpm install --frozen-lockfile` | exit 0 |
| Lint/format | `nix develop .#extensions --command pnpm check` | exit 0 |
| Typecheck | `nix develop .#extensions --command pnpm compile` | exit 0 |
| Unit tests | `nix develop .#extensions --command pnpm test` | all pass |
| Build | `nix develop .#extensions --command pnpm build` | exit 0 |

## Scope

**In scope**:
- 削除: `extensions/suno-helper/entrypoints/popup/`（3 ファイル）、`extensions/suno-helper/tests/popup-entrypoint.test.tsx`
- 編集: `extensions/suno-helper/wxt.config.ts`（コメントのみ）、`extensions/README.md`、`extensions/suno-helper/README.md`、`CHANGELOG.md`

**Out of scope**:
- `extensions/suno-helper/components/App.tsx` と `tests/popup-compatibility.test.ts` — App は overlay の現役 UI。誤名テストの rename は別課題（第 6 回監査の未選択 finding）。
- `filterEntrypoints` の値そのもの — `["background", "content", "overlay", "suno-bridge"]` は変更しない（popup は元から含まれていない）。
- distrokid-helper / community-helper — popup を持ったことがない。

## Git workflow

- issue 専用 linked worktree 上で作業（`$REPO_ROOT/.claude/worktrees/<slug>/`）
- Branch: `advisor/031-remove-suno-popup-remnants`
- Commit: `chore(extensions): suno-helper の廃止済み popup ソースを物理削除 (#<issue番号>)`（1 branch 1 commit）
- push / PR 作成はオペレーター指示があるまで行わない

## Steps

### Step 1: popup ソースとテストを削除する

```bash
git rm -r extensions/suno-helper/entrypoints/popup
git rm extensions/suno-helper/tests/popup-entrypoint.test.tsx
```

**Verify**: `git ls-files extensions/suno-helper/entrypoints/` → `background.ts` / `content.ts` / overlay 系 / `suno-bridge` 系のみ（popup が無い）

### Step 2: wxt.config.ts のコメントを更新する

38-40 行の 3 行コメントを、現状を表す形に縮める（例）:

```ts
// popup は #892 要件5 で廃止済み（ソースも削除済み）。action クリックは chrome.action.onClicked で overlay を toggle する。
```

`filterEntrypoints` の配列は変更しない。

**Verify**: `git diff extensions/suno-helper/wxt.config.ts` → コメント行のみの変更

### Step 3: README 2 本を実態に合わせる

- `extensions/README.md:20-21` を `entrypoints/  # background / content / overlay` / `components/  # overlay の React UI` の趣旨に修正。
- `extensions/suno-helper/README.md:16-17` の表から `entrypoints/popup/` 行を削除し、`components/` の説明を overlay UI に修正。24 / 28 / 101 行の「popup に表示」を「overlay に表示」へ修正（機能説明は変えない。表示先の名称だけ直す）。

**Verify**: `git grep -n "popup" extensions/README.md extensions/suno-helper/README.md` → 残るのは「popup は廃止済み」という説明文脈のみ（現役サーフェスとしての記述ゼロ）

### Step 4: ツールチェーンを全部通す

**Verify**（すべて `extensions/suno-helper/` で）:
- `pnpm check` → exit 0
- `pnpm compile` → exit 0
- `pnpm test` → all pass（popup-entrypoint 分のテスト数が減る）
- `pnpm build` → exit 0（出力 `.output/` に popup が無いこと）

### Step 5: CHANGELOG 追記

エントリ文面:

```
- suno-helper: #892 で廃止済みだった popup のソース残骸（entrypoints/popup/ とそのテスト）を物理削除し、README の popup 記述を overlay に更新
```

**Plan 033（issue #4483）が main にマージ済みの場合**（`test -d changelog.d` で判定）: `CHANGELOG.md` は編集せず、`changelog.d/4463-remove-suno-popup.removed.md` を新規作成して上の bullet を書く。未マージの場合のみ `CHANGELOG.md` の `[Unreleased]` に追記する。

**Verify**: fragment 方式なら `test -f changelog.d/4463-remove-suno-popup.removed.md` → exit 0。直接編集なら `git diff CHANGELOG.md` → 追記のみ

## Test plan

新規テストは不要（build 対象外コードの削除）。`pnpm test` のグリーンと、`pnpm build` の成功（manifest に `default_popup` が無いことは既存 CI の manifest チェックが担保）で回帰確認とする。

## Done criteria

- [ ] `git ls-files extensions/suno-helper/entrypoints/popup/` が空
- [ ] `extensions/suno-helper/tests/popup-entrypoint.test.tsx` が存在しない
- [ ] README 2 本に popup を現役とする記述が無い
- [ ] `pnpm check` / `pnpm compile` / `pnpm test` / `pnpm build` がすべて exit 0（suno-helper）
- [ ] `CHANGELOG.md` の `[Unreleased]` に追記がある
- [ ] In scope 外の変更がない
- [ ] `plans/README.md` の Status 行を更新した

## STOP conditions

- `wxt.config.ts` の `filterEntrypoints` に `"popup"` が復活している（popup が再有効化された — 削除してはならない）。
- `pnpm test` で popup 以外のテストが fail し、原因がこの削除に見えない場合（環境問題の可能性。2 回試して報告）。
- README 修正中に、popup を前提とする**別の現役ドキュメント**（例: docs/ 配下の拡張ガイド）への波及が見つかった場合 — スコープ拡大の判断が要るので報告する。

## Maintenance notes

- `tests/popup-compatibility.test.ts`（4495 行）と distrokid/community の同名テストは overlay UI のテストなのに popup の名を冠したまま。次の整理候補（rename + 分割）は plans/README.md の未選択 findings に記録済み。
- レビューでは「App.tsx / overlay 系に一切手が入っていないこと」を確認する。
