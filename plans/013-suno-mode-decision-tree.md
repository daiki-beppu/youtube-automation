# Plan 013: suno のボーカル/インスト モード判定を decision tree 化する

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 8deb3f02..HEAD -- .claude/skills/suno/SKILL.md`
> 差分があれば "Current state" の抜粋と実物を突合し、不一致なら STOP。

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: docs
- **Planned at**: commit `8deb3f02`, 2026-07-05

## Why this matters

`/suno` のモード判定(ボーカル/インストゥルメンタル)は後続工程すべてを分岐させる(歌詞生成の要否、Suno UI の Instrumental ON/OFF、YAML 構造)。現状の判定規則は「`genre_line` にボーカル要素(`vocals`, `vocal`, `singing`, `rap`, `male/female vocals` 等)が含まれていれば」というキーワードスキャン 1 本で、(a)「等」の範囲が不定、(b) 否定文脈(`no vocals`, `without vocals`)の扱いが未定義、(c) 判定に迷った場合の手順がない。Sonnet 級モデルが誤判定すると、インスト予定のコレクションに歌詞工程が走る(またはその逆)という高コストな手戻りになる。判定を決定木 + 迷ったら確認、の形に置き換える。

## Current state

- `.claude/skills/suno/SKILL.md:22-24` — 「### モード判定」セクション。現物:

```markdown
### モード判定

`config/skills/suno.yaml` の `genre_line` を読み取り、**ボーカル要素**（`vocals`, `vocal`, `singing`, `rap`, `male/female vocals` 等）が含まれていれば**ボーカルモード**、なければ**インストゥルメンタルモード**として処理する。
```

- 直後(24 行目〜)にモード別の対応表(YAML 構造 / 歌詞 / Suno 設定)がある。表は変更不要。
- `tests/test_suno_skill_doc.py` — suno SKILL.md の記述を契約検証するテストが存在する。変更後に必ず実行すること。

## Commands you will need

| 目的 | コマンド | 成功条件 |
|------|----------|----------|
| suno 契約テスト | `uv run pytest tests/test_suno_skill_doc.py -q` | exit 0 |
| ユニット全体 | `uv run pytest tests -q --ignore=tests/integration` | exit 0 |

## Scope

**In scope**:
- `.claude/skills/suno/SKILL.md`(「### モード判定」セクションのみ)
- `CHANGELOG.md`

**Out of scope**:
- モード別対応表・パターン設計・後続 Step の記述。
- `yt-generate-suno` CLI の実装(コード側の判定ロジックがあるならそれは触らない)。
- `/suno-lyric` / `/lyria` 側の記述。

## Git workflow

- worktree 上で作業。base は main。
- コミット例: `docs(suno): モード判定を decision tree 化し否定文脈と迷った場合の手順を明記`
- push / PR はオペレーターの指示があるまで行わない。

## Steps

### Step 1: モード判定セクションを置き換える

「### モード判定」の本文段落を以下で置き換える(直後の対応表は保持):

```markdown
`config/skills/suno.yaml` の `genre_line` を読み、次の順で判定する:

1. **否定表現が先**: `instrumental`, `no vocals`, `without vocals`, `vocal-free` のいずれかを含む → **インストゥルメンタルモード**（他の語より優先）
2. **ボーカル語の完全一致**: 単語として `vocals` / `vocal` / `singing` / `singer` / `rap` / `choir` / `humming` のいずれか、または `male vocals` / `female vocals` を含む → **ボーカルモード**
3. どちらにも該当しない → **インストゥルメンタルモード**
4. **判定に確信が持てない場合**（例: `vocal chops` のような素材系表現、上記リスト外の歌唱系の語）: 推測で進めず、genre_line の該当箇所を提示して AskUserQuestion でユーザーにモードを確認する

このリストは網羅ではない。リスト外の語で歌唱を意図している可能性があるときは必ず 4 に落とす。
```

**Verify**: `rg -n '否定表現が先' .claude/skills/suno/SKILL.md` → 1 件。`rg -n '確信が持てない場合' .claude/skills/suno/SKILL.md` → 1 件。

### Step 2: 契約テストと全体テスト

**Verify**: `uv run pytest tests/test_suno_skill_doc.py -q` → exit 0。fail した場合はテストが旧文言を assert していないか確認し、期待値を新文言へ更新(コミットに明記)。その後 `uv run pytest tests -q --ignore=tests/integration` → exit 0。

### Step 3: CHANGELOG 追記

```
- suno: モード判定をキーワードスキャン単独から decision tree（否定表現優先 → 完全一致 → 不明時はユーザー確認）に明確化
```

**Verify**: `rg -n 'decision tree' CHANGELOG.md` → 1 件。

## Test plan

`tests/test_suno_skill_doc.py` を主ゲートに使う。新規テストは不要(判定はモデルが実行する手順であり、コードではない)。

## Done criteria

- [ ] モード判定が 4 段の決定木 + 「迷ったら確認」の形になっている
- [ ] 直後のモード別対応表が無変更
- [ ] `uv run pytest tests -q --ignore=tests/integration` が exit 0
- [ ] `CHANGELOG.md` 追記済み、`plans/README.md` の 013 行を更新済み

## STOP conditions

- 「### モード判定」セクションが Current state の引用と一致しない。
- `yt-generate-suno` のコード側に別のモード判定実装が見つかり、SKILL.md の決定木と矛盾する場合(`rg -n 'vocal|instrumental' src/youtube_automation/scripts/generate_suno*.py` で確認)— どちらが正か判断せず STOP して報告。

## Maintenance notes

- ボーカル語リストを増やす場合はこの決定木の 1・2 項だけを編集する。「等」に戻さないこと(レビュー観点)。
- チャンネル側で判定を固定したいニーズが出たら、`config/skills/suno.yaml` に明示キー(`mode: vocal|instrumental`)を追加して決定木の 0 番目に置くのが正道(コード変更を伴うため別 plan)。
