# Plan 004: distrokid-helper のサーバー URL 既定値を extensions/shared/constants.ts に集約する

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat fa296fe..HEAD -- extensions/distrokid-helper/lib/storage.ts extensions/shared/constants.ts`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tech-debt
- **Planned at**: commit `fa296fe`, 2026-06-12
- **Issue**: https://github.com/daiki-beppu/youtube-automation/issues/956

## Why this matters

`yt-collection-serve` の既定 URL `http://localhost:7873` が 2 箇所にハードコードされている: `extensions/shared/constants.ts` の `DEFAULT_URL`（suno-helper が使用）と `extensions/distrokid-helper/lib/storage.ts` の `DEFAULT_SERVER_URL`。リポジトリ規約（ルート README / extensions/README.md）は「サーバーとの互換契約値は `extensions/shared/constants.ts` の定数として 1 箇所で定義する。ハードコーディング禁止」と明記しており、これはその違反。サーバーの既定ポートが変わったとき片方だけ更新されるリスクがある。distrokid-helper は既に `shared/constants` から `distrokidReleaseRoute` を import しているため、修正は import を 1 つ足すだけで済む。

## Current state

- `extensions/distrokid-helper/lib/storage.ts`（14 行、全文）:

```ts
// サーバー URL の永続化（@wxt-dev/storage）。
//
// 実 read/write は chrome.storage が必要なため拡張ランタイム側でのみ動く。
// 既定値は yt-collection-serve の DEFAULT_PORT=7873 と一致させる（suno-helper と対称）。

import { storage } from "@wxt-dev/storage";

// popup のサーバー URL 入力の初期値。yt-collection-serve の既定ポートを指す。
export const DEFAULT_SERVER_URL = "http://localhost:7873";

// サーバー URL の永続化アイテム（local area）。
export const serverUrlItem = storage.defineItem<string>("local:serverUrl", {
  fallback: DEFAULT_SERVER_URL,
});
```

- `extensions/shared/constants.ts:142-143` — 集約先の既存定数:

```ts
/** ローカル配信元の既定 URL。 */
export const DEFAULT_URL = "http://localhost:7873";
```

- shared からの相対 import の既存例（規約どおり `../../shared/*`）: `extensions/distrokid-helper/lib/api.ts:9` の `import { distrokidReleaseRoute } from "../../shared/constants";`
- `DEFAULT_SERVER_URL` の利用箇所を把握すること: `grep -rn "DEFAULT_SERVER_URL" extensions/distrokid-helper --include='*.ts' --include='*.tsx'`（storage.ts 本体のほか、popup コンポーネントやテストが参照している可能性がある）。

## Commands you will need

| Purpose | Command（cwd: `extensions/distrokid-helper`） | Expected on success |
|---|---|---|
| 型チェック | `pnpm compile` | exit 0 |
| Unit | `pnpm test` | all pass |
| Build | `pnpm build` | exit 0 |

## Scope

**In scope** (the only files you should modify):

- `extensions/distrokid-helper/lib/storage.ts`
- `DEFAULT_SERVER_URL` を import している distrokid-helper 配下のファイル（grep で特定したもののみ。import 元の差し替えに限る）

**Out of scope** (do NOT touch, even though they look related):

- **storage key `"local:serverUrl"` の変更** — key を変えると利用者の保存済みサーバー URL が失われる。絶対に変えない。
- `extensions/shared/constants.ts` — `DEFAULT_URL` は既にあるため変更不要（suno 固有定数が多いファイルだが、整理は本プランのスコープ外）。
- `extensions/suno-helper/**`。
- サーバー側 `collection_serve.py` の DEFAULT_PORT。

## Git workflow

- worktree 必須: `git -C /Users/mba/02-yt/automation pull --ff-only && git -C /Users/mba/02-yt/automation worktree add .worktrees/dk-server-url-const -b refactor/distrokid-helper-server-url-constant`
- Commit 規約: 日本語 Conventional Commits。例: `refactor(distrokid-helper): サーバー URL 既定値を shared/constants の DEFAULT_URL に集約`
- push / PR 作成はオペレーターの指示があるまで行わない。

## Steps

### Step 1: storage.ts を shared 定数参照に書き換える

`extensions/distrokid-helper/lib/storage.ts` のローカル定義を削除し、re-export に置き換える:

```ts
import { storage } from "@wxt-dev/storage";
import { DEFAULT_URL } from "../../shared/constants";

// popup のサーバー URL 入力の初期値。SSOT は shared/constants.ts の DEFAULT_URL
// （yt-collection-serve の DEFAULT_PORT=7873 と一致、suno-helper と共用）。
export const DEFAULT_SERVER_URL = DEFAULT_URL;

// サーバー URL の永続化アイテム（local area）。key は保存済み値の互換のため変更しない。
export const serverUrlItem = storage.defineItem<string>("local:serverUrl", {
  fallback: DEFAULT_SERVER_URL,
});
```

`DEFAULT_SERVER_URL` の export 名は維持する（参照側の変更を最小化し、storage key 同様の互換を保つ）。ファイル冒頭の既存コメント（chrome.storage が必要な旨）は残す。

**Verify**: `pnpm compile` → exit 0

### Step 2: 文字列リテラルの残存がないことを確認する

```
grep -rn "localhost:7873" extensions/distrokid-helper --include='*.ts' --include='*.tsx' | grep -v tests
```

storage.ts 以外（および storage.ts 自身）にリテラルが残っていないこと。テストコード内のリテラルは期待値の明示として許容（書き換え不要）。

**Verify**: 上記 grep → 0 件（tests を除く）

### Step 3: テストとビルド

```
pnpm test && pnpm build
```

**Verify**: 全 pass / exit 0

## Test plan

新規テストなし（純粋な定数集約）。既存の `tests/storage.test.ts`（17 行）が `DEFAULT_SERVER_URL` の fallback 挙動を検証しており、それが回帰ゲートになる。

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n 'DEFAULT_URL' extensions/distrokid-helper/lib/storage.ts` → shared からの import が存在する
- [ ] `grep -rn "localhost:7873" extensions/distrokid-helper/lib extensions/distrokid-helper/entrypoints extensions/distrokid-helper/components` → 0 件
- [ ] `grep -n '"local:serverUrl"' extensions/distrokid-helper/lib/storage.ts` → 1 件（key が変わっていない）
- [ ] `pnpm compile && pnpm test && pnpm build` がすべて exit 0
- [ ] `git status` で in-scope 外のファイルが変更されていない
- [ ] `plans/README.md` の status 行を更新済み

## STOP conditions

Stop and report back (do not improvise) if:

- `shared/constants.ts` の import が WXT のビルド（content script / popup の両 entrypoint）でエラーになる場合 — `constants.ts` は `./api` から型 import をしており（line 5）、bundler の解決に問題が出る可能性がゼロではない。その場合は原因を報告する（`import type` なので通常は tree-shake される）。
- `DEFAULT_SERVER_URL` の参照箇所が grep で 5 箇所を超えて見つかり、単純な import 差し替えで済まない構造だった場合。

## Maintenance notes

- 今後サーバーの既定ポートを変える場合は `shared/constants.ts::DEFAULT_URL` と `collection_serve.py` 側の既定ポートの 2 箇所更新となる（TS↔Python 間の SSOT 化は現実的でないため、constants.ts のコメントが Python 側参照を指している現状の運用を維持）。
- 将来 `shared/constants.ts` が suno 固有定数で肥大化した場合、`shared/server.ts`（serve 契約）と `shared/suno.ts`（suno 固有）への分割を検討する余地がある — 本プランでは見送り。
