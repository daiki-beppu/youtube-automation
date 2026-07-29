# ツールチェーンポリシー

本リポジトリの Python toolchain は **uv / Nix devShell 固定**。依存操作は uv を直接呼び、コマンド実行は devShell を経由する（非対話 shell / agent の正規入口は `nix develop --command <command>`。`docs/development.md`「開発者 bootstrap」）。

グローバル環境の python / pip や、パッケージマネージャを自動検出して委譲する類のラッパコマンドは使わない。ラッパは devShell の外（グローバル環境）に依存するため、参照するほど環境再現性が下がる。toolchain が 1 つに固定されたリポで AI agent が叩く前提では、ラッパの受益者もいない。

## コマンド

| 用途                   | コマンド                                     |
| ---------------------- | -------------------------------------------- |
| 依存の同期             | `nix develop --command uv sync`              |
| 依存の追加             | `uv add <pkg>` / `uv add --dev <pkg>`        |
| テスト                 | `nix develop --command uv run pytest`        |
| lint                   | `nix develop --command uv run ruff check .`  |
| format 検査            | `nix develop --command uv run ruff format --check .` |
| skill frontmatter 検証 | `uv run yt-skills lint [<skill>...]`         |

## 検査ゲート（CI 同等ゲート）

このリポジトリは**ローカル git hook を持たない**。品質ゲートは CI（`.github/workflows/ci.yml`）が正であり、「ローカルで CI を再現する」とは次のコマンド列を指す。

```
nix develop --command uv run ruff check .
nix develop --command uv run ruff format --check .
bash .github/scripts/any-usage-gate.sh   # origin/main からの新規追加行の Any/any 型検出
nix develop --command uv run pytest
```

加えて、変更内容に応じて次を守る。

- 実コード（`src/youtube_automation/` / `.claude/skills/` / `.claude/CLAUDE.template.md` / `pyproject.toml`）を変更したら、`CHANGELOG.md` の `[Unreleased]` を更新する（意図的に省く場合は PR に `skip-changelog` ラベルを付与する）
- skill を変更したら `uv run yt-skills lint` を通す
- `.takt/workflows/` または `.takt/facets/` を変更したら `takt workflow doctor` を通す（takt は CI 環境に無いためローカルのみ。`docs/takt-operations.md`）

個々のゲートを名指しで実行してよいのは、失敗を絞り込む反復の途中だけである（例: 実装中に `nix develop --command uv run pytest tests/test_xxx.py` を繰り返す）。**push 前・報告前には必ず CI 同等ゲートの全コマンドを通すこと。** 1 つのゲートを直して別のゲートを割る修正を、push してから CI に見つけさせない。

**例外は、実装前に red を観測する step（`write_tests` / `reproduce`）である。** あそこでの pytest の失敗はゲートの再現ではなく、テストが要件・症状を検証していることの証拠（要件トレーサビリティポリシー / `docs/takt-operations.md`）を得る手順そのものだ。実装がまだ無い時点で全ゲートが通ることは設計上ありえないため、**red を「壊れている」と読み替えて直しにいってはならない**。ゲートを通す責任は、実装を持つ後段の step（`implement` / `repair`）にある。

## 禁止

- uv 以外での依存操作（`pip install` 直叩き、グローバル環境への install、`poetry` / `conda` 等）
- テストの削除・skip・アサーション緩和によってゲートを通すこと
- CI 定義（`.github/workflows/ci.yml` / `.github/scripts/`）の弱体化によってゲートを通すこと
