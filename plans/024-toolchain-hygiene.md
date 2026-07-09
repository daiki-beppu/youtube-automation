# Plan 024: ツールチェーン整備 — dev 依存の一本化・ruff B/RUF 導入・seaborn 削除・Any-gate の CI バックストップ・CJK フォント回帰テスト

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 5394c378..HEAD -- pyproject.toml .github/workflows/ci.yml flake.nix ONBOARDING.md README.md uv.lock`
> 差分が出たら「Current state」の抜粋と実コードを突き合わせ、不一致なら STOP。

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW（すべて挙動非依存のツールチェーン変更 + lint 指摘の機械的解消）
- **Depends on**: none。ただし **020〜023 と CHANGELOG.md / pyproject.toml が衝突しやすい**ので、連続実行時は最後に回して rebase すること
- **Category**: dx
- **Planned at**: commit `5394c378`, 2026-07-09

## Why this matters

4 つの独立した小さなほつれを一括で直す。(1) dev 依存が `[project.optional-dependencies].dev` と `[dependency-groups].dev` に**二重宣言されドリフト済み** — 素の `uv sync` では ruff が入らず、新規貢献者のローカル `ruff check` が動かない（CI は `--extra dev` で偶然救われている）。(2) ruff が `E,F,I,W` のみで、バグ検出系の `B`（bugbear）/`RUF` が無効 — メンテナンスモードのリポジトリでこそ、レビューだけが頼りの欠陥クラス（except 内 raise の from 欠落、mutable class default 等）を機械捕捉に載せる価値が高い。(3) `seaborn` は宣言だけで import ゼロの死んだ直接依存。(4) 「新規 Any 禁止」ゲートが client-side lefthook のみで、`origin/main` 不在時は self-skip する — CI バックストップが無く実質 advisory。加えて、2020 年から未更新の `japanize-matplotlib`（CJK フォントの単一障害点）に glyph 回帰テストを張り、壊れたら即検知できるようにする（移行そのものは別判断）。

## Current state

### (1) dev 依存の二重宣言 — `pyproject.toml:33-34` と `:155-158`

```toml
[project.optional-dependencies]
dev = ["pytest>=9,<10", "ruff>=0.15,<1"]
veo = []  # google-genai, Pillow moved to main dependencies

[dependency-groups]
dev = [
    "pytest>=9.0.2",
]
```

`uv sync` はデフォルトで `dependency-groups` の dev を入れる（→ ruff が入らない）。CI は `uv sync --extra dev` を使用。`--extra dev` の参照箇所（更新対象）: `.github/workflows/ci.yml:14`（lint job）/ `:27`（test job）/ `:40`（windows job）、`flake.nix`、`ONBOARDING.md`、`README.md`。`docs/migration/`・`docs/investigations/`・`docs/upgrades/` にも文字列があるが**歴史文書なので触らない**。

### (2) ruff ルール — `pyproject.toml:152-153`

```toml
[tool.ruff.lint]
select = ["E", "F", "I", "W"]
```

監査時の実測（`uv run ruff check --select B,RUF --statistics src tests`、2026-07-09）: 総数 6,362 件だが、うち **6,147 件は RUF001/RUF002/RUF003（ambiguous-unicode）** — 日本語 docstring/コメント/文字列への誤検知であり ignore が正しい。それを除く実バックログは約 215 件: RUF100×93（unused-noqa、ただし select 集合依存で実数は変わる）、RUF043×35（テストの `pytest.raises(match=...)` の正規表現メタ文字）、B904×22（`raise ... from` 欠落）、RUF013×15（implicit Optional）、RUF012×10（mutable class default）、RUF005×9、B905×7（zip strict 未指定）、B007×5、ほか少数。約半数は `--fix` で自動修正可能。

### (3) seaborn — `pyproject.toml:22`

```toml
    "seaborn>=0.13,<1",
```

`rg -n 'seaborn|sns\.' src tests` → 0 件（監査時確認済み。transitive に必要な pandas/matplotlib は独立に直接依存として宣言済み）。

### (4) Any-gate — `.lefthook/pre-push/any-usage-gate.sh:16-21`

```bash
  BASE_REF="origin/main"
  if ! git rev-parse --verify --quiet "${BASE_REF}^{commit}" >/dev/null; then
    echo "any-usage-gate: ${BASE_REF} が無いためスキップします（CI / review で確認してください）。" >&2
    exit 0
  fi
```

スクリプトは `PRE_PUSH_DIFF_BASE` 環境変数があればそれを diff 基準に使う（`:13-15`）。bash + python3 のみに依存（`:45-48` で python3 を検出、ubuntu-latest に標準装備）。CI（`.github/workflows/ci.yml`）には対応 job が無い。**注意**: lefthook.yml の pre-push は「changelog-gate.sh が唯一のエントリポイントで他ゲートへ連鎖する」構成をコメントで固定している — **lefthook.yml は触らない**。CI 側に独立 job を足すだけ。

### (5) japanize-matplotlib — 単一消費者 `src/youtube_automation/utils/launch_curve_plotter.py:11`

```python
import japanize_matplotlib  # noqa: E402, F401 — registers Japanese fonts
```

`uv.lock` 上 `japanize-matplotlib==1.1.3`（最終リリース 2020-10）。matplotlib は 3.10.8。壊れたときの症状は「日本語ラベルが豆腐化」だが、matplotlib は描画時に `Glyph NNNN (...) missing from font(s)` の `UserWarning` を出すため機械検知できる。

### 適用される規約

- `pyproject.toml` を触るため `CHANGELOG.md` `[Unreleased]` 追記必須
- CI は nix devShell 経由（`nix develop --command ...`）。ローカル検証も同じコマンドが使えるが、`uv run` 直でも可

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| 依存同期 | `uv sync` | exit 0、ruff がインストールされる（Step 1 後） |
| Lint 全量 | `uv run ruff check .` | exit 0（Step 2 完了後） |
| Format | `uv run ruff format --check .` | exit 0 |
| 全テスト | `uv run pytest -q` | all pass |
| lock 再生成 | `uv lock` | exit 0、uv.lock 更新 |
| any-gate 単体 | `PRE_PUSH_DIFF_BASE=$(git merge-base origin/main HEAD) bash .lefthook/pre-push/any-usage-gate.sh` | exit 0 |

## Scope

**In scope**:

- `pyproject.toml`
- `uv.lock`（`uv lock` / `uv sync` による再生成のみ。手編集禁止）
- `.github/workflows/ci.yml`
- `flake.nix` / `ONBOARDING.md` / `README.md`（`--extra dev` 記述の更新のみ）
- `src/**/*.py` / `tests/**/*.py`（**Step 2 の ruff 指摘解消に必要な機械的修正のみ**）
- `tests/test_japanize_font_regression.py`（新規）
- `CHANGELOG.md`

**Out of scope**:

- `lefthook.yml` — pre-push の 1 コマンド構成はコメントで意図固定されている。触らない
- `docs/migration/` / `docs/investigations/` / `docs/upgrades/` の `--extra dev` 記述 — 歴史文書
- japanize-matplotlib の**置換**（フォント直接登録への移行）— 本プランは回帰テストの設置まで。移行は壊れてから/matplotlib メジャー更新時に判断
- ruff `UP` / `SIM` の導入 — メンテナンスモードでは churn に見合わない（監査で棄却済み）
- `[project.optional-dependencies].veo`（空 extra）— 後方互換のため残す
- extensions/（TS 側）の lint — 別ツールチェーン

## Git workflow

- worktree 上で作業。base branch は main
- 論理単位でコミットを分ける（最低: Step 1+3 / Step 2 / Step 4 / Step 5 の 4 コミット推奨）。例: `chore(dev): dev 依存を dependency-groups へ一本化 (#<issue>)`
- push / PR 化はオペレーター指示時のみ

## Steps

### Step 1: dev 依存を `[dependency-groups]` へ一本化する

1. `pyproject.toml` の `[dependency-groups]` を `dev = ["pytest>=9,<10", "ruff>=0.15,<1"]` にする（pin は optional-dependencies 側の広い指定を採用）
2. `[project.optional-dependencies]` から `dev` 行を削除（`veo = []` は残す）
3. `uv lock` を実行
4. `--extra dev` 参照を更新: `.github/workflows/ci.yml` の 3 箇所を `uv sync` に、`flake.nix` / `ONBOARDING.md` / `README.md` 内の該当記述を同様に（`rg -n 'extra dev' .github flake.nix ONBOARDING.md README.md` で漏れなく拾う）

**Verify**: `uv sync && uv run ruff --version && uv run pytest -q` → すべて exit 0 / `rg -n 'extra dev' .github flake.nix ONBOARDING.md README.md` → 0 件

### Step 2: ruff に B / RUF を導入し、バックログを解消する

1. `pyproject.toml` を:

```toml
[tool.ruff.lint]
select = ["E", "F", "I", "W", "B", "RUF"]
# RUF001/002/003: 日本語コードベースのため全角文字の ambiguous-unicode 検知は誤検知のみ
ignore = ["RUF001", "RUF002", "RUF003"]

[tool.ruff.lint.per-file-ignores]
# pytest.raises(match=...) の正規表現メタ文字警告はテスト可読性を優先して抑制
"tests/**" = ["RUF043"]
```

2. `uv run ruff check . --fix` で自動修正可能分を消化（安全 fix のみ。`--unsafe-fixes` は使わない）
3. 残りを手動解消。ルール別の方針:
   - **B904**（~22 件）: except 節内の raise に `from e`（原因連鎖が有用な場合）または `from None`（意図的に隠す場合）を付ける。迷ったら `from e`
   - **RUF013**: 暗黙 Optional 引数に `| None` を明記（挙動変更なし）
   - **RUF012**: クラス変数の mutable default に `typing.ClassVar[...]` 注釈を付ける（**Any は使わない** — any-gate に引っかかる）
   - **B905**: `zip(..., strict=False)` を明示（zip のデフォルトと同じ = 挙動保存）。両 iterable が同一長であることがコード上自明な場合のみ `strict=True`
   - **B007**: 未使用ループ変数を `_` に
   - **RUF100**: select 集合が変わったので実数は再計測される。残った unused-noqa は削除
   - その他の単発（B017, RUF005, RUF010, RUF015, RUF017, RUF019, RUF022, RUF023, RUF046, RUF059）: メッセージの指示どおり機械的に。**修正がコードの意味を変えると思ったら該当行のみ `# noqa: <rule>` + 1 語の理由コメントで逃がしてよい**（10 件を超えて noqa 逃げが必要なら STOP）
4. `uv run ruff format .` で format 差分がないことを確認（fix が format を崩した場合のみ再 format）

**Verify**: `uv run ruff check .` → exit 0 / `uv run pytest -q` → all pass（lint fix による挙動変化がないことの確認）

### Step 3: seaborn を削除する

`pyproject.toml:22` の seaborn 行を削除し `uv lock`。事前に `rg -n 'seaborn' src tests --glob '!__pycache__'` が 0 件であることを再確認。

**Verify**: `uv sync && uv run pytest -q` → all pass / `rg -n '"seaborn' pyproject.toml` → 0 件

### Step 4: Any-gate の CI バックストップ job を追加する

`.github/workflows/ci.yml` に job を追加（PR のみ。push 時は base が定義できないため対象外とする）:

```yaml
  any-gate:
    runs-on: ubuntu-latest
    if: github.event_name == 'pull_request'
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Check new Any usage
        env:
          PRE_PUSH_DIFF_BASE: ${{ github.event.pull_request.base.sha }}
        run: bash .lefthook/pre-push/any-usage-gate.sh
```

既存の `changelog` job（`:44-`）と同じ構造（`fetch-depth: 0` + base sha を env で渡す）を踏襲している。

**Verify**: ローカルで `PRE_PUSH_DIFF_BASE=$(git merge-base origin/main HEAD) bash .lefthook/pre-push/any-usage-gate.sh` → exit 0（自分の作業ブランチに新規 Any が無いこと。Step 2 の RUF012 対応で `Any` を書いていたらここで捕まる — ClassVar の具体型に直すこと）

### Step 5: CJK フォント glyph 回帰テストを追加する

`tests/test_japanize_font_regression.py` を新規作成:

```python
"""japanize-matplotlib（2020 年から未更新）の font 登録が壊れたら検知する回帰テスト。

壊れた場合の症状は日本語ラベルの豆腐化で、matplotlib は描画時に
"Glyph NNNN ... missing from font(s)" の UserWarning を出す。それを検知する。
"""

import warnings

import matplotlib

matplotlib.use("Agg")


def test_japanese_glyphs_render_without_missing_font_warnings():
    import japanize_matplotlib  # noqa: F401 — フォント登録の副作用が本テストの対象
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    ax.set_title("日本語ラベル描画テスト（再生回数・視聴維持率）")
    ax.plot([0, 1], [0, 1], label="テスト系列")
    ax.legend()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fig.canvas.draw()
    plt.close(fig)

    missing = [w for w in caught if "missing from font" in str(w.message)]
    assert not missing, f"日本語 glyph が描画できていない: {[str(w.message) for w in missing]}"
```

**Verify**: `uv run pytest tests/test_japanize_font_regression.py -q` → 1 passed

### Step 6: CHANGELOG 追記 + 全体検証

`CHANGELOG.md` `[Unreleased]` に Changed（dev 依存一本化 / ruff B・RUF 導入）と Removed（seaborn）を追記。

**Verify**: `uv run pytest -q` → all pass / `uv run ruff check . && uv run ruff format --check .` → exit 0

## Test plan

- 新規: `tests/test_japanize_font_regression.py`（Step 5、1 ケース）
- 既存スイート全 green が Step 2 の「lint fix は挙動を変えていない」ことの検証
- CI job（Step 4）は PR を開いたときに初めて実走する — ローカルでは Step 4 の Verify コマンドが等価検証

## Done criteria

- [ ] `rg -n 'optional-dependencies' pyproject.toml` の dev 行が消え、`[dependency-groups].dev` に pytest + ruff がある
- [ ] `uv run ruff check .` exit 0（select に B, RUF を含む状態で）
- [ ] `rg -n 'seaborn' pyproject.toml uv.lock` → pyproject 0 件（uv.lock は transitive で残らないこと — 残ったら何かが依存している。STOP 条件参照）
- [ ] `.github/workflows/ci.yml` に `any-gate` job が存在し、`rg -n 'extra dev' .github` → 0 件
- [ ] `uv run pytest -q` exit 0（glyph 回帰テスト含む）
- [ ] `CHANGELOG.md` `[Unreleased]` に追記
- [ ] `git status` で in-scope 外の変更なし
- [ ] `plans/README.md` の 024 行を更新

## STOP conditions

- Drift check 不一致（特に pyproject.toml の依存節が既に変わっている場合）
- Step 2 で `# noqa` 逃げが 10 件を超える（ルール選定の再検討が要る — 報告して指示を待つ）
- Step 2 の fix 後に pytest が fail し、原因が lint fix にある（当該 fix を revert して noqa + 報告）
- Step 3 で `uv lock` 後も uv.lock に seaborn が残る（何かが transitive に要求している — 削除中止して報告）
- Step 5 のテストが**現状のコードで**すでに fail する（japanize-matplotlib が既に壊れている — それ自体が重要 finding なので即報告。テスト追加は保留）

## Maintenance notes

- ruff / pytest のバージョン更新時、`[dependency-groups].dev` だけを見ればよくなった（二重管理の終了）
- matplotlib をメジャー更新（4.x）する際は japanize-matplotlib 互換が最大の懸念 — Step 5 のテストが早期警報になる。fail したら `matplotlib.font_manager.fontManager.addfont()` による直接登録への移行（監査 finding DEPS-02 の fix sketch）を実施
- レビューで見るべき点: Step 2 の diff に「機械的でない」変更（ロジック変更・リネーム）が紛れていないこと
- 明示的に先送り: japanize-matplotlib の置換移行、ruff `UP`/`SIM`、mypy/pyright 導入（監査で「導入しない」判断 — plans/README 参照）
