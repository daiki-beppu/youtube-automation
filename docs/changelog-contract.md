# CHANGELOG.md フォーマット契約

本ドキュメントは `youtube-automation` リポジトリの `CHANGELOG.md` および GitHub Release 本文の構造を、上流リリーススキルと下流追従スキル / 外部 digest 生成スキルの間で共有する **インターフェース契約** として定義する。

トーンは技術ログのまま維持する（運営者向けの噛み砕きは AI が遷移時に行う）。関数名・パッケージ構造・略語・専門用語の言及はそのまま許容する。

## 対象読者（パース側）

| 読者 | 用途 |
|---|---|
| `/automation-release` prepare（upstream） | `[Unreleased]` 配下に `### Migration` セクションがあるか warning レベルで検証 |
| `/automation-update` Phase 2（下流チャンネルリポジトリ） | `gh release view --json body` で Release 本文を取得、空なら CHANGELOG.md 該当バージョンセクションへ fallback。Top 3 / Fixed / Migration 全文を抽出 |
| libecity `release-notes-chat`（private） | リベシティ「リリースノートチャット」向け digest（プレーンテキスト投稿）の生成 |

## CHANGELOG.md 全体構造

[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) 準拠。

```markdown
# Changelog

## [Unreleased]

（次のリリースに含まれる変更を書き溜める場所）

### Added / Changed / Fixed / Removed / Deprecated / Security

### Migration

所要時間の目安: X〜Y 分

local fix 衝突注意:
- <該当 skill 名>（または「無し」）

サマリ:

- ...

## [<VER>] - <YYYY-MM-DD>

（リリース済みバージョンの記録、上と同じサブセクション構成）

...

[<VER>]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v<VER>
```

- `[Unreleased]` を常に先頭に置く
- 各バージョンは `## [<VER>] - <YYYY-MM-DD>` 形式（`<VER>` は `v` プレフィックス無し、リンク参照側は `v` 付き）
- 日付は ISO 8601
- サブセクション: `Added` / `Changed` / `Deprecated` / `Removed` / `Fixed` / `Security` / `Migration`
- ファイル末尾にリンク参照定義（`[<VER>]: <URL>`）を集約

## `### Migration` セクション必須要素

下流の `/automation-update` が決定論的に抽出できるよう、以下を **必須要素** とする。

### 1. 所要時間の目安（1 行目）

```
所要時間の目安: X〜Y 分
```

- `X` と `Y` は分単位の整数（または「5〜10」のような range）
- 単一値でも可（例: `所要時間の目安: 10 分`）
- 「即時」「数秒」など分単位以外を使う場合も「分」を含めて構わない（例: `所要時間の目安: 1 分未満`）

### 2. local fix 衝突注意

```
local fix 衝突注意:
- <skill 名>: <注意点 1 行>
- <skill 名>: <注意点 1 行>
```

または該当無しの場合:

```
local fix 衝突注意:
- 無し
```

- 列挙対象は `.claude/skills/<name>/` 配下のファイルを今回のリリースで挙動変更した skill 名
- 下流リポジトリで手書き local fix を維持しているケースで `yt-skills sync --force` 時に消える危険がある skill を明示
- 該当無しの場合は明示的に「無し」と書く（セクション自体を省略しない）

### 3. サマリ箇条書き

```
サマリ:

- v<VER> リリースに含まれる主要な変更を 3〜5 行で箇条書き
```

`/automation-update` が Top 3 を AI 抽出する際の参考情報として使う。

## 推奨される追加要素（任意）

- バグ修正への issue / PR 参照（`(#NNN)` 形式）
- 影響範囲の言及（`tag pin の場合は ... / main 追従の場合は ...`）

## 違反検出

| 検出側 | 違反内容 | 反応 |
|---|---|---|
| `/automation-release` prepare 1-4 | `[Unreleased]` 配下に `### Migration` セクション無し | warning + `AskUserQuestion` で続行確認 |
| `/automation-update` Phase 2-3 | `所要時間の目安` / `local fix 衝突注意` の抽出失敗 | fallback で CHANGELOG / Release 本文全体を AI 累積要約 + Phase 3-3 で `[HUMAN STEP]` 確認 |

## 例（v5.5.1 リリースの Migration セクション）

```
### Migration

所要時間の目安: 10〜15 分

local fix 衝突注意:
- short, short-thumbnail, short-release: broken symlink 修正（#345）。upstream 版で上書きされても影響なし
- masterup: `yt-fix-timestamps` 統合（#249）。手書き編集していなければ影響なし
- video-description: bulk-update モード統合（#247）。手書き編集していなければ影響なし

サマリ:

- 新規 skill 7 件（/onboard, /community-post, /community-draft, /short, /short-thumbnail, /short-release, /release-notes - 注: v5.6.0 で削除）と新規 CLI 1 件（yt-doctor）
- 既存 skill の挙動変更（/masterup, /video-description, preflight chapter_max を config 化）
- GOOGLE_CLOUD_PROJECT 必須環境変数の撤廃（ADC fallback 化、#280）
- broken symlink 修正で wheel ビルドエラー解消（#345）
```

## 関連リファレンス

- `.claude/skills/automation-release/references/changelog-promotion.md` — Unreleased → [VER] 昇格手順
- `.claude/skills/automation-release/SKILL.md` — リリース実施フロー（prepare + publish）
- 下流 `.claude/skills/automation-update/SKILL.md` — 各チャンネルリポジトリで CHANGELOG / Release 本文を読み取って追従するスキル
