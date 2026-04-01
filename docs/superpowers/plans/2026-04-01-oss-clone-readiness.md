# OSS クローン & channel-new 対応 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** automation リポを OSS としてクローン可能にし、rjn の全スキルを channel_config 参照で汎用化して移行する

**Architecture:** rjn リポの 19 スキル + コンパニオンファイルを automation の `.claude/skills/` に移行。チャンネル固有値（CLM, RJN 等）を削除し `channel_config.json` 参照に置換。setup_env.sh を 1Password 非依存に汎用化。

**Tech Stack:** Markdown (SKILL.md), JSON, Bash

---

### Task 1: setup_env.sh の汎用化

**Files:**
- Modify: `setup_env.sh`

- [ ] **Step 1: setup_env.sh を汎用化**

```bash
#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if command -v op &>/dev/null; then
  op inject -i "$REPO_ROOT/.env.tpl" -o "$REPO_ROOT/.env" -f
  echo "✓ .env generated from 1Password"
else
  if [ ! -f "$REPO_ROOT/.env" ]; then
    cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
    echo "✓ .env copied from .env.example"
    echo "⚠ Edit .env and set your API keys"
  else
    echo "✓ .env already exists"
  fi
fi
```

- [ ] **Step 2: 動作確認**

Run: `bash setup_env.sh`
Expected: 1Password なし環境では `.env` がコピーされること

- [ ] **Step 3: コミット**

```bash
git add setup_env.sh
git commit -m "chore: setup_env.sh を 1Password 非依存に汎用化"
```

---

### Task 2: auth/SETUP.md のパス修正

**Files:**
- Modify: `auth/SETUP.md`

- [ ] **Step 1: パス修正**

以下を置換:
- `youtube-automation/auth/` → `auth/`（Step 4 のファイル配置パス）
- `cd youtube-automation/auth/` → `cd auth/`（Step 5 のコマンド）
- `.gitignore` セクションの `youtube-automation/auth/` → `auth/`

- [ ] **Step 2: コミット**

```bash
git add auth/SETUP.md
git commit -m "fix: auth/SETUP.md のパスを相対パスに修正"
```

---

### Task 3: channel-new スキルの認証手順更新

**Files:**
- Modify: `.claude/skills/channel-new/SKILL.md`

- [ ] **Step 1: Step 3 を更新**

現在の Step 3:
```
OAuth クライアントは `automation/auth/client_secrets.json` として submodule に含まれる（全チャンネル共通）。
```

変更後:
```
OAuth クライアントはユーザーが自分で作成する。`automation/auth/SETUP.md` の手順に従い、Google Cloud Console で OAuth 2.0 認証情報を作成して `automation/auth/client_secrets.json` に配置すること。テンプレートは `automation/auth/client_secrets_template.json` を参照。
```

- [ ] **Step 2: コミット**

```bash
git add .claude/skills/channel-new/SKILL.md
git commit -m "fix: channel-new スキルの認証手順を OSS 向けに更新"
```

---

### Task 4: value-only スキルの一括移行（ハードコード値なし: 8 スキル）

**Files:**
- Copy from rjn: `collect`, `loop-video`, `masterup`, `short-thumbnail`, `thumbnail-compare`, `viewer-voice`, `wf-next`, `wf-status` の SKILL.md

- [ ] **Step 1: ハードコード値のないスキルをコピー**

```bash
for skill in collect loop-video masterup short-thumbnail thumbnail-compare viewer-voice wf-next wf-status; do
  mkdir -p .claude/skills/$skill
  cp /Users/mba/02-yt/rjn/.claude/skills/$skill/SKILL.md .claude/skills/$skill/
done
```

- [ ] **Step 2: チャンネル固有値が含まれていないことを確認**

Run: `grep -r "CLM\|RJN\|rainy\|jazz\|Rainy Jazz" .claude/skills/{collect,loop-video,masterup,short-thumbnail,thumbnail-compare,viewer-voice,wf-next,wf-status}/`
Expected: マッチなし（loop-video と wf-status に残る場合は Step 3 で対応）

- [ ] **Step 3: 残存するハードコード値があれば汎用化**

各スキルの SKILL.md を読み、`CLM` `RJN` `の場合` 等の注釈を削除。具体的なチャンネル名は「`channel_config.json` の値」に置換。

- [ ] **Step 4: コミット**

```bash
git add .claude/skills/{collect,loop-video,masterup,short-thumbnail,thumbnail-compare,viewer-voice,wf-next,wf-status}/
git commit -m "feat: rjn から value-only スキル 8 件を移行"
```

---

### Task 5: value-only スキルの移行 + 汎用化（軽微な修正: 8 スキル）

**Files:**
- Copy from rjn: `alignment-check`, `analyze`, `benchmark`, `persona`, `viewing-scene`, `short`, `report`, `status` の SKILL.md
- 各 SKILL.md でチャンネル固有値を削除

- [ ] **Step 1: スキルをコピー**

```bash
for skill in alignment-check analyze benchmark persona viewing-scene short report status; do
  mkdir -p .claude/skills/$skill
  cp /Users/mba/02-yt/rjn/.claude/skills/$skill/SKILL.md .claude/skills/$skill/
done
```

- [ ] **Step 2: 各スキルの SKILL.md を読み、チャンネル固有値を汎用化**

パターン:
- `CLM 向けに再評価` → `自チャンネル向けに再評価`
- `CLM との関係性` → `自チャンネルとの関係性`
- `CLM 現行テンプレート` → `現行テンプレート`
- `（CLM の場合）` → 削除
- `（CLM 等の BGM/ambient チャンネル）` → 削除

- [ ] **Step 3: 汎用化の確認**

Run: `grep -r "CLM\|RJN\|AEEJ\|GoA\|の場合）" .claude/skills/{alignment-check,analyze,benchmark,persona,viewing-scene,short,report,status}/`
Expected: マッチなし

- [ ] **Step 4: コミット**

```bash
git add .claude/skills/{alignment-check,analyze,benchmark,persona,viewing-scene,short,report,status}/
git commit -m "feat: rjn から軽微修正スキル 8 件を移行・汎用化"
```

---

### Task 6: config-driven スキルの移行 + 汎用化（中程度の修正: 5 スキル）

**Files:**
- Copy from rjn: `description`, `lyria`, `suno`, `thumbnail`, `upload` の SKILL.md
- Copy: `upload/posting-checklist.md` → `upload/references/posting-checklist.md`

- [ ] **Step 1: スキルをコピー**

```bash
for skill in description lyria suno thumbnail upload videoup; do
  mkdir -p .claude/skills/$skill
  cp /Users/mba/02-yt/rjn/.claude/skills/$skill/SKILL.md .claude/skills/$skill/
done
```

- [ ] **Step 2: コンパニオンファイルを references/ に配置**

```bash
mkdir -p .claude/skills/upload/references
cp /Users/mba/02-yt/rjn/.claude/skills/upload/posting-checklist.md .claude/skills/upload/references/
```

- [ ] **Step 3: 各スキルの SKILL.md を読み、チャンネル固有値を汎用化**

主な置換パターン:
- 具体的なジャンル名（jazz, rainy 等）→ `channel_config.json` の `genre.*` を参照する旨に置換
- チャンネル名（CLM 等）→ 削除または汎用表現に
- `posting-checklist.md` → `references/posting-checklist.md`

lyria は 12 箇所あるため、具体的な例示値（BPM, brightness 等）を「config の値を参照」に置換。

- [ ] **Step 4: 汎用化の確認**

Run: `grep -r "CLM\|RJN\|rainy\|jazz\|Rainy Jazz" .claude/skills/{description,lyria,suno,thumbnail,upload,videoup}/`
Expected: マッチなし

- [ ] **Step 5: コミット**

```bash
git add .claude/skills/{description,lyria,suno,thumbnail,upload,videoup}/
git commit -m "feat: rjn から config-driven スキル 6 件を移行・汎用化"
```

---

### Task 7: 構造的差分スキルの移行 + 汎用化（ideate, wf-new）

**Files:**
- Copy from rjn: `ideate/SKILL.md`, `ideate/collection-lifecycle.md`, `wf-new/SKILL.md`
- Move: `wf-references/schema.md` → `wf-new/references/schema.md`

- [ ] **Step 1: スキルをコピー**

```bash
mkdir -p .claude/skills/ideate/references
cp /Users/mba/02-yt/rjn/.claude/skills/ideate/SKILL.md .claude/skills/ideate/
cp /Users/mba/02-yt/rjn/.claude/skills/ideate/collection-lifecycle.md .claude/skills/ideate/references/

mkdir -p .claude/skills/wf-new/references
cp /Users/mba/02-yt/rjn/.claude/skills/wf-new/SKILL.md .claude/skills/wf-new/
cp /Users/mba/02-yt/rjn/.claude/skills/wf-references/schema.md .claude/skills/wf-new/references/
```

- [ ] **Step 2: ideate/SKILL.md を汎用化**

- ペルソナベースの企画フレームワーク → `channel_config.json` に `ideate` セクションがあればそれを使用、なければデフォルトの 5 企画フレームワークを使用する条件分岐の記述に
- 具体的なジャンル例 → `channel_config.json` の `genre.*` を参照
- `collection-lifecycle.md` → `references/collection-lifecycle.md`

- [ ] **Step 3: wf-new/SKILL.md を汎用化**

- `generation_mode` 分岐 → `channel_config.json` の `gemini_image.generation_mode` を参照する条件として記述
- `workflow-references/schema.md` → `references/schema.md`
- チャンネル固有値を削除

- [ ] **Step 4: 汎用化の確認**

Run: `grep -r "CLM\|RJN\|rainy\|jazz" .claude/skills/{ideate,wf-new}/`
Expected: マッチなし

- [ ] **Step 5: コミット**

```bash
git add .claude/skills/{ideate,wf-new}/
git commit -m "feat: rjn から構造的スキル 2 件を移行・汎用化"
```

---

### Task 8: 最終検証

- [ ] **Step 1: 全スキルのハードコード値チェック**

Run: `grep -r "CLM\|RJN\|AEEJ\|GoA\|rainy\|jazz\|celtic\|fantasy\|Rainy Jazz\|Fantasy Celtic" .claude/skills/ --include="*.md"`
Expected: マッチなし（channel-setup/references/ のテンプレート内プレースホルダーは許容）

- [ ] **Step 2: ディレクトリ構造の確認**

Run: `find .claude/skills -type f | sort`
Expected: 全 23 スキル + references ファイルが正しく配置されている

- [ ] **Step 3: コンパニオンファイルが references/ に配置されていることの確認**

確認対象:
- `.claude/skills/channel-setup/references/` (6 ファイル)
- `.claude/skills/ideate/references/collection-lifecycle.md`
- `.claude/skills/upload/references/posting-checklist.md`
- `.claude/skills/wf-new/references/schema.md`

- [ ] **Step 4: スペックドキュメントをコミット**

```bash
git add docs/superpowers/
git commit -m "docs: OSS クローン対応のスペック・実装計画を追加"
```
