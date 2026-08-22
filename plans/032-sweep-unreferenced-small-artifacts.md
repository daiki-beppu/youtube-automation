# Plan 032: 参照ゼロの小粒残骸を一括掃除する（shim / fixture / bench / 設定ファイル）

> **Executor instructions**: この plan を上から順に実行すること。各 step は互いに
> 独立しており、1 つが STOP になっても他は続行してよい（最後に STOP 分を報告）。
> 各 step の Verify コマンドを実行し、期待結果を確認してから次へ進む。完了したら
> `plans/README.md` の本 plan の Status 行を更新する。
>
> **Drift check (最初に実行)**: `git diff --stat 0030e636..HEAD -- src/youtube_automation/infrastructure/legacy_utils/image_provider tests/fixtures bench/bench_real_apis.py extensions/suno-helper/.prettierignore extensions/distrokid-helper/.prettierignore extensions/.fallow-dupes-baseline.json .gitignore`
> in-scope ファイルに変更があれば「Current state」の excerpt と実物を突き合わせ、
> 不一致の step は STOP（他の step は続行可）。

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: 033 (soft — CHANGELOG は fragment 方式で書く。033 が未マージの場合のみ CHANGELOG.md 直接編集に fallback)。Plan 028-031 と競合ファイルなし・並列実行可
- **Category**: tech-debt
- **Planned at**: commit `0030e636`, 2026-08-22
- **Issue**: https://github.com/daiki-beppu/youtube-automation/issues/4464

## Why this matters

第 6 回監査（未参照ファイル特化）で見つかった、**参照ゼロが機械的に証明できる小粒の残骸** 6 群をまとめて始末する。個々は小さいが、(a) CPython の import 機構上決して実行されない 5 本の shim、(b) 廃止済み設定スキーマを「正」に見せる fixture、(c) 実行経路のない bench オーケストレータ、(d) 存在しないツール（prettier）の設定 2 本、(e) 削除済みファイルを指し続ける重複検知 baseline、(f) commit された runtime lock ファイル — はいずれも「読んだ人を誤誘導する」タイプの残骸で、放置コストが削除コストを上回る。

## Current state

### A. `legacy_utils/image_provider` の兄弟 shim 5 本（src — CHANGELOG 必要）

- `src/youtube_automation/infrastructure/legacy_utils/image_provider/__init__.py` は canonical（`infrastructure.media.image_provider`）を import し、**末尾で 5 つのサブモジュール名を `sys.modules` に直接エイリアス登録する**:
  ```python
  sys.modules[f"{__name__}.composition"] = composition
  sys.modules[f"{__name__}.config"] = config
  sys.modules[f"{__name__}.gemini"] = gemini
  sys.modules[f"{__name__}.openai"] = openai
  sys.modules[f"{__name__}.prompt_schema"] = prompt_schema
  ```
  （この `__init__.py` は**残す**。）
- 同ディレクトリの `composition.py` / `config.py` / `gemini.py` / `openai.py` / `prompt_schema.py` は各自 `sys.modules[__name__] = _canonical` を行う独立 shim だが、CPython はサブモジュール import 時に**親パッケージを先に import し、`sys.modules` に名前があればそれを返す**ため、親 `__init__` が上のエイリアスを張った時点でこの 5 ファイルは決して読まれない。削除対象。
- downstream 互換契約は `tests/repo/test_skills_sync_installed_wheel.py:260-266` の `legacy_modules` タプルで、`"youtube_automation.utils.image_provider"`（**パッケージ**）だけを import する。兄弟ファイルのパスを参照するテストは無い（`git grep -n "legacy_utils/image_provider" tests/ src/` → shim 自身以外 0 件を確認済み）。
- 注意: `tests/contracts/architecture/test_repository_reorganization_contract.py:132-133` の mapping は旧 `utils/image_provider/*` → **canonical の `infrastructure/media/image_provider/*`** を指しており、legacy shim は指していない。この削除で fail しないはず（fail したら STOP）。

### B. 廃止スキーマの fixture ディレクトリ（tests のみ）

- `tests/fixtures/skill_config_verify/` の 5 ファイル（`config/channel_config.json`, `config/skills/{benchmark,description,loop-video,masterup}.yaml`）。リポジトリ全体で `skill_config_verify` への参照は CHANGELOG の履歴記述 1 件のみ（`git grep -ln "skill_config_verify"` → `CHANGELOG.md` のみを確認済み）。encode している単一ファイル `channel_config.json` 形式は、現行の `config/channel/*.json` 分割形式（`examples/channel_config.example/` 参照）で置換済み。

### C. commit された runtime lock ファイル（tests のみ）

- `tests/fixtures/sample_channel/data/quota_costs.json.lock` — 1 byte。`infrastructure/file_lock.py` が実行時に作る類のファイルで、参照ゼロ。untrack して ignore する。

### D. bench の孤児オーケストレータ（bench のみ）

- `bench/bench_real_apis.py` — docstring は「通常は `bench/main.py` が呼び出す」と主張するが、`bench/main.py` は自前の `REAL_API_BENCHES` リストを持ち import しない。`bench/README.md` の同梱ベンチ表にも無い。唯一の言及は `bench/bench_strategic_analytics.py:7` の docstring（「bench_real_apis には含めず」— 削除後も文意が通るので修正不要）。

### E. prettier 不在の `.prettierignore` 2 本（extensions のみ）

- `extensions/suno-helper/.prettierignore` と `extensions/distrokid-helper/.prettierignore`（8 行、byte 一致）。extensions 配下のどの package.json にも `prettier` は無く、フォーマットは ultracite（Oxfmt）。community-helper（最新）は持っていない。
- **注意**: `dashboard/` と `audio-studio/` の `.prettierrc` / `.prettierignore` は prettier を実際に使うので**触らない**。

### F. fallow baseline の亡霊エントリ（extensions のみ）

- `extensions/.fallow-dupes-baseline.json` の `clone_groups` 先頭 5 エントリが、#2246 の shared-ui 統合で削除済みのパスを指す:
  - `distrokid-helper/components/ui/button.tsx|suno-helper/components/ui/button.tsx`
  - `distrokid-helper/components/ui/card.tsx|suno-helper/components/ui/card.tsx`
  - `distrokid-helper/entrypoints/popup/style.css|suno-helper/components/theme.css`（2 エントリ）
  - （`suno-helper/components/theme.css` 自体の存在は Step 6 で確認すること）
- `extensions/.fallowrc.json` は `"gate": "new-only"` + `"dupesBaseline"` でこのファイルを許容重複の定義として使う。存在しないパスのエントリは gate の判定に寄与しない亡霊。

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Python テスト | `nix develop --command uv run pytest tests/repo/test_skills_sync_installed_wheel.py tests/contracts/ -q` | all pass |
| import 実証 | `nix develop --command uv run python -c "import youtube_automation.utils.image_provider.composition as m; print(m.__file__)"` | canonical 側のパス（`infrastructure/media/image_provider/composition.py`）が出力される |
| Ruff | `nix develop --command uv run ruff check src tests bench` | exit 0 |
| fallow audit | `cd extensions/suno-helper && nix develop .#extensions --command pnpm install --frozen-lockfile && nix develop .#extensions --command pnpm run audit` | exit 0 |

## Scope

**In scope**:
- 削除: A の shim 5 本、B の fixture 5 本、D の `bench/bench_real_apis.py`、E の `.prettierignore` 2 本
- untrack: C の `quota_costs.json.lock`（+ `.gitignore` に 1 行）
- 編集: `extensions/.fallow-dupes-baseline.json`（亡霊エントリ削除）、`src/.../legacy_utils/image_provider/__init__.py`（コメント 1 行追加のみ）、`CHANGELOG.md`

**Out of scope**:
- `legacy_utils/image_provider/__init__.py` のエイリアス実装本体 — downstream 契約の生命線。
- `dashboard/` / `audio-studio/` の prettier 設定 — 現役。
- `bench/` の他ファイル・`bench/main.py` — 現役（bench/ 全体の去就は別判断）。
- `examples/minimax-music-engine.example.json` — 参照ゼロだが「削除 vs README から掲載」の判断待ち（plans/README.md の未選択 findings 参照）。この plan では触らない。

## Git workflow

- issue 専用 linked worktree 上で作業（`$REPO_ROOT/.claude/worktrees/<slug>/`）
- Branch: `advisor/032-sweep-unreferenced-artifacts`
- Commit: `chore: 参照ゼロの残骸を一括削除（legacy shim / fixture / bench / prettier 設定 / fallow baseline） (#<issue番号>)`（1 branch 1 commit）
- push / PR 作成はオペレーター指示があるまで行わない

## Steps

### Step 1: shim 削除前に import 実証を取る

**Verify**: `nix develop --command uv run python -c "import youtube_automation.utils.image_provider.composition as m; print(m.__file__)"` → 出力パスが `infrastructure/media/image_provider/composition.py`（= 兄弟 shim は経由していない証拠）

### Step 2: 兄弟 shim 5 本を削除し、エイリアスの所在をコメントで固定する

```bash
git rm src/youtube_automation/infrastructure/legacy_utils/image_provider/{composition,config,gemini,openai,prompt_schema}.py
```

`__init__.py` の `sys.modules[...]` ブロック直前に 1 行コメントを追加:

```python
# サブモジュールのエイリアスはこの __init__ に集約する（per-file shim は import 機構上実行されないため置かない）
```

**Verify**: Step 1 と同じコマンド → 同じ出力。さらに `nix develop --command uv run pytest tests/repo/test_skills_sync_installed_wheel.py tests/contracts/ -q` → all pass

### Step 3: fixture と lock ファイルを始末する

```bash
git rm -r tests/fixtures/skill_config_verify
git rm --cached tests/fixtures/sample_channel/data/quota_costs.json.lock
```

`.gitignore` の Python セクションに追記: `*.json.lock`

**Verify**: `git grep -ln "skill_config_verify" -- tests src` → 0 件。`git status --porcelain | grep quota_costs` → untracked にも現れない（ignore が効いている）

### Step 4: bench の孤児を削除する

```bash
git rm bench/bench_real_apis.py
```

**Verify**: `git grep -n "bench_real_apis" -- bench .github docs` → 残るのは `bench/bench_strategic_analytics.py:7` の docstring 言及のみ（文意が通るので放置可）

### Step 5: prettierignore を削除する

```bash
git rm extensions/suno-helper/.prettierignore extensions/distrokid-helper/.prettierignore
```

**Verify**: `git ls-files "extensions/*/.prettierignore"` → 0 件（dashboard / audio-studio は対象外なので `git ls-files "*/.prettierignore"` に残ってよい）

### Step 6: fallow baseline の亡霊エントリを除去する

`extensions/.fallow-dupes-baseline.json` の `clone_groups` から、**パイプ区切りのどちらかのパスが存在しない**エントリを削除する。機械的に判定すること（各エントリの `path:lines` からパス部分を取り、`test -e extensions/<path>` で確認）。現時点で該当するのは Current state F の 5 エントリだが、必ず実測で決める。

**Verify**:
- baseline 内の全エントリのパスが `test -e` で存在する
- `cd extensions/suno-helper && nix develop .#extensions --command pnpm run audit` → exit 0

### Step 7: CHANGELOG 追記と全体確認

エントリ文面（A が src を触るためゲート対象）:

```
- legacy_utils/image_provider の実行されない per-file shim 5 本を削除（エイリアスは __init__ に集約済み）。あわせて参照ゼロの fixture・bench オーケストレータ・prettier 設定・fallow baseline の亡霊エントリを掃除
```

**Plan 033（issue #4483）が main にマージ済みの場合**（`test -d changelog.d` で判定）: `CHANGELOG.md` は編集せず、`changelog.d/4464-sweep-unreferenced.removed.md` を新規作成して上の bullet を書く。未マージの場合のみ `CHANGELOG.md` の `[Unreleased]` に追記する。

**Verify**: `nix develop --command uv run pytest tests/ -q` → all pass。`nix develop --command uv run ruff check src tests bench` → exit 0

## Test plan

新規テストは不要（全項目が削除または設定整理）。守るべき挙動は Step 1 / Step 2 の import 実証と downstream 契約テスト（`test_skills_sync_installed_wheel.py`）、および Step 6 の fallow audit グリーンで担保する。

## Done criteria

- [ ] A の 5 shim / B の 5 fixture / D / E の計 13 ファイルが tracked から消えている
- [ ] `git check-ignore tests/fixtures/sample_channel/data/quota_costs.json.lock` → exit 0
- [ ] `uv run python -c "import youtube_automation.utils.image_provider.composition"` が成功する
- [ ] `nix develop --command uv run pytest tests/ -q` が exit 0
- [ ] fallow baseline の全エントリのパスが実在し、`pnpm run audit` が exit 0
- [ ] `CHANGELOG.md` の `[Unreleased]` に追記がある
- [ ] In scope 外の変更がない
- [ ] `plans/README.md` の Status 行を更新した

## STOP conditions

- Step 1 の import 実証で shim 側のパスが出力される（親 `__init__` のエイリアスが変更されている — 前提崩れ）。
- Step 2 後に `tests/contracts/architecture/test_repository_reorganization_contract.py` が fail する（mapping が legacy shim を指すよう変わっている）。
- Step 6 で、存在しないパスのエントリを消すと fallow が**新規重複**として現存コードを報告し、その triage が必要になった場合（grandfathering の再判断はオペレーター事項）。
- `pnpm install` が lockfile 不整合で fail（環境問題。報告）。

## Maintenance notes

- 今後 `legacy_utils/` に互換 shim を足すときは per-file ではなく `__init__.py` のエイリアス集約方式に従う。
- fallow baseline は clone group 内のファイルを削除・移動したら**必ず再生成 or 手動除去**する（`extensions/CLAUDE.md` への明文化は未選択 finding として plans/README.md に記録済み）。
- `bench/` ディレクトリ全体（perf #131 の時限計測フェーズ産、CI 非接続、`bench_strategic_analytics.py` は `time.sleep` を計測している）の去就は別判断として残っている。
