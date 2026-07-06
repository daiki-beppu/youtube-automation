# Plan 016: setup の project ID truncate 手順を一義化する

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 8deb3f02..HEAD -- .claude/skills/setup/SKILL.md`
> 差分があれば "Current state" の抜粋と実物を突合し、不一致なら STOP。

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: docs
- **Planned at**: commit `8deb3f02`, 2026-07-05

## Why this matters

`/setup` の GCP project ID 生成規則に「30 文字を超える場合は `yt-` を含めて 30 文字以内に truncate」とあるが、この文は「`yt-` prefix を保持して slug 側の末尾を削る」とも「全体を機械的に 30 文字で切る」とも読める。さらに機械的に切ると末尾がハイフンで終わる ID(GCP 制約違反)が生成されうる。project ID は作成後に変更できないため、規則を手順 + 具体例で一義化する。小さな修正だが、`/setup` は新チャンネルごとに必ず通る道である。

## Current state

- `.claude/skills/setup/SKILL.md:157-159` — 対象箇所。現物:
  - 158 行: 「project ID: `yt-{channel-slug}`。`channel-slug` はチャンネル名を kebab-case 化し、英小文字・数字・ハイフン以外をハイフンに置換、連続ハイフンを 1 個に畳み、先頭末尾のハイフンを削る」
  - 159 行: 「project ID は GCP 制約に合わせて 6-30 文字、英小文字開始、英小文字/数字/ハイフン終端に収める。30 文字を超える場合は `yt-` を含めて 30 文字以内に truncate し、短すぎる/空になる場合はカスタム入力を求める」

## Commands you will need

| 目的 | コマンド | 成功条件 |
|------|----------|----------|
| setup 契約テスト | `uv run pytest tests/test_setup_skill.py -q` | exit 0 |
| ユニット全体 | `uv run pytest tests -q --ignore=tests/integration` | exit 0 |

## Scope

**In scope**:
- `.claude/skills/setup/SKILL.md`(159 行の truncate 文のみ)
- `CHANGELOG.md`

**Out of scope**:
- 158 行の slug 生成規則(既に一義的)。
- gcloud コマンド群・その他の Step。

## Git workflow

- worktree 上で作業。base は main。
- コミット例: `docs(setup): project ID の truncate 手順を具体例付きで一義化`
- push / PR はオペレーターの指示があるまで行わない。

## Steps

### Step 1: truncate 文を置き換える

159 行の「30 文字を超える場合は `yt-` を含めて 30 文字以内に truncate し、短すぎる/空になる場合はカスタム入力を求める」を以下で置き換える:

```markdown
全体（`yt-` + slug）が 30 文字を超える場合は次の手順で切り詰める: (1) `yt-` prefix は必ず保持し、slug の**末尾から**文字を削って全体を 30 文字以内にする、(2) 切り詰め後の末尾がハイフンになった場合はそのハイフンも削る、(3) 結果が 6 文字未満・単語の切れ目が不自然で意味が読み取れない場合は自動生成をやめてカスタム入力を求める。例: `yt-very-long-channel-name-tokyo`（31 文字）→ `yt-very-long-channel-name-toky`（30 文字）→ 末尾はハイフンでないのでこれで確定。
```

**Verify**: `rg -n '末尾から' .claude/skills/setup/SKILL.md` → 1 件。`rg -n 'そのハイフンも削る' .claude/skills/setup/SKILL.md` → 1 件。

### Step 2: 契約テストと全体テスト、CHANGELOG

**Verify**: `uv run pytest tests/test_setup_skill.py -q` → exit 0(fail 時は旧文言の assert を新文言へ更新し、コミットに明記)。`uv run pytest tests -q --ignore=tests/integration` → exit 0。

`CHANGELOG.md` の `[Unreleased]`:

```
- setup: project ID の 30 文字超過時の truncate 手順を一義化（prefix 保持・末尾削り・末尾ハイフン除去・不自然ならカスタム入力）
```

**Verify**: `rg -n 'truncate 手順を一義化' CHANGELOG.md` → 1 件。

## Test plan

`tests/test_setup_skill.py` を主ゲートに使う。新規テスト不要。

## Done criteria

- [ ] truncate 規則が手順 3 段 + 具体例で一義化されている
- [ ] `uv run pytest tests -q --ignore=tests/integration` が exit 0
- [ ] `CHANGELOG.md` 追記済み、`plans/README.md` の 016 行を更新済み

## STOP conditions

- 159 行の現物が Current state の引用と一致しない。
- project ID の生成がコード側(`yt-doctor` / setup 系 CLI)にも実装されていて SKILL.md と食い違うことが判明した場合(`rg -n 'project.?id' src/youtube_automation/ -i | head` で確認)— 正はコード側なので STOP して報告。

## Maintenance notes

- GCP の project ID 制約(6-30 文字、小文字開始、末尾ハイフン不可)が変わることは考えにくいが、この段落が制約の唯一の記述箇所。gcloud 側でエラーになった場合はまずここを疑う。
