## 変更スコープ宣言

実装に入る前に、**先に書かれたテストコード**から要件 ID を拾い（`rg 'REQ-\d+-\d+' -n`）、そのうち **この step で実装するもの** を宣言してください。宣言にない変更は行いません。

**`plan.md` をファイルとして探さないでください。** この step は callable sub-workflow の中で動くため、親の Report Directory は見えません。要件の担体はテストコードです — `write_tests` が全要件について「要件 ID とケース ID を埋め込んだテスト」を red の状態で残しているので、それが実装すべき仕様の全量になります（docs/takt-operations.md）。

## 手順

1. 先に書かれたテスト（red）を確認する。テストが要求している振る舞いが実装の仕様である
2. テストを green にする最小の実装を行う。テストが要求していない振る舞いを足さない。実装の途中で「テストが要求している仕様そのものが誤っている」と判断したら、**実装を続けずに報告する**
3. テストを実行して green にする。反復の途中はこれだけを回してよい（対象テストファイルに絞ってよい）:
   ```
   nix develop --command uv run pytest
   ```
4. 完了前に、CI と同一の検査ゲート（CI 同等ゲート）を通す:
   ```
   nix develop --command uv run ruff check .
   nix develop --command uv run ruff format --check .
   bash .github/scripts/any-usage-gate.sh
   nix develop --command uv run pytest
   ```
   加えて、実コード（`src/youtube_automation/` / `.claude/skills/` / `.claude/CLAUDE.template.md` / `pyproject.toml`）を変更したなら `CHANGELOG.md` の `[Unreleased]` を更新し、skill を変更したなら `uv run yt-skills lint` を通す。落ちたゲートを直したら、**個別ゲートではなく CI 同等ゲート全体を通し直す**（1 つ直して別のゲートを割っていないことの確認）

## 本リポジトリの開発規約（CLAUDE.md）

以下は絶対の制約です。守れない事情があるなら、実装せずに報告してください。

- **テストは `tests/test_<対象>.py` の pytest。** 対象と無関係なファイルへ分散させない
- **チャンネル固有値は `load_config` 経由。** ハードコーディング禁止（`config/channel/*.json` に集約）。Path のみ必要なら `channel_dir()`
- **エラーはドメイン例外**（`infrastructure/errors.py` の `ConfigError` / `YouTubeAPIError` 等）。生の `Exception` / `KeyError` を catch しない
- **パッケージ内 import は fully-qualified**（`from youtube_automation.xxx import ...`）
- **新規 CLI は `yt-*` prefix** を踏襲し、`pyproject.toml` の `[project.scripts]` に entry point を登録する
- **SKILL.md frontmatter の `description:` は double-quoted string** で書く
- **メンテナンスモード**（ADR-0021）: TypeScript は dashboard/（ADR-0013）+ extensions/ 限定。他の TS 実装・tayk core・削除済み `packages/` の復活は禁止
- 実コードを変更したら `CHANGELOG.md` の `[Unreleased]` を更新する

## 禁止

- テストを通すためにテストを書き換えること（期待値の緩和・skip・削除）
- 実装計画の要件 ID にない機能を足すこと（良かれと思った追加も対象）
- 規約文書から黙って逸脱すること。逸脱が必要なら、**該当規約文書の改訂を同じ差分に含める**
- `pip install` / `npm install` 等、**uv 以外での依存操作**（依存追加は `uv add`、同期は `uv sync`）
- CI 同等ゲートを通さずに完了とすること
- main への直接コミット

## 判定

- 宣言した要件 ID を実装し、テストが green になった → 次へ
- 実装計画の方針では実現できないことが判明した → 差し戻す
