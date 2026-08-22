# Plan 029: 到達不能な video_validator クラスタと B3 facade 2 本を削除する

> **Executor instructions**: この plan を上から順に実行すること。各 step の
> Verify コマンドを実行し、期待結果を確認してから次へ進む。「STOP conditions」
> のいずれかが発生したら改善を試みず停止して報告する。完了したら
> `plans/README.md` の本 plan の Status 行を更新する。
>
> **Drift check (最初に実行)**: `git diff --stat 0030e636..HEAD -- src/youtube_automation/commands/analytics/video_validator.py src/youtube_automation/domains/media/video_validator.py src/youtube_automation/domains/media/video.py src/youtube_automation/domains/media/audio.py tests/commands/analytics/test_video_validator.py tests/repo/test_cli_harness_gate.py tests/test_b3_domain_migration_contract.py`
> in-scope ファイルに変更があれば「Current state」の excerpt と実物を突き合わせ、
> 不一致なら STOP。

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW–MED（downstream import の可能性のみ。in-repo 到達経路はゼロ）
- **Depends on**: 033 (soft — CHANGELOG は fragment 方式で書く。033 が未マージの場合のみ CHANGELOG.md 直接編集に fallback)
- **Category**: tech-debt
- **Planned at**: commit `0030e636`, 2026-08-22
- **Issue**: https://github.com/daiki-beppu/youtube-automation/issues/4461

## Why this matters

`video_validator` クラスタ（CLI 1 本 + domain 実装 + facade、計 446 行）は、`pyproject.toml` のどの `yt-*` entry point からも、skill・doc・workflow のどこからも呼べない。唯一の消費者は自分専用のテスト 278 行で、CI で毎回実行・カバレッジ計上・リファクタ追従コストを払い続けている。同型の B3 期 facade `domains/media/audio.py`（6 行）も、消費者は migration 契約テストの列挙のみ。「テストだけが延命させている dead code」を削除し、契約テストの凍結リストからも外す。

## Current state

削除対象 4 + テスト 1:

- `src/youtube_automation/commands/analytics/video_validator.py` — `main()` と `if __name__ == "__main__"` を持つ CLI だが、`pyproject.toml [project.scripts]` に対応する `yt-*` が無く、`src/youtube_automation/entrypoints.py` の文字列 dispatch にも現れない（`git grep -n "video_validator" src/youtube_automation/entrypoints.py` → 0 件を確認済み）。冒頭:
  ```python
  """ffprobe adapter and command entry point for video validation."""
  ...
  from youtube_automation.domains.media.video_validator import VideoValidator
  ```
- `src/youtube_automation/domains/media/video_validator.py` — `VideoValidator`（377 行）。importer は上の dead CLI と `domains/media/video.py` の 2 つだけ。
- `src/youtube_automation/domains/media/video.py` — 6 行の facade。全文:
  ```python
  """Video domain public surface."""

  from youtube_automation.domains.media.video_type import VideoType, VideoTypeConfig
  from youtube_automation.domains.media.video_validator import VideoValidator

  __all__ = ["VideoType", "VideoTypeConfig", "VideoValidator"]
  ```
  src 内 importer ゼロ。参照は `tests/test_b3_domain_migration_contract.py` の列挙のみ。
- `src/youtube_automation/domains/media/audio.py` — 6 行の facade。全文:
  ```python
  """Provider-neutral audio formats and billing units."""

  from youtube_automation.domains.media.audio_formats import AUDIO_EXTS
  from youtube_automation.domains.media.audio_units import unit_for_audio

  __all__ = ["AUDIO_EXTS", "unit_for_audio"]
  ```
  同じく参照は `tests/test_b3_domain_migration_contract.py` のみ。re-export 元の `audio_formats.py` / `audio_units.py` は現役（**触らない**）。
- `tests/commands/analytics/test_video_validator.py` — 278 行。唯一の behavioral consumer。丸ごと削除。

編集が必要な契約テスト 2:

- `tests/repo/test_cli_harness_gate.py:26` — `LEGACY_CLI_ALLOWLIST` に `"youtube_automation.commands.analytics.video_validator",` の行がある。この 1 行を削除。
- `tests/test_b3_domain_migration_contract.py:54,57` — 凍結モジュールリストに `"youtube_automation.domains.media.audio",` と `"youtube_automation.domains.media.video",` がある。この 2 行を削除。

注意（誤読しやすい点）:
- `src/youtube_automation/domains/media/audio_formats.py:4` の docstring に「`video_validator`（個別動画と音声ファイル数の整合性チェック）」という**言及**があるが、import ではない。docstring のこの言及行は削除後に整合するよう文言を調整してよい（それ以外は触らない）。
- `domains/media/video_type.py`（`VideoType`）は多数の現役 importer を持つ。**削除しない**。

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| 対象テスト | `nix develop --command uv run pytest tests/repo/test_cli_harness_gate.py tests/test_b3_domain_migration_contract.py tests/domains/media/ -q` | all pass |
| import 健全性 | `nix develop --command uv run python -c "import youtube_automation.domains.media.video_type"` | exit 0 |
| Ruff | `nix develop --command uv run ruff check src tests` | exit 0 |
| 全体（時間があれば） | `nix develop --command uv run pytest -q` | all pass |

## Scope

**In scope**:
- 削除: `src/youtube_automation/commands/analytics/video_validator.py`, `src/youtube_automation/domains/media/video_validator.py`, `src/youtube_automation/domains/media/video.py`, `src/youtube_automation/domains/media/audio.py`, `tests/commands/analytics/test_video_validator.py`
- 編集: `tests/repo/test_cli_harness_gate.py`（1 行削除）, `tests/test_b3_domain_migration_contract.py`（2 行削除）, `src/youtube_automation/domains/media/audio_formats.py`（docstring の言及調整のみ・任意）, `CHANGELOG.md`

**Out of scope**:
- `src/youtube_automation/domains/media/video_type.py`, `audio_formats.py` の実装, `audio_units.py` — 現役。
- `src/youtube_automation/domains/uploads/descriptions_md.py` — 同類の疑いだが別判断（第 6 回監査で未選択。この plan で触らない）。
- `pyproject.toml` — video_validator の entry point はもともと存在しないので変更不要。

## Git workflow

- issue 専用 linked worktree 上で作業（`$REPO_ROOT/.claude/worktrees/<slug>/`）
- Branch: `advisor/029-delete-video-validator-cluster`
- Commit: `refactor(analytics): 到達不能な video_validator クラスタと B3 facade を削除 (#<issue番号>)`（1 branch 1 commit）
- push / PR 作成はオペレーター指示があるまで行わない

## Steps

### Step 1: 削除前の到達不能性を再確認する

**Verify**:
- `git grep -ln "video_validator" -- src tests pyproject.toml` → ヒットは Current state に列挙した 5 ファイル（+ `audio_formats.py` の docstring）のみ
- `git grep -ln "domains.media.video\b" -- src` と `git grep -ln "domains.media.audio\b" -- src` → いずれも 0 件（tests のみ）

### Step 2: 5 ファイルを削除する

```bash
git rm src/youtube_automation/commands/analytics/video_validator.py \
       src/youtube_automation/domains/media/video_validator.py \
       src/youtube_automation/domains/media/video.py \
       src/youtube_automation/domains/media/audio.py \
       tests/commands/analytics/test_video_validator.py
```

**Verify**: `git status --short` → 上記 5 件の `D` のみ

### Step 3: 契約テストの列挙から外す

- `tests/repo/test_cli_harness_gate.py` から `"youtube_automation.commands.analytics.video_validator",` の 1 行を削除
- `tests/test_b3_domain_migration_contract.py` から `"youtube_automation.domains.media.audio",` と `"youtube_automation.domains.media.video",` の 2 行を削除

**Verify**: `nix develop --command uv run pytest tests/repo/test_cli_harness_gate.py tests/test_b3_domain_migration_contract.py -q` → all pass

### Step 4: 残存参照を掃く

`git grep -n "video_validator\|VideoValidator" -- src tests docs .claude` を実行。ヒットが `audio_formats.py` の docstring だけなら、その言及を現状に合う文言へ修正（または該当句を削除）する。

**Verify**: 上記 grep の残ヒットが 0 件（docstring 修正後）

### Step 5: CHANGELOG 追記とテスト

エントリ文面:

```
- 到達不能だった video_validator（CLI + domain 実装 + facade）と B3 facade domains/media/{video,audio}.py を削除
```

**Plan 033（issue #4483）が main にマージ済みの場合**（`test -d changelog.d` で判定）: `CHANGELOG.md` は編集せず、`changelog.d/4461-delete-video-validator.removed.md` を新規作成して上の bullet を書く。未マージの場合のみ `CHANGELOG.md` の `[Unreleased]` に追記する。

**Verify**:
- `nix develop --command uv run pytest tests/ -q -x --ignore=tests/repo` → all pass（時間短縮のため。可能なら ignore なしの全体を実行）
- `nix develop --command uv run pytest tests/repo -q` → all pass
- `nix develop --command uv run ruff check src tests` → exit 0

## Test plan

新規テストは不要（削除のみ）。回帰確認は Step 3 / Step 5 の契約テスト＋全体スイート。削除により `tests/contracts/architecture/test_repository_reorganization_contract.py` が fail した場合は、そのファイル内で `video_validator` を指す mapping 行を確認して同様に削除する（Step 3 と同じ性質の列挙更新。ただし `utils/comments/codex_generator.py` など**他モジュールの mapping は触らない**）。

## Done criteria

- [ ] 5 ファイルが存在しない
- [ ] `git grep -n "VideoValidator" -- src tests` が 0 件
- [ ] `nix develop --command uv run pytest -q` が exit 0（全体）
- [ ] `nix develop --command uv run ruff check src tests` が exit 0
- [ ] `CHANGELOG.md` の `[Unreleased]` に追記がある
- [ ] In scope 外の変更がない（`git status`）
- [ ] `plans/README.md` の Status 行を更新した

## STOP conditions

- Step 1 の grep で Current state に無い importer が見つかった（この plan 作成後に新しい消費者が生えた）。
- `test_b3_domain_migration_contract.py` の列挙削除で、リスト以外のロジック（例: 「削除済みモジュールは import 不可であること」を別途 assert する節）に矛盾が出た場合 — その契約の意図判断が必要なので報告する。
- 全体テストで、この plan が触っていない領域の fail が 2 回連続で再現した。

## Maintenance notes

- `VideoValidator` は「動画と音声ファイル数の整合性チェック」の実装だった。将来同機能が必要になったら git 履歴（この commit の親）から復元し、その際は必ず `yt-*` entry point として登録して skill から呼ぶこと（到達経路のない CLI を作らない）。
- downstream チャンネルリポジトリが `domains.media.video_validator` を直接 import している可能性は理論上あるが、downstream 向け import 契約リスト（`tests/repo/test_skills_sync_installed_wheel.py` の `legacy_modules`）に含まれていないため保証対象外。リリースノートに削除を明記すれば十分。
