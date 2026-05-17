# リリースノート本文構造テンプレ

`docs/upgrades/v<ver>.md` の構造定義。`/release-notes` スキル Phase 4 でプレースホルダ `{{...}}` を埋めて使う。

実例は本リリースで生成した [`docs/upgrades/v5.5.0.md`](../../../../docs/upgrades/v5.5.0.md) を参照（このテンプレに沿った具体ノート）。

---

## プレースホルダ一覧

| プレースホルダ | 内容 | 例 |
|---|---|---|
| `{{VER}}` | リリースバージョン | `5.5.0` |
| `{{PREV_VER}}` | 前回リリース | `5.4.0` |
| `{{DATE}}` | リリース日 (ISO 8601) | `2026-05-17` |
| `{{TLDR_NEW}}` | TL;DR の「新しくできること」（1 〜 2 文） | `/playlist と /metadata-audit が使える、新規チャンネル立ち上げが 1 コマンドで完結` |
| `{{TLDR_BEHAVIOR}}` | TL;DR の「既存機能が良くなったこと」 | — |
| `{{TLDR_FIX}}` | TL;DR の「直った不具合」 | — |
| `{{TLDR_ACTION}}` | TL;DR の「あなたがやること」 | `pyproject.toml の tag 更新 + uv lock + yt-skills sync の 3 コマンド` |
| `{{TLDR_SPECIAL}}` | TL;DR の「特定リポだけの追加対応」（あれば） | `deepfocus365 だけ local fix の衝突解消` |
| `{{NEW_FEATURES}}` | 🆕 新機能セクションの内容（複数項目） | — |
| `{{BEHAVIOR_CHANGES}}` | 🔧 挙動変更セクションの内容 | — |
| `{{BUGFIXES}}` | 🐛 バグ修正セクション | — |
| `{{INTERNAL}}` | 🧹 内部改善（一言で） | — |
| `{{DOWNSTREAM_TABLE}}` | あなたのチャンネルへの影響テーブル | — |
| `{{SPECIAL_HANDLING}}` | 特定下流への特別対応 | — |
| `{{COMMANDS_BLOCK}}` | 実行手順の bash ブロック（pin / main 追従の 2 パターン） | — |
| `{{VERIFY_BLOCK}}` | 追従後に確認すべきコマンド | — |
| `{{TROUBLESHOOTING_QA}}` | Q&A 形式のトラブルシューティング 3〜5 件 | — |
| `{{CHECKLIST}}` | 最終チェックリスト（5〜8 項目） | — |
| `{{LINKS}}` | 関連 PR / issue / 下流 issue のリンク | — |

---

## テンプレ本体

````markdown
# v{{VER}} アップグレードガイド — チャンネル運営者向け

このページは「**自分のチャンネルリポジトリを v{{VER}} に追従させたい運営者**」向けの平易なガイドです。エンジニア向けの詳細実装は `CHANGELOG.md` と各 PR を参照してください。

> **所要時間の目安**: 5〜10 分（コマンド 3〜4 個実行するだけ）

---

## ⚡ TL;DR（30 秒サマリー）

| 観点 | 内容 |
|---|---|
| 🆕 **新しくできるようになったこと** | {{TLDR_NEW}} |
| 🔧 **既存機能が良くなったこと** | {{TLDR_BEHAVIOR}} |
| 🐛 **直った不具合** | {{TLDR_FIX}} |
| 📋 **あなたがやること** | {{TLDR_ACTION}} |
| ⚠️ **特定リポだけの追加対応** | {{TLDR_SPECIAL}} |

---

## 🎯 このバージョンで何が変わるか

### 🆕 新しくできるようになったこと

{{NEW_FEATURES}}

### 🔧 既存機能が良くなったこと

{{BEHAVIOR_CHANGES}}

### 🐛 直った不具合

{{BUGFIXES}}

### 🧹 内部改善（運営者影響なし、参考のみ）

{{INTERNAL}}

詳細は `CHANGELOG.md` の v{{VER}} セクションを参照してください。

---

## 📋 あなたのチャンネルへの影響

### 現在運用中のチャンネルの追従手順

{{DOWNSTREAM_TABLE}}

### ⚠️ 特定リポでの追加対応

{{SPECIAL_HANDLING}}

---

## 🚀 実行手順

{{COMMANDS_BLOCK}}

---

## 🔍 追従後に確認すべきこと

{{VERIFY_BLOCK}}

---

## ❓ トラブルシューティング

{{TROUBLESHOOTING_QA}}

---

## ✅ 最終チェックリスト

{{CHECKLIST}}

---

## 📎 関連リンク

{{LINKS}}
````

---

## 各項目の書き方ガイドライン

### TL;DR

- 5 行のテーブル。1 行 1 観点で 30 秒で読み切れる粒度
- 「あなたがやること」は **コマンド数を明示**（「3 コマンド」など）して所要時間の見当を立てやすくする
- 「特定リポだけの追加対応」が無いリリースの場合はその行を削除

### 各カテゴリ（🆕 / 🔧 / 🐛）の項目

1 項目あたり以下の構造で記述:

```markdown
#### N. `<entity>` — 一行要約

本文 2〜3 文で背景と何が変わったか。技術用語は使わない。

| 運営者にとって嬉しいこと | 注意点 |
|---|---|
| ... | ... |

関連: PR #NNN (Closes #MMM)
```

**Before / After テーブル** を入れる場合は嬉しさ表の前に配置:

```markdown
| Before（旧） | After（新） |
|---|---|
| ... | ... |
```

### 影響表

3 カラム: リポジトリ名 / 現在の参照 / やること。

例:
```markdown
| リポジトリ | 現在の参照 | やること |
|---|---|---|
| **rjn** | `tag = "vX.Y.Z"` 固定 | tag を v{{VER}} に更新 + uv lock + yt-skills sync |
| **deepfocus365** | main 追従 | uv lock + yt-skills sync + local fix の衝突解消 |
```

### 実行手順

各下流のパターン別に bash ブロックを並べる。コメントで各ステップの意味を明記:

```bash
# 1. pyproject.toml の tag 参照を更新
sed -i '' 's/tag = "vX.Y.Z"/tag = "vA.B.C"/' pyproject.toml

# 2. uv lock を更新（upstream を vA.B.C で固定）
uv lock --upgrade-package youtube-channels-automation

# 3. .claude/skills/ を新バージョンで同期
uv run yt-skills sync

# 4. コミット
git add pyproject.toml uv.lock .claude/skills/
git commit -m "chore: youtube-automation vA.B.C への追従"
git push
```

### トラブルシューティング

Q&A 形式で 3〜5 件。「想定される質問」を運営者目線で書き起こす:

```markdown
### Q1. ...

**A**. ...
```

### 最終チェックリスト

5〜8 項目。GitHub Markdown のタスクリスト `- [ ]` 形式で:

```markdown
- [ ] `pyproject.toml` の参照が v{{VER}} に更新済み
- [ ] `uv lock` で `uv.lock` が更新済み
- [ ] `uv run yt-skills sync` 完了、新規 skill が `.claude/skills/` に存在する
- [ ] `uv run yt-config-migrate verify` が pass
- [ ] コミット + push 完了
```

---

## 書く時の重要原則

1. **二人称・命令形**: 「あなたの」「やること」「気にしなくて OK」
2. **絵文字を機能的に使う**: カテゴリ識別（🆕 / 🔧 / 🐛 / 🧹）、視認性向上（⚡ / 📋 / 🚀 / 🔍 / ❓ / ✅ / 📎 / ⚠️）
3. **before / after を必ず併記**: 挙動変更を説明するときは旧と新を視覚的に対比
4. **「気にしなくて OK」を多用**: 影響が無いことを明示することも親切（特に内部改善）
5. **コマンドはコピペ可能**: コメント付き、改行・引用符に注意。Mac の `sed -i ''` などプラットフォーム依存にも配慮
6. **長文 NG**: 各項目の本文は 2〜3 文以内。詳細実装は `CHANGELOG.md` に委ねる
