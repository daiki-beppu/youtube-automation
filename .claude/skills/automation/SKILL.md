---
name: automation
purpose: 準備する
description: "Use when 下流リポジトリで automation を最新リリースへ追従させるとき、またはツールキットの仕様・skill・CLIについて質問するとき。排他的な --update で追従 wizard、--question <質問> または排他フラグなしの自然文で読み取り専用の質問 mode を実行する。「追従」「アップグレード」「automation-update」「automationについて質問」で発動"
---

## 前後工程

- `前工程`: `/automation-release`
- `後工程`: `なし`
- `委譲先`: `なし`

## 成果物

- `書き込む`: `pyproject.toml`, `uv.lock`, `.claude/skills/*`, `.claude/CLAUDE.md`
- `読み込む`: `CHANGELOG.md`, `pyproject.toml`, `config/channel/*.json`, `config/skills/*`, `docs/features.md`, `docs/workflow-cheatsheet.md`, `.claude/skills/*/SKILL.md`, `.claude/CLAUDE.md`

## モード判定

`$ARGUMENTS` から排他フラグ `--update` / `--question` の個数を最初に数える。

- 2 個以上なら排他違反として停止し、mode は 1 つだけ指定するよう促す
- `--update` が 1 個なら `references/update.md` を読み、残りの引数を update mode の引数として扱う
- `--question` が 1 個なら、後続に空白以外の質問がある場合だけ `references/question.md` を読む。質問が空なら停止する
- 排他フラグなしで `$ARGUMENTS` に空白以外の自然文があれば、全体を質問として question mode で扱い `references/question.md` を読む
- 排他フラグなしで `$ARGUMENTS` が空または空白だけならモード未指定として停止し、`--update` / `--question <質問>` を促す。処理は開始しない

| mode | 読む reference |
|---|---|
| `--update` | `references/update.md` |
| `--question` | `references/question.md` |

## 共通契約

update mode の機械的な追従処理の公開 CLI は既存の `yt-automation-update` である。CLI 名と Python module 名は変更しない。question mode は読み取り専用で、回答生成用 CLI を新設しない。

実行場所は `youtube-channels-automation` を依存に持つ下流チャンネルリポジトリに限る。upstream 本体や依存参照のないリポジトリでは停止し、`references/update.md` の実行場所判定に従って移動先候補を案内する。

## AI が絶対に勝手にやらないこと

次の操作は `references/update.md` の `[HUMAN STEP]` で明示同意を得るまで実行しない。

- local fix を破棄する `yt-automation-update apply --force-sync`
- 旧 skill を削除する `--prune`
- sha pin の bump 先決定
- 既存の手書き skill の上書き
- `git push`（AI は commit までで停止する）

## 想定 API call 数

| API | call 数 / 実行 | 変動要因 |
|---|---|---|
| YouTube Data + Analytics API（smoke の `yt-channel-status` 1 回分） | 約 3 + P units（P = playlist 数）+ Analytics reports.query 1 call | チャンネルの playlist 数 |
| YouTube Reporting API（`yt-doctor` 診断、無料枠） | 数 call（quota 課金なし） | — |
| GitHub API（question mode の fallback） | ローカルで未解決の場合だけ数 call | 読む docs / CHANGELOG / open issue の数 |

- 上限 / 承認: smoke 検証はいずれも読み取り専用で、YouTube への書き込み API は呼ばない。破壊的操作（`--force-sync` / push 等）はすべて `[HUMAN STEP]` で人間判断を取る。

## 完了条件

- update mode: `references/update.md` の Phase 1〜4を順に実行し、追従後の機械チェックとコミットが完了している。push は実行せず、利用者へ案内する
- question mode: `references/question.md` の優先順位で根拠と version を示して回答し、ファイル・git・upstream を変更していない。未解決なら `/skill-feedback` を案内して終了する
