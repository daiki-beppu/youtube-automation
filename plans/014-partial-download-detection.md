# Plan 014: suno-helper → masterup 間の部分ダウンロード検知手順を明文化する

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 8deb3f02..HEAD -- .claude/skills/masterup/SKILL.md .claude/skills/suno-helper/SKILL.md`
> 差分があれば "Current state" の抜粋と実物を突合し、不一致なら STOP。

## Status

- **Priority**: P2
- **Effort**: S(監査時は M 想定だったが、責務分離が既に明文化済みと確認できたため縮小)
- **Risk**: LOW
- **Depends on**: none
- **Category**: docs
- **Planned at**: commit `8deb3f02`, 2026-07-05

## Why this matters

**スコープ注記(監査からの縮小)**: 当初の finding は「DL 状態管理の責務が不明」と主張したが、実読の結果、責務分離は既に明文化されていた — `masterup/SKILL.md:10` が「DL は /suno-helper が primary path、本スキルの主責務はマスター音源生成 + workflow-state 更新」と宣言し、`suno-helper/SKILL.md:130-131` の完了確認に `workflow-state.json` の `planning.music.suno_playlist_url` と `assets.music_downloaded = true` が列挙されている。残る実ギャップは 1 点: **部分ダウンロード**(例: 10 曲中 5 曲で失敗)のとき、`assets.music_downloaded` の真偽と `02-Individual-music/` の実ファイル数が食い違う状態を masterup 側が検知する手順がないこと。Sonnet 級モデルは「フラグが true だから揃っている」と解釈し、欠けた曲数のままマスター音源を生成しうる(生成後に気づくと Suno クレジットと時間の手戻り)。期待曲数との突合チェックを masterup の入口に 1 つ追加する。

## Current state

- `.claude/skills/masterup/SKILL.md`(613 行)
  - 10 行目: DL 責務分離の宣言(上記)。変更不要。
  - Step 1(コレクション特定、148 行目付近に `collections/planning/` の `workflow-state.json` 検索)— この直後が追加位置の候補。Step 構成を実読して確定すること。
  - 期待曲数の情報源: コレクションの `workflow-state.json` および `20-documentation/suno-prompts.json` の entry 数(インストは 1 Generate = 2 clip)。正確なキー名は `masterup/SKILL.md` 内の既存記述(`mp3_count` への言及が 114 行目にある)と `wf-new` が生成する workflow-state の構造を実読して確認する。
- `.claude/skills/suno-helper/SKILL.md:130-131` — 完了確認リスト(`assets.music_downloaded` が true)。変更は任意(Step 3 参照)。

## Commands you will need

| 目的 | コマンド | 成功条件 |
|------|----------|----------|
| ユニット全体 | `uv run pytest tests -q --ignore=tests/integration` | exit 0 |

## Scope

**In scope**:
- `.claude/skills/masterup/SKILL.md`(入口チェックの追加 1 箇所)
- `.claude/skills/suno-helper/SKILL.md`(完了確認への 1 項目追記のみ、任意)
- `CHANGELOG.md`

**Out of scope**:
- `assets.music_downloaded` フラグの仕様変更(bool のまま。曲数フィールド追加などのスキーマ変更はしない — 下流互換に関わるため別判断)。
- masterup の Step 2-5(DL fallback・マスター生成)本体。
- `yt-generate-master` 等の CLI 実装。

## Git workflow

- worktree 上で作業。base は main。
- コミット例: `docs(masterup): 部分ダウンロード検知の入口チェックを追加`
- push / PR はオペレーターの指示があるまで行わない。

## Steps

### Step 1: 期待曲数の正確な情報源を特定する

`masterup/SKILL.md` を実読し、(a) Step 構成、(b) 期待曲数が何で決まるか(`workflow-state.json` のキー / `suno-prompts.json` の entry 数×2 など)を確定する。`rg -n 'mp3_count|tracks_per_collection|曲数' .claude/skills/masterup/SKILL.md .claude/skills/suno/SKILL.md` が手がかり。

**Verify**: 期待曲数の算出方法を 1 文で言える状態になっている(判断できなければ STOP)。

### Step 2: masterup の入口に突合チェックを追加する

コレクション特定 Step(Step 1)の完了直後に追加(文言は Step 1 の調査結果でキー名を正確にする):

```markdown
**DL 完全性チェック**: `02-Individual-music/` の mp3 実ファイル数を数え、期待曲数（<Step 1 で確定した情報源>）と突合する。

- 一致 → 次の Step へ
- 実ファイル数が少ない（部分ダウンロード）→ `assets.music_downloaded` が `true` でも揃っているとみなさない。不足曲数と該当 entry を提示し、/suno-helper の再実行（または Step 2-3 の手動 DL fallback）を案内して停止する
- `02-Individual-music/` が空 → /suno-helper 未実行として案内して停止する
```

**Verify**: `rg -n 'DL 完全性チェック' .claude/skills/masterup/SKILL.md` → 1 件。

### Step 3(任意): suno-helper の完了確認に注記を追加する

`suno-helper/SKILL.md` の完了確認リスト(130-131 行付近)に 1 項目追記:

```markdown
7. `02-Individual-music/` の mp3 数が期待曲数と一致している（不足があれば `assets.music_downloaded` を true にしない）
```

既存リストの番号体系に合わせること。

**Verify**: `rg -n '期待曲数と一致' .claude/skills/suno-helper/SKILL.md` → 1 件。

### Step 4: CHANGELOG 追記とテスト

```
- masterup / suno-helper: 部分ダウンロード（期待曲数と実ファイル数の不一致）を masterup 入口で検知する手順を追加
```

**Verify**: `rg -n '部分ダウンロード' CHANGELOG.md` → 1 件。`uv run pytest tests -q --ignore=tests/integration` → exit 0。

## Test plan

新規テスト不要。既存ユニットスイート green を確認。

## Done criteria

- [ ] masterup の入口に「実ファイル数 vs 期待曲数」の突合と、不一致時の停止・案内がある
- [ ] チェックの期待曲数の情報源が実在するキー/ファイルを指している(Step 1 で確認済みのもの)
- [ ] `CHANGELOG.md` 追記済み、ユニットテスト exit 0
- [ ] `plans/README.md` の 014 行を更新済み

## STOP conditions

- Step 1 で期待曲数の情報源が特定できない(workflow-state / suno-prompts のどちらにも曲数に相当する値がない)— スキーマ追加が必要になり本 plan のスコープ外。STOP して報告。
- masterup に既に同等の完全性チェックが存在する。

## Maintenance notes

- 将来 `assets.music_downloaded` を bool から `{downloaded: N, expected: M}` 型に拡張すれば、このチェックは機械化できる(スキーマ変更 + suno-helper 拡張側の対応が必要。follow-up 候補)。
- インスト/ボーカルで期待曲数の算式が違う場合(1 Generate = 2 clip)、チェック文言に両モードの算式を明記すること。
