# ダウンストリームリポジトリ発見と検査の手順

`/release-notes` スキル Phase 3 で参照する具体手順。

---

## 1. 下流リポジトリの一覧化

`~/02-yt/` 配下の git リポジトリを列挙する:

```bash
ls -d ~/02-yt/*/ 2>/dev/null
```

各ディレクトリで `.git` の存在を確認:

```bash
for d in ~/02-yt/*/; do
  [ -d "$d/.git" ] && echo "$d"
done
```

`automation` 自身も含まれるので、上流リポジトリは除外する:

```bash
for d in ~/02-yt/*/; do
  [ -d "$d/.git" ] || continue
  [ "$(basename "$d")" = "automation" ] && continue
  echo "$d"
done
```

### 想定される下流（2026-05 時点）

- `~/02-yt/rjn/` — daiki-beppu/youtube-rain-jazz-night（雨ジャズ夜系）
- `~/02-yt/deepfocus365/` — daiki-beppu/deepfocus365（集中音楽系）
- 将来追加されるチャンネルも同じ規約で配置される想定

GitHub の repo 名は `git remote get-url origin` で取得:

```bash
cd "$d" && git remote get-url origin
```

`git@github.com:daiki-beppu/<name>.git` または `https://github.com/daiki-beppu/<name>.git` 形式から `<name>` を抽出。

---

## 2. pin 形式の判定

各下流の `pyproject.toml` で `youtube-channels-automation` の参照を見る:

```bash
grep -A 2 "youtube-channels-automation" "$d/pyproject.toml"
```

### 3 つのパターン

**A. tag pin**:
```toml
youtube-channels-automation = { git = "https://github.com/daiki-beppu/youtube-automation", tag = "v5.4.0" }
```
→ **tag を v<ver> に更新する必要あり** → 🔴 必須

**B. branch 追従（main）**:
```toml
youtube-channels-automation = { git = "https://github.com/daiki-beppu/youtube-automation", branch = "main" }
# または無印
youtube-channels-automation = { git = "https://github.com/daiki-beppu/youtube-automation" }
```
→ `uv lock --upgrade-package youtube-channels-automation` で main の最新を取り込む → 🔴 必須（自動だが lock update が要）

**C. rev (sha) pin**:
```toml
youtube-channels-automation = { git = "...", rev = "abc1234" }
```
→ コミット指定 pin、bump 戦略はユーザー判断。新 tag のコミット sha に更新するか、引き続き古い sha で固定するか確認

### tag pin の自動置換例

```bash
# Mac
sed -i '' 's/tag = "v5.4.0"/tag = "v5.5.0"/' "$d/pyproject.toml"

# Linux
sed -i 's/tag = "v5.4.0"/tag = "v5.5.0"/' "$d/pyproject.toml"
```

スキル内では「sed の `-i ''` は Mac 用」と明記する（クロスプラットフォーム想定）。

---

## 3. local fix の検出

今回のリリースで挙動変更があった skill ファイルを特定し、各下流の該当ファイルで local 編集が無いか確認。

### 検出対象の skill ファイルを抽出

リリース対象 PR から、`.claude/skills/<name>/SKILL.md` を変更したものをリストアップ:

```bash
# automation 側で
git diff --name-only v<prev>..v<curr> | grep '^\.claude/skills/' | grep 'SKILL\.md$'
```

例（v5.5.0）:
- `.claude/skills/masterup/SKILL.md`
- `.claude/skills/wf-next/SKILL.md`
- `.claude/skills/channel-setup/SKILL.md`
- `.claude/skills/collection-ideate/SKILL.md`

### 各下流で grep

挙動変更の特徴的なキーワード（rsync, git rev-parse, freshness_days など）が下流側に既に書き込まれていれば、local fix が残っている可能性:

```bash
# masterup の rsync 化 (#321) が今回入った場合
for d in ~/02-yt/*/; do
  file="$d/.claude/skills/masterup/SKILL.md"
  [ -f "$file" ] || continue
  if grep -qE "rsync.*-a|git rev-parse --git-common-dir" "$file"; then
    echo "[local fix?] $file"
  fi
done
```

### yt-skills diff の活用（推奨）

実物比較は `yt-skills diff` の方が正確:

```bash
cd "$d"
uv run yt-skills diff 2>&1 | head -50
```

差分が出るスキルは、下流側で手書き編集が入っているか、upstream の更新が未配布。`yt-skills sync` で upstream 配布版で上書きするか、手動マージするか判断材料になる。

### 検出結果のレポート形式

「local fix の衝突懸念」として以下を集約:

```markdown
| 下流 | ファイル | 検出内容 | 推奨対応 |
|---|---|---|---|
| deepfocus365 | .claude/skills/masterup/SKILL.md | rsync ベースの記述あり | upstream で同等修正済み → 破棄して sync で上書き |
| deepfocus365 | .claude/skills/wf-next/SKILL.md | git rev-parse --git-common-dir あり | upstream で同等修正済み → 破棄 |
| rjn | （該当なし） | — | — |
```

---

## 4. 既存 issue の確認

下流リポジトリで「v<ver> 追従」関連の既存 issue を検索:

```bash
gh issue list --repo daiki-beppu/<repo> --state all --search "v<ver>" --json number,title,state
```

### 既存 issue がある場合

- 状態が `open` → コメント追加でアップグレードガイドへのリンクを通知
- 状態が `closed` → リリースノートで「対応済み」として参照

### 既存 issue が無い場合

- 新規起票（タイトル: `chore: youtube-automation v<ver> への追従`）

---

## 5. 配布されているか確認（オプション）

下流側の `pyproject.toml` の lock ファイル（`uv.lock`）を見て、現時点で参照している commit を確認:

```bash
grep -A 5 "youtube-channels-automation" "$d/uv.lock" | head -10
```

`resolution = "..."` や `rev = "..."` で commit sha を取得し、その sha が v<prev> 〜 v<curr> のどこにあるか:

```bash
git log --oneline | grep <sha>
```

これで「現在の lock は v5.4.0 ベース」「すでに main の最新を取り込み済み」などが判定可能。
