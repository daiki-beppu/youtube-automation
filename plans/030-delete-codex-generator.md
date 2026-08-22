# Plan 030: 構築経路が封鎖済みの CodexGenerator を削除する

> **Executor instructions**: この plan を上から順に実行すること。各 step の
> Verify コマンドを実行し、期待結果を確認してから次へ進む。「STOP conditions」
> のいずれかが発生したら改善を試みず停止して報告する。完了したら
> `plans/README.md` の本 plan の Status 行を更新する。
>
> **Drift check (最初に実行)**: `git diff --stat 0030e636..HEAD -- src/youtube_automation/application/comments/ tests/application/comments/ tests/contracts/architecture/test_repository_reorganization_contract.py`
> in-scope ファイルに変更があれば「Current state」の excerpt と実物を突き合わせ、
> 不一致なら STOP。

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: 033 (soft — CHANGELOG は fragment 方式で書く。033 が未マージの場合のみ CHANGELOG.md 直接編集に fallback)
- **Category**: tech-debt
- **Planned at**: commit `0030e636`, 2026-08-22
- **Issue**: https://github.com/daiki-beppu/youtube-automation/issues/4462

## Why this matters

`CodexGenerator`（subprocess で `codex exec --json` を叩くコメント返信生成器、122 行）は、factory と replier の両方が provider='codex' を **ConfigError で拒否する**ため、プロダクションでは構築不可能。つまり「監査済みフロー（--export-candidates / --agent-replies-file）に一本化する」という設計判断が既に下りていて、この class は取り残された残骸である。放置すると、将来の貢献者が factory の分岐を「直して」**未監査の自動返信経路を再有効化する footgun** になる。テストごと削除し、封鎖が意図であることをコードに残す。

## Current state

- `src/youtube_automation/application/comments/codex_generator.py` — 削除対象。冒頭:
  ```python
  """Codex CLI によるコメント返信生成."""
  ...
  class CodexGenerator:
      """codex exec --json でコメント返信を生成する."""
  ```
  src 内 importer ゼロ（`git grep -ln "codex_generator" src/` → 自ファイルのみを確認済み）。
- `src/youtube_automation/application/comments/generator_factory.py:27` 付近 — codex 分岐は raise（**このガードは残す**）:
  ```python
  if config.provider == PROVIDER_CODEX:
      raise ConfigError(
          "comments.generator.provider='codex' は直接生成に使用できません。"
          "--export-candidates と --agent-replies-file の監査済みフローを使用してください"
  ```
- `src/youtube_automation/application/comments/replier.py:177` 付近 — 同趣旨の第 2 ガード（**残す**）。
- テスト側の参照:
  - `tests/application/comments/test_comments_generator.py:1` — docstring `"""GeminiGenerator / CodexGenerator の単体テスト."""`
  - 同 `:10` — `from youtube_automation.application.comments.codex_generator import CodexGenerator`
  - 同 `:250-` — `# ─── CodexGenerator ───` 区切り以下の `class TestCodexGenerator:` 一式（削除対象）
  - `tests/application/comments/test_comments_generator_factory.py:38` — `assert not hasattr(comments_api, "CodexGenerator")` は**不在を assert する**テストなので削除後も通る（触らない）。
  - `tests/application/comments/test_comments_replier.py` — `codex` provider の**拒否挙動**をテストしている可能性が高い。拒否テストはガードの検証なので残す。`CodexGenerator` 自体を import している行だけが削除対象。
- `tests/contracts/architecture/test_repository_reorganization_contract.py:117` — 移行 mapping:
  ```python
  "src/youtube_automation/utils/comments/codex_generator.py": "src/youtube_automation/application/comments/codex_generator.py",
  ```
  削除後は移行先が存在しなくなるため、この mapping 行の扱いをテストの仕組みに合わせて更新する（Step 3）。

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| comments テスト | `nix develop --command uv run pytest tests/application/comments/ -q` | all pass |
| 契約テスト | `nix develop --command uv run pytest tests/contracts/architecture/test_repository_reorganization_contract.py -q` | all pass |
| Ruff | `nix develop --command uv run ruff check src tests` | exit 0 |

## Scope

**In scope**:
- 削除: `src/youtube_automation/application/comments/codex_generator.py`
- 編集: `tests/application/comments/test_comments_generator.py`（TestCodexGenerator 一式と import・docstring）、`tests/application/comments/test_comments_replier.py`（CodexGenerator の import 行のみ、あれば）、`tests/contracts/architecture/test_repository_reorganization_contract.py`（mapping 1 行）、`src/youtube_automation/application/comments/generator_factory.py`（コメント 1 行追加のみ）、`CHANGELOG.md`

**Out of scope**:
- `generator_factory.py` / `replier.py` の **raise ガード本体** — これは意図された UX。削除・緩和しない。
- `PROVIDER_CODEX` 定数と、codex provider の**拒否**を検証するテスト — config 値としての 'codex' は引き続き受け付けて拒否メッセージを出す仕様なので残す。
- `prompt_safety.py` / `generator.py`（`ReplyContext`）— 現役の共有モジュール。

## Git workflow

- issue 専用 linked worktree 上で作業（`$REPO_ROOT/.claude/worktrees/<slug>/`）
- Branch: `advisor/030-delete-codex-generator`
- Commit: `refactor(comments): 構築経路封鎖済みの CodexGenerator を削除 (#<issue番号>)`（1 branch 1 commit）
- push / PR 作成はオペレーター指示があるまで行わない

## Steps

### Step 1: 本体を削除する

```bash
git rm src/youtube_automation/application/comments/codex_generator.py
```

**Verify**: `git grep -ln "codex_generator" src/` → 0 件

### Step 2: テストを整理する

- `tests/application/comments/test_comments_generator.py`: `class TestCodexGenerator:` 一式（`# ─── CodexGenerator ───` 区切り以下）と 10 行目の import を削除。1 行目の docstring を `"""GeminiGenerator の単体テスト."""` に修正。
- `tests/application/comments/test_comments_replier.py`: `CodexGenerator` / `codex_generator` を import している行があれば削除。**codex provider が ConfigError で拒否されることを検証するテストは残す**。

**Verify**: `nix develop --command uv run pytest tests/application/comments/ -q` → all pass

### Step 3: reorganization 契約の mapping を更新する

`tests/contracts/architecture/test_repository_reorganization_contract.py` を読み、mapping がどう検証されているか確認する（旧パス不在 + 新パス存在の assert が典型）。テスト内に「移行後にさらに削除されたモジュール」を表す仕組み（removed 系リスト等）があればそちらへ移し、無ければ 117 行の mapping エントリを削除して、削除の経緯をエントリ跡に 1 行コメントで残す。

**Verify**: `nix develop --command uv run pytest tests/contracts/architecture/test_repository_reorganization_contract.py -q` → all pass

### Step 4: 封鎖意図をコメントで固定する

`generator_factory.py` の codex 分岐 raise の直前に 1 行コメントを追加:

```python
# codex は監査済み export/replies フロー専用（直接生成の実装は #<この変更の issue/PR 番号> で削除済み）
```

**Verify**: `nix develop --command uv run ruff check src` → exit 0

### Step 5: CHANGELOG 追記と全体確認

エントリ文面:

```
- 構築経路が封鎖済みだった CodexGenerator（comments 直接生成の codex 実装）を削除。codex provider は従来どおり --export-candidates / --agent-replies-file へ誘導
```

**Plan 033（issue #4483）が main にマージ済みの場合**（`test -d changelog.d` で判定）: `CHANGELOG.md` は編集せず、`changelog.d/4462-delete-codex-generator.removed.md` を新規作成して上の bullet を書く。未マージの場合のみ `CHANGELOG.md` の `[Unreleased]` に追記する。

**Verify**: `nix develop --command uv run pytest tests/ -q` → all pass

## Test plan

新規テストは不要。既存の「codex provider は ConfigError で拒否される」テスト（`tests/application/comments/test_comments_replier.py` / factory テスト）が守るべき挙動の回帰テストとして機能し続ける。`test_comments_generator_factory.py:38` の `not hasattr` assert は削除後の状態と整合する。

## Done criteria

- [ ] `src/youtube_automation/application/comments/codex_generator.py` が存在しない
- [ ] `git grep -n "CodexGenerator" -- src tests` のヒットが「拒否テスト・不在 assert・コメント」以外に無い
- [ ] `nix develop --command uv run pytest tests/ -q` が exit 0
- [ ] `nix develop --command uv run ruff check src tests` が exit 0
- [ ] `CHANGELOG.md` の `[Unreleased]` に追記がある
- [ ] In scope 外の変更がない
- [ ] `plans/README.md` の Status 行を更新した

## STOP conditions

- `git grep -ln "codex_generator" src/` が自ファイル以外を返す（新しい消費者が生えた）。
- factory / replier の codex 分岐が raise 以外に変わっている（封鎖が解除されている — この plan の前提が崩れているので、削除ではなく再設計判断が必要）。
- Step 3 で reorganization 契約テストの構造が「mapping 1 行の削除」で済まない複雑さだった場合（例: 受け入れ済みの別 receipt との突き合わせがある）。

## Maintenance notes

- 将来 codex による直接生成を復活させたい場合は、git 履歴から class を戻すのではなく、**なぜ封鎖したか**（未監査自動返信の防止。監査フローは export→人手/エージェント確認→replies-file）を先に再評価すること。
- レビューでは「拒否ガードとその検証テストが残っていること」を必ず確認する。
