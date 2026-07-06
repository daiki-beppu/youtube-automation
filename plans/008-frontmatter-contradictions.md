# Plan 008: 兄弟スキル間の frontmatter 矛盾・発動キーワード衝突を解消する

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 8deb3f02..HEAD -- .claude/skills/viewer-voice/SKILL.md .claude/skills/audience-persona-design/SKILL.md .claude/skills/benchmark/SKILL.md .claude/skills/channel-research/SKILL.md .claude/skills/videoup/SKILL.md .claude/skills/video-upload/SKILL.md`
> 差分があれば "Current state" の抜粋と実物を突合し、不一致なら STOP。

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: plans/005-skill-authoring-standard.md(ルール 1「発動条件の相互排他」。005 未完了でも実行可能)
- **Category**: docs
- **Planned at**: commit `8deb3f02`, 2026-07-05

## Why this matters

スキルの frontmatter `description` は、モデルがどのスキルを発動するか決める唯一の入口情報である。監査で 3 つの実害パターンを確認した: (a) `/viewer-voice` は自分を「任意後続スキル」と名乗るが、`/audience-persona-design` は「/viewer-voice を必須入力に」と宣言しており**直接矛盾**、(b) 発動キーワード「競合分析」が `/benchmark`(データ収集)と `/channel-research`(収集済みデータの分析)の両方に登録されており、Sonnet 級モデルはどちらを呼ぶか判定できない、(c) `/videoup`(動画ファイル生成)と `/video-upload`(YouTube 投稿)は名前が酷似しているのに、互いを区別する否定トリガーがない。誤発動は前工程スキップや意図しない工程実行につながる。

## Current state

6 ファイルの frontmatter 3 行目(`description:`)のみが対象。現物(2026-07-05 時点、すべて実読で確認済み):

- `.claude/skills/viewer-voice/SKILL.md:3`
  `"Use when 競合コメントの収集・分析で視聴者インサイトを抽出するとき。「視聴者の声」「コメント分析」「ユーザーリサーチ」で発動。/audience-persona-design らの前提データを作る任意後続スキル"`
- `.claude/skills/audience-persona-design/SKILL.md:3`
  `"Use when ターゲット視聴者を第一ペルソナとして設計・見直しするとき。「ペルソナ設定」「視聴者像」「ターゲット層」で発動。/viewer-voice を必須入力に persona-definition.md を確定"`
- `.claude/skills/benchmark/SKILL.md:3`
  `"Use when 競合チャンネルのベンチマークデータを最新化するとき。「競合分析」「ベンチマーク更新」で発動。docs/benchmarks/*.md を更新"`
- `.claude/skills/channel-research/SKILL.md:3`
  `"Use when /benchmark と /viewer-voice の TTP ベンチマークデータを徹底分析するとき。「競合分析」「チャンネルリサーチ」「TTP 対象抽出」で発動"`
- `.claude/skills/videoup/SKILL.md:3`
  `"Use when 音声ファイルが揃い動画生成が必要なとき。「動画変換」「MP3→MP4」「generate_videos」「videoup」で発動。マスター音源・マスター動画生成を案内"`
- `.claude/skills/video-upload/SKILL.md:3`
  `"Use when コレクションの動画が完成し、YouTubeへのアップロード自動化が必要なとき。Complete Collection のアップロードと live 移行を実行"`

規約: description は **double-quoted string 必須**(値内の `: ` が strict YAML でマッピング区切りと誤解釈されるため。`CLAUDE.md`「### skill frontmatter」)。`tests/test_skill_frontmatter_yaml.py` が YAML 妥当性を機械検証している。

事実確認済みの依存関係(書き換え内容の根拠):
- `/viewer-voice` の出力は `/audience-persona-design` の必須入力である(audience-persona-design 側が「必須入力」と宣言、Phase 1 で `docs/plans/viewer-voice-analysis.md` を要求)。「任意」なのは「/benchmark の後に必ず実行しなくてもよい」という意味で、ペルソナ設計に対しては必須。
- `/benchmark` は YouTube API でデータ**収集**(`docs/benchmarks/*.md` 更新)、`/channel-research` は収集済みデータの**分析専用**(`channel-research/SKILL.md:11-15` に「前提: /benchmark と /viewer-voice を実行済み」と明記)。
- `/videoup` はローカルで MP3→MP4 の動画ファイルを生成、`/video-upload` は完成した動画を YouTube へアップロードし `planning/ → live/` 移行。

## Commands you will need

| 目的 | コマンド | 成功条件 |
|------|----------|----------|
| frontmatter YAML 検証 | `uv run pytest tests/test_skill_frontmatter_yaml.py -q` | exit 0 |
| スキル docs 整合 | `uv run pytest tests/test_skill_docs_consistency.py -q` | exit 0 |
| ユニット全体 | `uv run pytest tests -q --ignore=tests/integration` | exit 0 |

## Scope

**In scope**:
- 上記 6 ファイルの frontmatter `description:` 行(本文は原則触らない。Step 1 の viewer-voice のみ本文中の同表現があれば合わせる)
- `CHANGELOG.md`(`[Unreleased]` への追記)

**Out of scope**:
- 他 41 スキルの description — 発動キーワードの網羅的再設計はしない(規約 005 が新規作成時に効く)。
- `yt-skills sync` 関連コード、スキル本文の手順。
- `/discover-competitors` の description(「競合候補」「競合発掘」で既に区別されている)。

## Git workflow

- worktree 上で作業。base は main。
- コミット例: `docs(skills): 兄弟スキル間の frontmatter 矛盾と発動キーワード衝突を解消`
- push / PR はオペレーターの指示があるまで行わない。

## Steps

### Step 1: viewer-voice ↔ audience-persona-design の矛盾を解消する

`viewer-voice/SKILL.md:3` の description 末尾「/audience-persona-design らの前提データを作る任意後続スキル」を、依存を一義化した表現に置き換える:

```
/audience-persona-design の必須入力（viewer-voice-analysis.md）を作る前工程。実行タイミングは任意
```

(「必須入力を作る」と「実行タイミングは任意」を分離することで矛盾を解く。)
本文(`viewer-voice/SKILL.md` 内)に「任意後続スキル」という同表現があれば同様に直す: `rg -n '任意後続' .claude/skills/viewer-voice/SKILL.md` で検索。

**Verify**: `rg -n '必須入力' .claude/skills/viewer-voice/SKILL.md` → frontmatter でヒット。`rg -n '任意後続スキル' .claude/skills/viewer-voice/SKILL.md` → 0 件。

### Step 2: 「競合分析」キーワードの衝突を解消する

- `benchmark/SKILL.md:3`: 「競合分析」を「競合データ収集」に置き換え、末尾に否定トリガーを追加:
  `"Use when 競合チャンネルのベンチマークデータを最新化するとき。「競合データ収集」「ベンチマーク更新」で発動。docs/benchmarks/*.md を更新。収集済みデータの分析は /channel-research"`
- `channel-research/SKILL.md:3`: 末尾に前提とデータ収集の区別を追加:
  `"Use when /benchmark と /viewer-voice の TTP ベンチマークデータを徹底分析するとき。「競合分析」「チャンネルリサーチ」「TTP 対象抽出」で発動。データ収集・更新は /benchmark（未実行なら先に案内）"`

(「競合分析」は分析側の channel-research だけに残す。)

**Verify**: `rg -l '「競合分析」' .claude/skills/*/SKILL.md` → `channel-research` のみ。`rg -n '競合データ収集' .claude/skills/benchmark/SKILL.md` → 1 件。

### Step 3: videoup / video-upload の相互否定トリガーを追加する

- `videoup/SKILL.md:3` 末尾に追加: `。YouTube への投稿は /video-upload（本スキルはローカルで動画ファイルを生成するのみ）`
- `video-upload/SKILL.md:3` 末尾に追加: `。「アップロード」「公開して」で発動。動画ファイルの生成（MP3→MP4）は /videoup`

**Verify**: `rg -n 'video-upload' .claude/skills/videoup/SKILL.md | head -3` → frontmatter 行にヒット。`rg -n '/videoup' .claude/skills/video-upload/SKILL.md | head -3` → frontmatter 行にヒット。

### Step 4: YAML 妥当性と double-quote を確認する

6 ファイルすべてで description が 1 行の double-quoted string のままであること。

**Verify**: `uv run pytest tests/test_skill_frontmatter_yaml.py -q` → exit 0。

### Step 5: CHANGELOG に追記する

```
- skills frontmatter: viewer-voice/audience-persona-design の依存表現矛盾、benchmark/channel-research の「競合分析」衝突、videoup/video-upload の相互否定トリガー欠如を解消
```

**Verify**: `rg -n 'skills frontmatter' CHANGELOG.md` → 1 件。

### Step 6: テスト全体を確認する

**Verify**: `uv run pytest tests -q --ignore=tests/integration` → exit 0。`tests/test_skill_docs_consistency.py` が description 文言を assert していて fail した場合は期待値を新文言へ更新する(コミットに明記)。

## Test plan

既存の `test_skill_frontmatter_yaml.py`(YAML 妥当性)と `test_skill_docs_consistency.py` を検証ゲートに使う。新規テストは不要。

## Done criteria

- [ ] 「任意後続スキル」表現が viewer-voice から消え、「必須入力を作る前工程」に置き換わっている
- [ ] 「競合分析」キーワードを含む description が channel-research のみ
- [ ] videoup / video-upload が互いを名指しで区別している
- [ ] 6 ファイルとも description は double-quoted 1 行のまま
- [ ] `CHANGELOG.md` 追記済み、ユニットテスト exit 0
- [ ] `plans/README.md` の 008 行を更新済み

## STOP conditions

- 6 ファイルの description 現物が Current state の引用と一致しない(drift)。
- `tests/test_skills_rename.py` など、description の文言に依存するテストが期待値更新だけでは直らない形で fail する。
- description の変更が `yt-skills sync` の差分検出以外の機構(例: docs 自動生成)に影響することが判明した場合。

## Maintenance notes

- 下流リポジトリへは次回リリース後の `yt-skills sync` で伝播する。sync 前後で差分が出るのは意図どおり。
- 発動キーワードの重複検出は現状人力。`test_skill_docs_consistency.py` の系譜で「同一鉤括弧キーワードが複数スキルの description に現れたら fail」という機械チェックを追加できる(follow-up、この plan では見送り)。
- レビュー観点: description が 1 行で読み切れる長さに収まっているか(長すぎる description は skill 一覧表示で切り捨てられる)。
