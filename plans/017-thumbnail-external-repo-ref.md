# Plan 017: thumbnail の外部リポジトリ参照をオペレーター向け注記に隔離する

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 8deb3f02..HEAD -- .claude/skills/thumbnail/SKILL.md`
> 差分があれば "Current state" の抜粋と実物を突合し、不一致なら STOP。

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none(plans/005 ルール 7「実行者が解決できない参照の禁止」の実装例)
- **Category**: docs
- **Planned at**: commit `8deb3f02`, 2026-07-05

## Why this matters

`/thumbnail` の diff_prompt_template 解説の中に「実装事例として `daiki-beppu/rjn` の `config/skills/thumbnail.yaml` が参考になる」という文が地の文で置かれている。このスキルは `yt-skills sync` で下流チャンネルリポジトリへ配布され、そこで実行するモデル(とりわけ Sonnet 級)にとって `daiki-beppu/rjn` はアクセスできない私有リポジトリである。地の文の「参考になる」は実行手順の一部として解釈され、モデルが gh でのアクセス試行やファイル探索で時間を浪費する。オペレーター(リポジトリ所有者)向けの情報としては有用なので、削除ではなく「実行者向けではない」ことが明確な引用ブロックへ隔離する。

## Current state

- `.claude/skills/thumbnail/SKILL.md:340` — 対象の一文。現物(段落末尾):
  「差分プロンプトの具体例は skill-config の `image_generation.gemini.diff_prompt_template` を参照し、チャンネル固有のオブジェクト・カラーを埋める。実装事例として `daiki-beppu/rjn` の `config/skills/thumbnail.yaml` が参考になる（jazzgak チャンネルの 5 サムネを `color_themes.<theme>.reference_image` で多軸切替）。」
- 他に外部リポジトリを地の文で参照する箇所がないか確認する: `rg -n 'daiki-beppu/' .claude/skills/*/SKILL.md`(この plan のスコープは thumbnail のみだが、他にあれば README に followup として記録する)。

## Commands you will need

| 目的 | コマンド | 成功条件 |
|------|----------|----------|
| thumbnail 関連テスト | `uv run pytest tests/test_thumbnail_skill_assets.py tests/test_thumbnail_codex_image_skill.py -q` | exit 0 |
| ユニット全体 | `uv run pytest tests -q --ignore=tests/integration` | exit 0 |

## Scope

**In scope**:
- `.claude/skills/thumbnail/SKILL.md`(340 行の一文の移動・書式変更のみ)
- `CHANGELOG.md`

**Out of scope**:
- diff_prompt_template の解説本体。
- 他スキルの外部参照(発見したら README に記録するのみ)。

## Git workflow

- worktree 上で作業。base は main。
- コミット例: `docs(thumbnail): 外部リポジトリ参照をオペレーター向け注記に隔離`
- push / PR はオペレーターの指示があるまで行わない。

## Steps

### Step 1: 該当文を引用ブロックに隔離する

340 行の「実装事例として `daiki-beppu/rjn` の…」の一文を段落から削除し、同じ段落の直後に以下の引用ブロックとして置き直す:

```markdown
> **参考（オペレーター向け・実行時は無視してよい）**: 実装事例はオペレーターの私有リポジトリ `daiki-beppu/rjn` の `config/skills/thumbnail.yaml` にある（jazzgak チャンネルの 5 サムネを `color_themes.<theme>.reference_image` で多軸切替）。下流リポジトリの実行者はアクセスできないため、取得を試みないこと。
```

**Verify**: `rg -n '実行時は無視してよい' .claude/skills/thumbnail/SKILL.md` → 1 件。`rg -n '実装事例として' .claude/skills/thumbnail/SKILL.md` → 0 件(地の文から消えている)。

### Step 2: 他の外部参照を確認する(記録のみ)

`rg -n 'daiki-beppu/' .claude/skills/*/SKILL.md` を実行し、thumbnail 以外にヒットがあれば `plans/README.md` の残課題欄に 1 行追記する(修正はしない)。

**Verify**: コマンドを実行し、結果を README 更新(該当なしなら不要)に反映した。

### Step 3: CHANGELOG 追記とテスト

```
- thumbnail: 外部リポジトリ（daiki-beppu/rjn）への参照をオペレーター向け注記に隔離（下流実行者のアクセス試行を防止）
```

**Verify**: `rg -n 'オペレーター向け注記に隔離' CHANGELOG.md` → 1 件。`uv run pytest tests -q --ignore=tests/integration` → exit 0。

## Test plan

`tests/test_thumbnail_skill_assets.py` / `tests/test_thumbnail_codex_image_skill.py` を含むユニットスイート green を確認。新規テスト不要。

## Done criteria

- [ ] `daiki-beppu/rjn` への言及が「オペレーター向け・実行時は無視」の引用ブロック内にのみ存在する
- [ ] 「取得を試みないこと」という禁止形が含まれている
- [ ] `CHANGELOG.md` 追記済み、ユニットテスト exit 0
- [ ] `plans/README.md` の 017 行を更新済み

## STOP conditions

- 340 行付近の現物が Current state の引用と一致しない。
- thumbnail の contract テストがこの一文の存在位置を assert している(期待値更新で直るなら更新して続行、構造的に直らないなら STOP)。

## Maintenance notes

- 規約(plans/005 ルール 7)の「オペレーター向け注記」書式の最初の実装例になる。以降、私有リポジトリ・未接続機能への言及はこの書式に揃える。
- 実装事例をこのリポジトリ内に置けるなら(`examples/` に匿名化した thumbnail.yaml 例を追加)、外部参照自体を不要にできる(follow-up 候補)。
