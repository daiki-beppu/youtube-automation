# CHANGELOG.md フォーマット契約

本ドキュメントは `youtube-automation` リポジトリの `CHANGELOG.md` および GitHub Release 本文の構造を、上流リリーススキルと下流追従スキル / 外部 digest 生成スキルの間で共有する **インターフェース契約** として定義する。

トーンは技術ログのまま維持する（運営者向けの噛み砕きは AI が遷移時に行う）。関数名・パッケージ構造・略語・専門用語の言及はそのまま許容する。

## 対象読者（パース側）

| 読者 | 用途 |
|---|---|
| `/automation-release` prepare（upstream） | `[Unreleased]` 配下に `### Migration` セクションがあるか warning レベルで検証 |
| `/automation --update` Phase 2（下流チャンネルリポジトリ） | `gh release view --json body` で Release 本文を取得、空なら CHANGELOG.md 該当バージョンセクションへ fallback。Top 3 / Fixed / Migration 全文を抽出 |
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

## fragment 運用（書き溜め方）

通常の PR は `CHANGELOG.md` を直接編集せず、`changelog.d/` に
`<issue番号>-<slug>.<type>.md` を追加する。type と本文書式は
[`changelog.d/README.md`](../changelog.d/README.md) を正とする。リリース prepare
の冒頭で `yt-changelog-compile` が fragment を契約順の見出しへ集約し、処理済み
fragment を削除する。

この変更は `[Unreleased]` への書き込み経路だけを分離する。コンパイル後の
`CHANGELOG.md`、リリース済み version section、GitHub Release body の形式は変わらない。
したがって prepare の Migration warning、下流 `/automation --update`、libecity digest
という既存 3 消費者のパース契約にも変更はない。

## `### Migration` セクション必須要素

下流の `/automation --update` が決定論的に抽出できるよう、以下を **必須要素** とする。

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

`/automation --update` が Top 3 を AI 抽出する際の参考情報として使う。

## Migration の import path 対応表

リリースで import 可能な Python module を移動し、旧 import path に互換 facade を設けない場合、`### Migration` に以下の対応表を置く。該当する移動を全件記載し、下流コードの置換元と置換先を一意にする。

```markdown
Python module 移動: あり
互換 facade: なし

| 旧 import path | 新 import path |
|---|---|
| `youtube_automation.cli.doctor` | `youtube_automation.commands.system.doctor` |
```

- 旧 / 新 path は、いずれも `youtube_automation.*` から始まる fully-qualified module path とする
- class・関数・変数名は表へ含めず、import 文で module として指定する path だけを書く
- 1 module の移動を 1 行とし、旧 path と新 path に同じ値を書かない
- 旧 path に互換 facade を残す移動はこの表の対象外とし、通常の Migration サマリで互換範囲を説明する

旧 module の削除に伴って API が再設計され、同じ責務を持つ新 module が存在しない場合は、参考にできる新 module を「新 import path」へ書かない。1 対 1 移動の対応表とは分けて、次の行フォーマットで削除と再設計を記録する。

```markdown
Python module 再設計: あり

| 削除された import path | 移行区分 | 参考 module（置換先ではない） |
|---|---|---|
| `youtube_automation.utils.legacy_client` | 1 対 1 代替なし（再設計） | `youtube_automation.infrastructure.google.client` |
```

- 削除された import path と参考 module は、いずれも `youtube_automation.*` から始まる fully-qualified module path とする
- 移行区分は `1 対 1 代替なし（再設計）` とし、class ベースから関数ベースへの変更など、呼び出し側の再設計が必要なことを Migration 本文で説明する
- 参考 module は置換先ではない。機能が近い class・関数を併記する場合も、自動置換できる API と誤認させず、利用者が責務を組み直すための参照として示す
- 互換 facade / shim がある削除や、単純な module 移動はこの行フォーマットへ混在させない

facade 無しの Python module 移動がないリリースでは、対応表を空のまま置かず、次の 1 行だけを記載する。この状態は「module を移動したが facade が無い」状態と区別される。

```markdown
Python module 移動: なし
```

## 推奨される追加要素（任意）

- バグ修正への issue / PR 参照（`(#NNN)` 形式）
- 影響範囲の言及（`tag pin の場合は ... / main 追従の場合は ...`）

## 違反検出

| 検出側 | 違反内容 | 反応 |
|---|---|---|
| `/automation-release` prepare 1-4 | `[Unreleased]` 配下に `### Migration` セクション無し | warning + `AskUserQuestion` で続行確認 |
| `/automation --update` Phase 2-3 | `所要時間の目安` / `local fix 衝突注意` の抽出失敗 | fallback で CHANGELOG / Release 本文全体を AI 累積要約 + Phase 3-3 で `[HUMAN STEP]` 確認 |

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
- 下流 `.claude/skills/automation/SKILL.md` — 各チャンネルリポジトリで CHANGELOG / Release 本文を読み取って追従するスキル
