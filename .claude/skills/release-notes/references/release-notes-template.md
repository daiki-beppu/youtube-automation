# リリースノート本文構造テンプレ

> ⚠ **下流連携あり**: 本テンプレで定義する `■ AI にお任せする場合のプロンプト` / `■ TL;DR（30 秒サマリー）` / `■ このバージョンで何が変わるか` および冒頭の `所要時間の目安: X〜Y 分` は、下流 private リポジトリ libecity の `release-notes-chat` スキルがパースする **互換性のあるインターフェース**。改修時は libecity 側も同時更新が必要。詳細は `../SKILL.md` の「⚠ 改修時の注意 / 下流連携先」セクション（issue #336）を参照。

`docs/upgrades/v<ver>.md` の構造定義。`/release-notes` スキル Phase 4 でプレースホルダ `{{...}}` を埋めて使う。

**重要**: 出力は **プレーンテキスト**。GitHub 上でコピペしやすいよう、全体を ```` ```text ... ``` ```` フェンスで囲み、Markdown 記法（`#` 見出し、`|` テーブル、`**bold**`、`` `code` ``、絵文字）を本文では使わない。区切りは `■` / `──` などのテキスト記号で表現する。

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
| `{{AI_PROMPT}}` | チャンネルリポジトリの Claude Code に貼って追従させるプロンプト（先頭セクション） | — |
| `{{NEW_FEATURES}}` | 新機能セクションの内容（複数項目） | — |
| `{{BEHAVIOR_CHANGES}}` | 挙動変更セクションの内容 | — |
| `{{BUGFIXES}}` | バグ修正セクション | — |
| `{{INTERNAL}}` | 内部改善（一言で） | — |
| `{{DOWNSTREAM_TABLE}}` | あなたのチャンネルへの影響テーブル（プレーンテキスト化） | — |
| `{{SPECIAL_HANDLING}}` | 特定下流への特別対応 | — |
| `{{COMMANDS_BLOCK}}` | 実行手順（pin / main 追従の 2 パターン、2 スペースインデント） | — |
| `{{VERIFY_BLOCK}}` | 追従後に確認すべきコマンド（2 スペースインデント） | — |
| `{{TROUBLESHOOTING_QA}}` | Q&A 形式のトラブルシューティング 3〜5 件 | — |
| `{{CHECKLIST}}` | 最終チェックリスト（5〜8 項目、`[ ]` 記法） | — |
| `{{LINKS}}` | 関連 PR / issue / 下流 issue のリンク | — |

---

## テンプレ本体

````text
v{{VER}} アップグレードガイド — チャンネル運営者向け
====================================================

このページは youtube-channels-automation を v{{VER}} へ追従させたいチャンネル運営者向けの平易なガイドです。エンジニア向けの詳細実装は CHANGELOG.md と各 PR を参照してください。

所要時間の目安: 5〜10 分（コマンド 3〜4 個実行するだけ）


■ AI にお任せする場合のプロンプト

以下をそのままチャンネルリポジトリの Claude Code に渡せば、v{{VER}} への追従を自動実行します。dry-run / 差分確認のステップで一度立ち止まるので、内容を確認してから承認してください。

{{AI_PROMPT}}


■ TL;DR（30 秒サマリー）

- 新しくできるようになったこと:
  {{TLDR_NEW}}

- 既存機能が良くなったこと:
  {{TLDR_BEHAVIOR}}

- 直った不具合:
  {{TLDR_FIX}}

- あなたがやること:
  {{TLDR_ACTION}}

- 特定リポだけの追加対応:
  {{TLDR_SPECIAL}}


■ このバージョンで何が変わるか

── 新しくできるようになったこと ──

{{NEW_FEATURES}}


── 既存機能が良くなったこと ──

{{BEHAVIOR_CHANGES}}


── 直った不具合 ──

{{BUGFIXES}}


── 内部改善（運営者影響なし、参考のみ）──

{{INTERNAL}}

詳細は CHANGELOG.md の v{{VER}} セクションを参照してください。


■ あなたのチャンネルへの影響

── 現在運用中のチャンネルの追従手順 ──

{{DOWNSTREAM_TABLE}}


── 特定リポでの追加対応 ──

{{SPECIAL_HANDLING}}


■ 実行手順

{{COMMANDS_BLOCK}}


■ 追従後に確認すべきこと

{{VERIFY_BLOCK}}


■ トラブルシューティング

{{TROUBLESHOOTING_QA}}


■ 最終チェックリスト

{{CHECKLIST}}


■ 関連リンク

{{LINKS}}
````

---

## 各項目の書き方ガイドライン

### AI にお任せする場合のプロンプト（`{{AI_PROMPT}}`）

ガイド冒頭、TL;DR の **前** に配置する。運営者がページを開いて最初に目にし、コピーひとつでチャンネルリポジトリの Claude Code に追従作業を委任できる位置にする。

2 スペースインデントの平文ブロックで、次の要素を含める:

1. **pyproject.toml の参照形式確認**（tag pin か main 追従かを Claude 側に判定させる）
2. **`uv lock --upgrade-package youtube-channels-automation`**
3. **`uv run yt-skills diff`** で local fix の有無を確認 → 差分があれば運営者に見せて承認を取らせる（即時 sync しない）
4. **`uv run yt-skills sync`**（このリリースで配布される新スキル名を明記）
5. **追従後の動作確認**: `uv run yt-config-migrate verify` + `uv run yt-channel-status`。**確認コマンドの直下に「これらは v{{VER}} に確実に存在する CLI。command not found / No module named が出ても『ガイドが古い』と判断せず、`uv sync` → `uv pip list | grep youtube-channels-automation` の順で env 側を疑え」の 1 行を必ず添える**（ガイド全文を読まずプロンプトだけで作業する agent が偽陽性で確認をスキップするのを防ぐガード。issue #335 で実害発生済み）
6. **コミット & push**: `chore: youtube-automation v{{VER}} への追従`（add 対象: `pyproject.toml uv.lock .claude/skills/`）

末尾に **このリリースで衝突しやすい local fix の候補**（該当 skill 名を列挙）と、**承認なしに上書きしないこと**を明記する。詳細仕様は `https://github.com/daiki-beppu/youtube-automation/blob/main/docs/upgrades/v{{VER}}.md` を参照させる。

実例は `docs/upgrades/v5.5.0.md` の「AI にお任せする場合のプロンプト」セクションを参照。

### TL;DR

- 5 項目の箇条書き。1 項目 1 観点で 30 秒で読み切れる粒度
- 「あなたがやること」は **コマンド数を明示**（「3 コマンド」など）して所要時間の見当を立てやすくする
- 「特定リポだけの追加対応」が無いリリースの場合はその行を削除

### 各カテゴリ（新機能 / 挙動変更 / バグ修正）の項目

1 項目あたり以下の構造で記述:

```
N. <entity> — 一行要約

本文 2〜3 文で背景と何が変わったか。技術用語は使わない。

- 嬉しいこと: ...
- 注意点: ...

関連: PR #NNN (Closes #MMM)
```

**Before / After** を入れる場合は嬉しさ箇条書きの前に配置:

```
Before: ...
After:  ...
```

### 影響箇条書き

リポジトリごとに 3 要素（現在の参照 / やること）を併記。

例:

```
- rjn: tag = "vX.Y.Z" 固定 → tag を v{{VER}} に更新 + uv lock + yt-skills sync
- deepfocus365: main 追従 → uv lock + yt-skills sync + local fix の衝突解消
```

### 実行手順

各下流のパターン別に 2 スペースインデントで並べる。コメントで各ステップの意味を明記:

```
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

### 追従後確認（`{{VERIFY_BLOCK}}`）

検証コマンド本体（2 スペースインデント）の **前** に、以下の定型リードインを必ず入れる:

```
以下のコマンドはすべて v{{VER}} のリリース時点で entry point として登録済みです（uv run yt-config-migrate / uv run yt-channel-status / uv run yt-skills など）。command not found / No module named 相当が出た場合は「ガイドが古い」「コマンドが存在しない」と判断せず、env 側の問題として以下の順で切り分けてください（詳細はトラブルシューティング参照）:

  1. uv sync
  2. uv pip list | grep youtube-channels-automation で v{{VER}} が入っているか確認
  3. ダメなら uv cache clean && uv lock --upgrade-package youtube-channels-automation で再ロック
```

このリードインが無いと、ダウンストリーム実行 agent が env 側の不整合（`uv sync` 未実行 / 古い venv / cache）を「ガイドの誤り」と早合点して追従後確認をスキップする偽陽性が発生する（issue #335 で実害）。バージョンに依存しない普遍的なガードなので、リリースごとに省略しないこと。

### トラブルシューティング

Q&A 形式で 3〜5 件。「想定される質問」を運営者目線で書き起こす:

```
Q1. ...
A.  ...
```

**必須 Q**: 「追従後確認コマンド（`yt-config-migrate verify` / `yt-channel-status` / `yt-skills` 等）が `command not found` / `No module named ...`」系の Q を **1 件必ず含める**。回答は env 側切り分け手順を明記:

```
1. uv sync
2. uv pip list | grep youtube-channels-automation で当該バージョンが入っているか確認
3. ダメなら uv cache clean && uv lock --upgrade-package youtube-channels-automation && uv sync
4. それでも解決しなければ .venv 削除 → uv sync で作り直し
```

「これらは entry point として登録済みなのでガイドの記載は誤りではない、env 側の問題」を明示すること。これを省くと agent が早合点で追従後確認をスキップする偽陽性が発生する（issue #335 で実害）。

### 最終チェックリスト

5〜8 項目。GitHub Markdown のタスクリスト記法 `[ ]` を本文として埋め込む（外側コードブロック内では未チェック表示のままだが、コピペで Notion / Slack 等でもそのまま読める形を維持）:

```
  [ ] pyproject.toml の参照が v{{VER}} に更新済み
  [ ] uv lock で uv.lock が更新済み
  [ ] uv run yt-skills sync 完了、新規 skill が .claude/skills/ に存在する
  [ ] uv run yt-config-migrate verify が pass
  [ ] コミット + push 完了
```

---

## 書く時の重要原則

1. **プレーンテキスト出力**: 外側を ```` ```text ... ``` ```` フェンスで囲み、本文に `#` / `|` / `**` / `` ` `` / 絵文字を使わない。区切りは `■` `──` を使う。コードや CLI も 2 スペースインデントの平文で表現
2. **二人称・命令形**: 「あなたの」「やること」「気にしなくて OK」
3. **before / after を必ず併記**: 挙動変更を説明するときは旧と新を 2 行で対比（`Before:` / `After:`）
4. **「気にしなくて OK」を多用**: 影響が無いことを明示することも親切（特に内部改善）
5. **コマンドはコピペ可能**: コメント付き、改行・引用符に注意。Mac の `sed -i ''` などプラットフォーム依存にも配慮
6. **長文 NG**: 各項目の本文は 2〜3 文以内。詳細実装は CHANGELOG.md に委ねる
