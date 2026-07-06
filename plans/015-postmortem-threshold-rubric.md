# Plan 015: postmortem の閾値「文脈調整可」に調整ルーブリックを付ける

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 8deb3f02..HEAD -- .claude/skills/postmortem/SKILL.md`
> 差分があれば "Current state" の抜粋と実物を突合し、不一致なら STOP。

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none(plans/005 ルール 4「判断基準なしの判断要求の禁止」の実装例)
- **Category**: docs
- **Planned at**: commit `8deb3f02`, 2026-07-05

## Why this matters

`/postmortem` の症状判定表(CTR 0.7 倍未満 → サムネ訴求弱、など)の直後に「閾値は固定値ではなく**チャンネル特性に応じて文脈調整可**とする」とあるが、何をどう見て調整するかの基準がない。Sonnet 級モデルはこの一文から (a) 恣意的に閾値を動かして毎回違う結論を出す、(b) 調整を一切しない、のどちらかに振れる。postmortem は週次で繰り返し実行され結果が戦略判断に使われるため、判定の再現性が下がると分析自体への信頼が失われる。調整して良い条件と幅を 3 ケースの表で固定する。

## Current state

- `.claude/skills/postmortem/SKILL.md:91` — 対象の一文。現物:
  「閾値は固定値ではなく **チャンネル特性に応じて文脈調整可** とする。判定にあたって閾値を変更した場合は postmortem.md の「症状サマリー」欄に明示する。」
- 85-90 行: 症状判定表(4 行。`ctr_percentage` の 0.7 倍 / 0.9 倍、`impressions` の 0.5 倍、`ratio_vs_median < 0.9` などの係数)。**表自体は変更しない。**

## Commands you will need

| 目的 | コマンド | 成功条件 |
|------|----------|----------|
| ユニット全体 | `uv run pytest tests -q --ignore=tests/integration` | exit 0 |

## Scope

**In scope**:
- `.claude/skills/postmortem/SKILL.md`(91 行目の一文を段落に拡張するのみ)
- `CHANGELOG.md`

**Out of scope**:
- 症状判定表の係数そのもの。
- Phase 4(検証ステップ)以降の記述。

## Git workflow

- worktree 上で作業。base は main。
- コミット例: `docs(postmortem): 閾値の文脈調整にルーブリック（3 ケース + 上限幅）を追加`
- push / PR はオペレーターの指示があるまで行わない。

## Steps

### Step 1: 調整ルーブリックを追加する

91 行目の一文を以下で置き換える:

```markdown
閾値は以下のルーブリックの範囲でのみ調整可。**該当ケースがなければ表の係数をそのまま使う**（自由裁量での調整は不可）:

| ケース | 判定条件 | 調整 |
|--------|----------|------|
| 新チャンネル | 公開動画数 < 10 本、またはチャンネル開設 30 日未満 | 母集団が小さく平均が不安定なため、平均比の閾値を ±0.1 まで緩めてよい（例: 0.7 倍 → 0.6 倍） |
| 直近にテーマ転換 | 直近 3 本が過去の主要テーマと異なる（collection-ideate の記録で確認） | 過去平均との比較は参考値とし、`ratio_vs_median` 系の判定を優先する |
| 外部要因の明確な痕跡 | 公開時刻ミス・サムネ差し替え等が workflow-state / 履歴から確認できる | 該当指標の判定を保留し、外部要因を先に記録する |

調整した場合は、変更前後の閾値と適用したケース名を postmortem.md の「症状サマリー」欄に必ず明示する。
```

**Verify**: `rg -n '自由裁量での調整は不可' .claude/skills/postmortem/SKILL.md` → 1 件。`rg -n '±0.1' .claude/skills/postmortem/SKILL.md` → 1 件。

### Step 2: CHANGELOG 追記とテスト

```
- postmortem: 閾値の「文脈調整可」に 3 ケースのルーブリックと調整上限を追加（判定の再現性向上）
```

**Verify**: `rg -n 'ルーブリック' CHANGELOG.md` → 1 件。`uv run pytest tests -q --ignore=tests/integration` → exit 0。

## Test plan

新規テスト不要。既存ユニットスイート green を確認。

## Done criteria

- [ ] 調整可能なケース・条件・上限幅が表形式で定義され、「該当なしなら表のまま」が明記されている
- [ ] 症状判定表(85-90 行)の係数が無変更
- [ ] `CHANGELOG.md` 追記済み、ユニットテスト exit 0
- [ ] `plans/README.md` の 015 行を更新済み

## STOP conditions

- 91 行目の一文が Current state の引用と一致しない。
- ルーブリックの 3 ケースがチャンネル運用の実態と合わないとオペレーターから指摘があった場合(ケース定義は提案値 — 変更要望があれば従う)。

## Maintenance notes

- ルーブリックの係数(±0.1、10 本、30 日)は初期提案値。数サイクル運用して postmortem.md の「症状サマリー」欄に調整記録が溜まったら見直す。
- `/analytics-analyze` 側にも閾値系の記述があれば同じルーブリック参照に寄せられる(今回スコープ外)。
