# Plan 010: channel-new のペルソナ生成前に TTP 対象の中間ゲートを追加する

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 8deb3f02..HEAD -- .claude/skills/channel-new/SKILL.md`
> 差分があれば "Current state" の抜粋と実物を突合し、不一致なら STOP。

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: docs
- **Planned at**: commit `8deb3f02`, 2026-07-05

## Why this matters

**スコープ注記(監査からの縮小)**: 当初の監査 finding は「channel-new(537 行)は完了条件が埋没し、Step 3 のチェックが混在」と主張したが、plan 作成時の実読で大半は既に解決済みと判明した — TTP 完了条件は冒頭近く(48-60 行)にあり、Step 3 は「停止すべき 17 チェック」と「許容する 4 fail(理由文字列付き)」を明確に分離している(110-140 行)。残る実ギャップは 1 点のみ: **最終ゲート(Step 9、396-404 行)まで TTP 対象 0 件が検出されない**こと。途中の Step(ペルソナ生成など)は `benchmark.channels` が空でも進行でき、Sonnet 級モデルは空のまま後続成果物を作ってから Step 9 で差し戻される。無駄な生成(AI コスト)と手戻りを、ペルソナ生成直前の 2 行のゲートで防ぐ。

## Current state

- `.claude/skills/channel-new/SKILL.md`(537 行)— 対象ファイル。
  - 48-60 行: 「### TTP 完了条件（新規開設モード）」— `config/channel/analytics.json::benchmark.channels` に承認済み TTP 対象 1 件以上、など 6 条件。**既に冒頭にある。変更不要。**
  - 110-140 行: Step 3 の yt-doctor チェック分離。**変更不要。**
  - 396-404 行: Step 9 の最終ゲート「承認済み TTP 対象が 0 件の場合は `/wf-new` 接続へ進まず、Step 1/5 に戻って候補を再確認するか、ユーザーに停止を確認して終了する。」— 唯一の 0 件検出点。
  - ペルソナ生成の Step(Step 7 前後。実読して正確な見出しを特定すること)— `benchmark.channels` への依存があるが入口ガードなし。

## Commands you will need

| 目的 | コマンド | 成功条件 |
|------|----------|----------|
| ユニット全体 | `uv run pytest tests -q --ignore=tests/integration` | exit 0 |

## Scope

**In scope**:
- `.claude/skills/channel-new/SKILL.md`(ペルソナ生成 Step の冒頭に 2〜4 行追加のみ)
- `CHANGELOG.md`(`[Unreleased]` への追記)

**Out of scope**:
- TTP 完了条件セクション・Step 3・Step 9 の既存文言(すでに良い状態。再構成しない)。
- 取り込みモード(既存チャンネル取り込み)側の手順 — TTP 完了条件の適用外と明記されている(52 行)。
- SKILL.md の分割・短縮などの構造改革。

## Git workflow

- worktree 上で作業。base は main。
- コミット例: `docs(channel-new): ペルソナ生成前に TTP 対象 0 件の中間ゲートを追加`
- push / PR はオペレーターの指示があるまで行わない。

## Steps

### Step 1: ペルソナ生成 Step を特定する

`rg -n '^### ' .claude/skills/channel-new/SKILL.md` で Step 見出し一覧を出し、ペルソナ(persona)生成を行う Step を特定する(Step 7 近辺の想定)。

**Verify**: 見出し一覧にペルソナ生成に該当する Step がある。なければ STOP。

### Step 2: 中間ゲートを追加する

特定した Step の見出し直後に追加:

```markdown
**入口ゲート**: `config/channel/analytics.json::benchmark.channels` に承認済み TTP 対象が 1 件以上あることを確認する。0 件の場合は本 Step 以降に進まず、Step 5 に戻って TTP 候補の承認を完了させる（冒頭「TTP 完了条件」参照）。0 件のままペルソナを生成すると Step 9 の最終ゲートで差し戻しになり、生成コストが無駄になる。
```

**Verify**: `rg -n '入口ゲート' .claude/skills/channel-new/SKILL.md` → 1 件、ペルソナ生成 Step 内。

### Step 3: CHANGELOG 追記とテスト

`CHANGELOG.md` の `[Unreleased]`:

```
- channel-new: ペルソナ生成前に TTP 対象 0 件を検出する中間ゲートを追加（最終ゲートまで気づかない手戻りを防止）
```

**Verify**: `rg -n '中間ゲート' CHANGELOG.md` → 1 件。`uv run pytest tests -q --ignore=tests/integration` → exit 0。

## Test plan

新規テスト不要。既存ユニットスイート green を確認。

## Done criteria

- [ ] ペルソナ生成 Step の冒頭に TTP 対象 0 件ゲートがある
- [ ] 既存の TTP 完了条件・Step 3・Step 9 は無変更(`git diff` で該当行に差分がない)
- [ ] `CHANGELOG.md` 追記済み、ユニットテスト exit 0
- [ ] `plans/README.md` の 010 行を更新済み

## STOP conditions

- ペルソナ生成 Step が特定できない、または既に同等の入口ゲートが存在する。
- ペルソナ生成が `benchmark.channels` に依存しない構造に変わっている(ゲートの前提が崩れている)。

## Maintenance notes

- `/channel-new` は最近「取り込みモード統合」(#1460)で大きく改稿された。今後の改稿でもこのゲートが Step 9 の最終ゲートと二重管理にならないよう、文言は「冒頭 TTP 完了条件への参照」に留めてある(条件本体をコピーしない — 単一ソース原則)。
- 監査 finding の残り(「537 行で長い」)は plan 化を見送り: 現構造は参照関係が明示されており、分割はリスクの割に益が薄い。
