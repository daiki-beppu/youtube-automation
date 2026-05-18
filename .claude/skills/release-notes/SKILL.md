---
name: release-notes
description: Use when youtube-automation の non-trivial なリリース（tag + GitHub Release 作成済み）後に、チャンネル運営者向け（非エンジニア向け）のアップグレードガイドを作成し、ダウンストリームへの影響分析と追従 issue 起票・コメント追加までを一気通貫で行いたいとき。「リリースノート作成」「v5.x.y の説明」「運営者向けまとめ」「アップグレードガイド」「ダウンストリーム影響分析」「v5.x.y への追従 issue」「リリース後の運営者通知」など、リリース後の運営者向けドキュメント生成および追従調整に関わる場面で使用すること。
---

## Overview

youtube-automation の non-trivial なリリース（破壊的変更や新機能を含むメジャー / マイナー）の **後** に、以下を一気通貫で生成・配信するスキル:

1. **チャンネル運営者向けアップグレードガイド** `docs/upgrades/v<ver>.md`（非エンジニア向け、**AI にお任せプロンプト** + TL;DR + カテゴリ別変更 + 影響箇条書き + 実行手順 + Q&A）。**プレーンテキスト出力**：全体を ```` ```text ... ``` ```` フェンスで囲み、本文では Markdown 記法（`#`/`|`/`**`/絵文字）を使わない（Notion・Slack 等にコピペしても読める形を維持）。先頭の「AI にお任せプロンプト」は運営者が下流リポの Claude Code にそのまま貼れば追従作業を自動実行できるコピペ用ブロック（テンプレの `{{AI_PROMPT}}` を参照）
2. **CHANGELOG.md 同期**: `[Unreleased]` → `[v<ver>] - <date>` への昇格 + 新規 `[Unreleased]` + リンク定義追加
3. **ダウンストリーム影響分析**: 下流リポジトリ（rjn / deepfocus365 等）の `pyproject.toml` pin と `.claude/skills/` の local fix を実物確認
4. **追従 issue 起票 / コメント追加**: 未起票なら issue 新規作成、既起票ならアップグレードガイドへのリンクコメントを追加
5. **GitHub Release 本文の更新（オプション）**: auto-generated PR list の冒頭にアップグレードガイドへのリンクを追記

**前提**: tag `v<ver>` が main に push 済み、GitHub Release が `--generate-notes` で作成済み（このスキルは「リリース後」専用）。

`/release` スキル（Node.js 向け）とは責務が異なる。本スキルは **publish 後の運営者向けノート生成 + 影響波及対応** に特化。

## Instructions

**実行場所**: youtube-automation リポジトリのルート（`/Users/mba/02-yt/automation`）

### Phase 1: リリース内容の収集

1. **前回 tag と今回 tag を確定**:
   ```bash
   gh release list --limit 3
   git tag --sort=-v:refname | head -3
   ```
   ユーザーに「今回作るノートのバージョンは `v5.5.0` で、前回は `v5.4.0` でいいですか？」と確認。

2. **コミット差分の抽出**:
   ```bash
   git log v<prev>..v<curr> --no-merges --oneline
   git log v<prev>..v<curr> --no-merges --pretty=format:"%H %s"
   ```
   差分が 100 件超なら、`--first-parent` でマージコミットのみに絞る選択肢も提示。

3. **PR / issue の逆引き**:
   各コミットメッセージから `(#NNN)` を抽出し、`gh pr view <N> --json title,body,labels` で本文と Closes 参照を取得。Closes/Refs/Fixes に紐づく issue 番号を集約。

4. **コミット種別の分類**:
   - `feat:` → 🆕 新機能
   - `fix:` → 🐛 バグ修正
   - `refactor:` / `feat:` で **挙動変更を伴う** もの → 🔧 挙動変更
   - `chore:` / `docs:` / `test:` / `perf:` / `ci:` → 🧹 内部改善

   分類が曖昧な場合は PR 本文を読み、運営者影響の有無を判定（影響あれば 🆕/🔧/🐛、なければ 🧹）。

### Phase 2: 非エンジニア向け翻訳・分類

`references/release-notes-template.md` のテンプレ構造に沿って各変更を整形する。

各変更について **2 つの箇条書き** を生成（テーブルではなくプレーンテキストの `- 嬉しいこと:` / `- 注意点:` 形式）:

- **運営者にとって嬉しいこと**: 機能の意味を平易な言葉で、運営者にとっての価値で表現
- **注意点・必要な対応**: ユーザーがやるべきこと、または「気にしなくて OK」を明示

翻訳ガイドライン:

| 技術用語（NG）| 平易な言い換え（OK） |
|---|---|
| API call / endpoint | YouTube への送信 / 反映 |
| rsync で同期 | ファイル同期方法を改善し、サムネや設定も漏れなくコピーされるように |
| refactor / namespace 刷新 | 内部処理の整理（運営者影響なし） |
| Mixin / dataclass | （言及しない、必要なら「内部構造の改善」と一言） |
| OAuth scope | YouTube への認可情報 |
| HTTP 400 / 403 | 反映エラー / 認可エラー |

**重大変更 Top 5** を抽出して TL;DR テーブルに配置。判定基準:
- ダウンストリームで必須対応が発生するか
- 運営者の日常操作に直接影響するか
- バグ修正なら、これまで失敗していた操作が成功するようになるか

**内部改善は最低限の言及のみ**（運営者影響なしを明示）。

### Phase 3: ダウンストリーム影響分析

`references/downstream-discovery.md` の手順で下流リポジトリを発見。

1. **下流リポジトリの一覧化**:
   - `~/02-yt/` 配下の git リポジトリを `ls ~/02-yt/` で列挙
   - 各ディレクトリの `pyproject.toml` を grep して `youtube-channels-automation` の参照を抽出:
     ```bash
     for d in ~/02-yt/*/; do
       [ -f "$d/pyproject.toml" ] || continue
       echo "=== $d ==="
       grep -E "youtube-channels-automation" "$d/pyproject.toml" | head -3
     done
     ```
   - **automation 自身は除外**（自己参照のため）

2. **pin 形式の判定**:
   - `tag = "vX.Y.Z"` 形式 → 明示 pin、bump 必須
   - `branch = "main"` または無印 → main 追従、`uv lock` で自動取り込み
   - `rev = "<sha>"` 形式 → コミット pin、別途判断

3. **local fix の検出**（特に skill 編集）:
   今回のリリースで挙動変更があった skill ファイルを特定し、各下流リポジトリの該当ファイルで grep:
   ```bash
   # 例: /masterup Step 6 の rsync 化 (#321) が今回のリリースに含まれる場合
   for d in ~/02-yt/*/; do
     [ -f "$d/.claude/skills/masterup/SKILL.md" ] || continue
     if grep -q "rsync\|git rev-parse --git-common-dir" "$d/.claude/skills/masterup/SKILL.md"; then
       echo "[local fix?] $d/.claude/skills/masterup/SKILL.md"
     fi
   done
   ```
   ヒットしたら「**local fix の衝突懸念あり**」としてレポートに含める。

4. **影響度マトリクス生成**:
   `references/impact-assessment-rules.md` のルールに沿って、各下流リポジトリ × 各変更を以下に分類:
   - 🔴 **必須対応**: bump や config migration や local fix の解消が必要
   - 🟡 **確認推奨**: 動作する想定だが念のため検証推奨
   - 🟢 **影響なし**: 操作不要

   結果をテーブル化してアップグレードガイドの「あなたのチャンネルへの影響」セクションに反映。

### Phase 4: 出力・反映

`references/release-notes-template.md` のプレースホルダを埋めて以下を生成:

1. **`docs/upgrades/v<ver>.md`** を新規作成
2. **`CHANGELOG.md` の昇格**: `references/changelog-promotion.md` の手順で実施
3. **追従 issue の起票またはコメント**:
   - 各下流リポジトリで既存 issue を検索:
     ```bash
     gh issue list --repo daiki-beppu/<repo> --state all --search "v<ver>" --json number,title,state
     ```
   - **既存 issue が無い** → 新規起票:
     ```bash
     gh issue create --repo daiki-beppu/<repo> --title "chore: youtube-automation v<ver> への追従" --body-file /tmp/issue-<repo>-v<ver>.md
     ```
   - **既存 issue がある** → コメント追加:
     ```bash
     gh issue comment <N> --repo daiki-beppu/<repo> --body "非エンジニア向けの詳細手順を docs/upgrades/v<ver>.md にまとめました: https://github.com/daiki-beppu/youtube-automation/blob/main/docs/upgrades/v<ver>.md"
     ```

4. **GitHub Release 本文の更新（オプション）**:
   ```bash
   # 現本文の冒頭にアップグレードガイドへのリンクを追記
   current=$(gh release view v<ver> --json body --jq .body)
   prepend="📖 **チャンネル運営者向けアップグレードガイド**: [docs/upgrades/v<ver>.md](https://github.com/daiki-beppu/youtube-automation/blob/main/docs/upgrades/v<ver>.md)\n\n---\n\n"
   gh release edit v<ver> --notes "${prepend}${current}"
   ```
   ユーザーに事前確認してから実行する（リリース本文の上書きは目立つ action のため）。

### Phase 5: PR 作成

このスキル自身を含むコミットを `docs/v<ver>-release-notes` ブランチで切ってから:

```bash
git checkout -b docs/v<ver>-release-notes
git add docs/upgrades/v<ver>.md CHANGELOG.md
git commit -m "docs: v<ver> アップグレードガイド + CHANGELOG 昇格"
git push -u origin docs/v<ver>-release-notes
```

base branch は通常 `main`（または次バージョンの `release/vX.Y.Z`）。`/pr` スキルで PR 作成。

## Gotchas

- **「リリース前」には呼ばない**: tag が無い段階では `git log v<prev>..v<curr>` の右辺が解決できない。tag + GitHub Release 作成済みであることを Phase 1 冒頭で必ず確認
- **下流 local fix の見落とし**: `.claude/skills/<name>/SKILL.md` の grep だけでは検出漏れがある。`yt-skills diff` の出力も併用するのが確実だが、対話的なので結果整形が手間。両方を試して整合確認
- **CHANGELOG.md の `[Unreleased]` 残骸**: 過去リリース時に昇格を忘れていた場合、Unreleased に複数バージョンの内容が累積している。今回のリリース対象のみ抽出するのは困難なので、潔く「v<ver> リリースに累積で含まれる」として全部昇格させる
- **issue 起票の重複防止**: `gh issue list --search "v<ver>"` で既存 issue を必ず確認。重複起票はノイズになる
- **リンクが一時的に 404**: docs/upgrades/v<ver>.md を main にマージする前に issue コメントで参照リンクを貼ると、PR マージまで 404 になる。Phase 4 の issue コメントは **PR マージ後** に行うのが筋（このスキルでは PR 作成までを Phase 5、コメント追加は別途呼び直しで実施）

## Rules

- このスキル自体の編集は **takt 経由 NG**（CLAUDE.md 規約: skill 編集は通常の Claude Code 対話セッションで）
- `docs/upgrades/v<ver>.md` のスタイルは **必ず `references/release-notes-template.md` のテンプレ構造を踏襲**（読者の認知負荷を一定に保つため）。**プレーンテキスト出力**（外側 ```` ```text ``` ```` フェンス、本文に Markdown 記法を使わない）が必須
- 非エンジニア向け = チャンネル運営者向け。コード差分・関数名・パッケージ構造には言及しない（必要なら「内部実装の改善」と一言で済ませる）
- 各変更について「運営者にとって嬉しいこと」「注意点」を必ず 1〜2 文で書く（長文 NG）
- 重大変更 Top 5 以外は詳細表に格下げ。TL;DR セクションは 30 秒で読み切れる長さに収める
- 下流リポジトリの実物検査（local fix grep / pin 形式判定）は **必ず実物コマンド** で確認。記憶に頼らない
- issue 起票 / コメント追加は **PR マージ後** に行う（リンクの 404 を避ける）

## Cross References

- `references/release-notes-template.md` — リリースノートの本文構造（プレースホルダ付き）
- `references/impact-assessment-rules.md` — 変更の分類と影響度判定ルール
- `references/downstream-discovery.md` — 下流リポジトリ発見と pin / local fix 検出の具体手順
- `references/changelog-promotion.md` — `CHANGELOG.md` Unreleased 昇格手順（Keep a Changelog 準拠）
- `/release` — Node.js 向け（このリポジトリでは使えない、参考のみ）
- `/issue` — 下流リポジトリへの新規 issue 起票（Phase 4 で連携）
- `/pr` — PR 作成（Phase 5 で連携）
- `/cp` — commit + push（Phase 5 で連携）
