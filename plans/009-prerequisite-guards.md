# Plan 009: 工程チェーンの前提条件ガードを 4 スキルに追加する

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 8deb3f02..HEAD -- .claude/skills/channel-setup/SKILL.md .claude/skills/channel-research/SKILL.md .claude/skills/audience-persona-design/SKILL.md .claude/skills/channel-direction/SKILL.md`
> 差分があれば "Current state" の抜粋と実物を突合し、不一致なら STOP。

## Status

- **Priority**: P2
- **Effort**: S-M
- **Risk**: LOW
- **Depends on**: plans/005-skill-authoring-standard.md(ルール 3「前提ガードの標準型」。005 未完了でも実行可能)
- **Category**: docs
- **Planned at**: commit `8deb3f02`, 2026-07-05

## Why this matters

チャンネル戦略系スキルは `/channel-direction → /channel-setup`、`/benchmark → /channel-research`、`/viewing-scene → /audience-persona-design Phase 6` という工程チェーンを成すが、後工程スキルの手順に「前工程の出力が存在するか」の入口ガードがない箇所が 4 つある。Sonnet 級モデルは前提を暗黙に信じて手順を実行し、`FileNotFoundError` や空データでの続行(最悪、欠損データのまま成果物を確定)に至る。各箇所に「存在確認 → なければ前工程を案内して停止」の 1〜3 行を追加する。ガードは軽微だが、失敗が「後工程の途中」ではなく「入口」で起きるようになり、復旧手順が一義化される。

## Current state

対象 4 箇所(すべて実読で確認済み):

1. `.claude/skills/channel-setup/SKILL.md:34-52` — 「#### Step 2.1: 競合 TTP 面のスナップショット取得（必須）」。`uv run python3 -c "... YouTubeOAuthHandler().get_youtube_service() ..."` の inline Python を提示するが、直前に `auth/token.json` / `auth/client_secrets.json` の存在確認がない。OAuth 未設定だと実行時例外で落ちる。
2. `.claude/skills/channel-setup/SKILL.md:114-127` — 「### Step 3.5: config/skills/*.yaml への転記」。`docs/channel/channel-direction.md` の決定を転記すると書かれているが、同ファイルの存在確認ステップがない。`/channel-direction` 未実行のまま到達すると転記元がない。
3. `.claude/skills/channel-research/SKILL.md:11-15` — Overview に「**前提**: /benchmark と /viewer-voice を実行済みで、以下のデータが存在すること」とデータ一覧(`data/benchmark_YYYYMMDD.json` 等)は**記載済み**。ただし手順(Step 1)側に存在確認コマンドと「なければ停止」の指示がない。前提は書いてあるが実行時に照合されない形。
4. `.claude/skills/audience-persona-design/SKILL.md:119-131` — 「### Phase 5: viewing-scene 検証」は `/viewing-scene` が `docs/plans/viewing-scene-matrix.md` を生成する前提で Phase 6(最終確定)へ進む。`/viewing-scene` が実行されなかった/失敗した場合のガードがなく、Phase 6 が暫定ペルソナを最終版として確定しうる。

参考(良い先例、変更しない): `.claude/skills/channel-new/SKILL.md:110`「以下の check が `ok` でない場合は、ここで `/setup` を案内して停止する。」

## Commands you will need

| 目的 | コマンド | 成功条件 |
|------|----------|----------|
| frontmatter 検証 | `uv run pytest tests/test_skill_frontmatter_yaml.py -q` | exit 0 |
| ユニット全体 | `uv run pytest tests -q --ignore=tests/integration` | exit 0 |

## Scope

**In scope**:
- `.claude/skills/channel-setup/SKILL.md`(Step 2.1 冒頭と Step 3.5 冒頭)
- `.claude/skills/channel-research/SKILL.md`(最初の実行 Step の冒頭)
- `.claude/skills/audience-persona-design/SKILL.md`(Phase 5 → Phase 6 の間)
- `CHANGELOG.md`(`[Unreleased]` への追記)

**Out of scope**:
- `/channel-direction` 側の変更(引き継ぎ表は既に十分明示的: `channel-direction/SKILL.md:99-115`)。
- `/wf-*` 系スキル(collection-ideate が既に存在チェックの記述を持つ)。
- inline Python 自体の書き換え(コード内容は正しい。ガードを前置するだけ)。
- CLI / src 側の変更。

## Git workflow

- worktree 上で作業。base は main。
- コミット例: `docs(skills): channel-setup / channel-research / audience-persona-design に前提ガードを追加`
- push / PR はオペレーターの指示があるまで行わない。

## Steps

### Step 1: channel-setup Step 2.1 に認証ガードを追加する

「#### Step 2.1」見出しの直後・inline Python の前に追加:

```markdown
実行前に認証ファイルの存在を確認する。ない場合は `/setup` を案内して停止する（このまま下のコードを実行すると認証エラーで失敗する）:

​```bash
ls auth/token.json auth/client_secrets.json
​```
```

**Verify**: `rg -n 'ls auth/token.json' .claude/skills/channel-setup/SKILL.md` → 1 件、Step 2.1 セクション内にある。

### Step 2: channel-setup Step 3.5 に転記元ガードを追加する

「### Step 3.5」見出しの直後に追加:

```markdown
転記元 `docs/channel/channel-direction.md` が存在することを確認する。ない場合は `/channel-direction` を先に実行するようユーザーに案内して停止する（順序: `/channel-direction` → `/channel-setup` Step 3.5 固定）。
```

**Verify**: `rg -n 'channel-direction を先に実行' .claude/skills/channel-setup/SKILL.md` → 1 件。

### Step 3: channel-research の最初の Step に存在確認を追加する

`.claude/skills/channel-research/SKILL.md` の最初の実行ステップ(Overview の後、最初の `## Instructions` / Step 見出しを実読して特定)の冒頭に追加:

```markdown
### Step 0: 前提データの存在確認

​```bash
ls data/benchmark_*.json data/comments_*.json docs/benchmarks/*.md
​```

1 つでも欠けている場合は分析に入らない。`data/benchmark_*.json` / `docs/benchmarks/*.md` がなければ `/benchmark` を、`data/comments_*.json` がなければ `/viewer-voice` を案内して停止する。
```

既存の Step 番号とぶつかる場合は「Step 0」とし、既存番号は変えない。

**Verify**: `rg -n 'Step 0: 前提データの存在確認' .claude/skills/channel-research/SKILL.md` → 1 件。

### Step 4: audience-persona-design の Phase 6 入口にガードを追加する

「### Phase 6: 最終 persona-definition.md 更新」見出しの直後に追加:

```markdown
`docs/plans/viewing-scene-matrix.md` が存在しない場合、Phase 6 に進んではならない。`/viewing-scene` の実行（Phase 5）に戻るか、ユーザーが viewing-scene 検証をスキップすると明示した場合のみ、persona-definition.md に「viewing-scene 未検証」と注記した上で確定する。
```

**Verify**: `rg -n 'viewing-scene-matrix.md が存在しない場合' .claude/skills/audience-persona-design/SKILL.md` → 1 件。

### Step 5: CHANGELOG に追記する

```
- channel-setup / channel-research / audience-persona-design: 前工程出力（auth token / channel-direction.md / benchmark データ / viewing-scene-matrix.md）の存在ガードを追加
```

**Verify**: `rg -n '存在ガードを追加' CHANGELOG.md` → 1 件。

### Step 6: テスト確認

**Verify**: `uv run pytest tests -q --ignore=tests/integration` → exit 0。

## Test plan

新規テスト不要(SKILL.md の手順文追加)。既存ユニットスイート green を確認。`test_skill_docs_consistency.py` が fail した場合は期待値更新で対応(コミットに明記)。

## Done criteria

- [ ] 4 箇所すべてに「存在確認 → なければ前工程案内で停止」のガードが入っている
- [ ] 既存の Step 番号・見出し構造を壊していない(`rg -n '^### ' <file>` で前後比較)
- [ ] `CHANGELOG.md` 追記済み
- [ ] `uv run pytest tests -q --ignore=tests/integration` が exit 0
- [ ] `plans/README.md` の 009 行を更新済み

## STOP conditions

- 対象 4 箇所の現物が Current state の記述と一致しない(drift)。
- 該当箇所に既に同等のガードが存在する(先行修正済み)— 重複追加せず該当 Step をスキップし、README にその旨を書く。
- channel-research に `## Instructions` に相当する実行手順セクションが見つからない(構造が想定と違う)。

## Maintenance notes

- ガードのパス(`docs/plans/viewing-scene-matrix.md` 等)は各スキルの出力先変更と連動する。出力パスを変える PR ではガード側の追従をレビューで確認。
- `/viewing-scene` 側に「出力完了を workflow 側へ通知する」仕組みはない(ファイル存在が唯一のシグナル)。将来状態ファイルに寄せる場合はガードも書き換える。
