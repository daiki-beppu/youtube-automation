# mutation testing ツール mutmut の導入可否調査（issue #4620）

pyscn に続く CI 品質ゲート候補として mutation testing ツール mutmut を評価した記録。
実測 PoC は `src/youtube_automation/configuration/`（19 ファイル）に限定し、
コード・依存関係への恒久変更は行っていない（PoC は scratchpad の一時クローンで実施。
本 PR の diff は本レポートのみ）。

## 結論

**CI 品質ゲートとしては不採用。ローカルのオンデマンド検出力監査ツールとしては条件付きで有効。**

- ゲート不採用の根拠: (1) mutant 実行前の固定オーバーヘッドだけで全スイート単プロセス 2 周
  （stats 22 分 + clean tests。clean tests は実測で 2.6 時間経過後に flake 1 件で中断）が必要、
  (2) 全 src への適用は mutant 数の粗い比例見積りで 11 時間超となり GitHub Actions の
  job 上限（6 時間)を超える、(3) `-x` 前提の実行モデルのため flaky テスト 1 件で全体が中断する、
  (4) ベースラインで原理的に失敗する静的契約テスト 41 件の deselect リストを保守し続ける
  運用コストが発生する。
- 条件付きで有効の根拠: 「閉じたモジュール + 対応テストディレクトリ」に限定すれば
  39 分で完走し、実際に検出力の穴（legacy override 解決経路がどのテストにも固定されていない等）を
  具体的な diff として特定できた。恒久導入はせず、必要時に本レポートの再現手順で実行する。
- survived mutant の triage から得られたテスト強化候補は別 issue として起票する（スコープ外）。

## 実測 PoC

### 計測条件

| 項目 | 値 |
|---|---|
| マシン | Apple M4（10 コア）/ 16 GB RAM / macOS 26.6.2 |
| 実行環境 | uv 0.12.3 / Python 3.11（`uv sync` した PoC 用 venv。nix devShell 経由の再現手順は後述） |
| mutmut | 3.7.0（2026-07-31 リリース） |
| 変異対象 | `src/youtube_automation/configuration/`（19 ファイル・3,075 行） |
| テスト選択 | `tests/configuration/`（488 件）+ ベースラインで成立しない 41 nodeid を deselect |
| ベースコミット | `09e2255c` |

### 測定値

| 項目 | 値 |
|---|---|
| 生成 mutant 数 | **3,723** |
| killed | **2,738** |
| survived | **985**（timeout 0・skipped 0） |
| **kill 率** | **73.5%** |
| mutant 生成時間 | 128 秒（変異 19 ファイル + 複製 434 ファイル。2 回目以降はキャッシュで ~7 秒） |
| mutant 実行フェーズ | 1,692 秒（2.20 mutations/秒。CPU 数分の子プロセスで並列） |
| 総 wall-clock | 2,357 秒（39 分 17 秒。再複製チェック・stats・clean tests・forced fail 含む） |

参考値（フェーズ規模の把握用）:

| 項目 | 値 |
|---|---|
| 全スイート `pytest -n auto`（通常環境・10,190 件） | 565 秒 |
| 全スイート単プロセス（mutants 複製内・stats 相当） | 1,318 秒 |
| clean tests フェーズ（テスト選択なしの場合） | 9,404 秒経過時点で flake 1 件により中断（完走せず） |

### survived mutant の内訳と具体例

survived 985 件の 90% は `loader.py`（886 件）に集中し、関数別では
`_build_overlays`（268）・`_build_comments`（180）・`_build_schedule`（88）が上位。
CLAUDE.md が「新キー追加で登録を忘れやすい」と警告している loader 集中は、
テスト検出力の分布としても裏付けられた。

実物の diff（`mutmut show <mutant名>` の出力）から 2 類型を例示する:

**類型 1: 本物の検出力の穴** — legacy override の解決経路がどのテストにも固定されていない。
この行を壊しても `tests/configuration/` は全て green のままになる。

```diff
# youtube_automation.configuration.skills.x_load_skill_config__mutmut_29: survived
-    if override_path is None and (legacy_owner := _NAMESPACED_LEGACY_OVERRIDE_OWNERS.get(skill)) is not None:
+    if override_path is None and (legacy_owner := _NAMESPACED_LEGACY_OVERRIDE_OWNERS.get(None)) is not None:
```

**類型 2: 方針上テストで固定しないもの** — エラーメッセージ文言の変異。
survived の相当数がこの類型で、triage では機械的に除外してよい
（テストポリシーは非契約文字列の完全一致固定を禁じている）。

```diff
# youtube_automation.configuration.loader.x__build_comments__mutmut_10: survived
-        raise ConfigError("comments セクションは object でなければなりません")
+        raise ConfigError("XXcomments セクションは object でなければなりませんXX")
```

kill 率 73.5% は「`tests/configuration/` に対する」値である点に注意。
survived の一部は `tests/application/` 等の上位テストが殺せる可能性があり、
全スイートで測れば kill 率は上がる。ただし全スイートモードは後述のとおり実行時間の面で
成立しなかったため、本 PoC ではモジュール所有テストに対する検出力として解釈する。

### pytest-xdist との併用

競合しない（そのまま共存できる）。mutmut は pytest を `-x -q` の単プロセスで in-process
実行し、並列化は mutant 単位の自前 process pool（CPU 数の子プロセス）で行うため、
xdist がインストールされていても使われない。本リポジトリは `addopts` に `-n` を
書いていないため設定変更も不要。逆に stats / clean tests の全スイート実行も単プロセスに
なる（22 分/周 の主因）。`pytest_add_cli_args` に `-n` を足して stats を xdist 化できるかは
未検証（mutant 切替が環境変数ベースのため worker への伝播確認が必要）。

## 本リポジトリで mutmut を動かすまでの落とし穴（実測で判明）

mutmut 3 は `mutants/` ディレクトリにソースとテストを複製し、その中で pytest を
in-process 実行する。この複製モデルが本リポジトリのテストスイートと 4 点で衝突した。
いずれも再現手順の設定で回避済み。

| # | 症状 | 原因 | 回避策 |
|---|------|------|--------|
| 1 | `tests/repo/` などが collection error（`.claude/skills/...py` が無い） | `mutants/` には `source_paths` + tests しか複製されず、リポジトリ実ファイルを読む contract テストが参照先を失う | `also_copy` でリポジトリ top-level をほぼ全部複製する |
| 2 | `yt-collection-serve` の subprocess 起動テストが `FileNotFoundError` | `uv run --with mutmut` の一時 overlay 環境は console script の実体パスが揮発する | mutmut を PoC 環境の venv に `uv pip install` し、`uv run --no-sync mutmut run` で実行する |
| 3 | `python3` を bare 起動するテストが `ModuleNotFoundError` | venv の bin が PATH に無いと系外 python が解決される | 同上（`uv run --no-sync` が PATH に `.venv/bin` を通す） |
| 4 | ベースライン（無変異）で 41 テストが失敗し stats 収集が中断 | (a) symlink 実体・wheel/sdist 内容・nix devShell・codex CLI を検証する静的契約テストは `mutants/` 複製内で原理的に成立しない（`also_copy` の copytree が symlink を実体化する等）。(b) `warnings` の発生元 filename を検証するテストは trampoline 経由呼び出しで帰属が変わる | 該当 nodeid を `pytest_add_cli_args` の `--deselect` で除外（`-m "not repo_contract"` では不足 — マーカーが付いていない静的契約テストが `tests/configuration/` 等にも分布している） |

除外したのは静的リポジトリ契約・パッケージング・外部 CLI 系のみで、
`configuration/` のロジックを exercise するテストではないため kill 率の測定は歪まない。

## 価値の低いテストの特定可否

**「どの mutant も殺さないテスト」の特定は mutmut 単体では不可。方向を変えた
「どのテストにも守られていないコード箇所」の特定は可能（= survived 一覧そのもの）。**

- 不可の理由: mutmut は mutant ごとに `-x`（最初の失敗で停止）でテストを実行するため、
  「その mutant を殺せるテストの全列挙」を記録しない。テスト単位の kill 貢献マトリクスを
  出す組み込み機能は `results` / `browse` / `export-cicd-stats` のいずれにも無い。
  cosmic-ray / mutatest にも同等機能は無く、ツール乗り換えでは解決しない。
- 部分的に可能なこと: stats 収集が「変異対象の関数を実行しないテストは選択しない」ため、
  変異対象モジュールに一切関与しないテストはカバレッジベースで峻別されている。
  ただしこれは「関与しない」であって「価値が低い」ではない。
- 代替手段: 検出範囲が他テストと重複するテストの特定には、mutation testing よりも
  coverage.py の dynamic contexts（`--cov-context=test` でテスト単位の行カバレッジを記録し、
  「そのテストだけがカバーする行が 0 のテスト」を抽出する）が直接的で、実行時間も
  通常のカバレッジ計測と同等で済む。この分析が必要になった場合は別 issue として
  切り出すのが妥当。

## 代替ツールとの簡易比較

実測は mutmut のみ。以下は文献ベースの比較（2026-08-26 時点）。

| 項目 | mutmut | cosmic-ray | mutatest |
|---|---|---|---|
| 最新版 / リリース日 | 3.7.0 / 2026-07-31 | 8.7.0 / 2026-08-09 | 3.1.0 / 2021（休眠） |
| メンテ状況 | 活発 | 活発 | 12 か月以上リリースなし・PR/issue 活動なし |
| 変異方式 | libcst でソースを書き換えた `mutants/` コピー + trampoline（全 mutant を 1 回の import で切替） | AST 書き換え、mutant ごとにソース適用 | `__pycache__`（バイトコード）差し替え。ソース非変更 |
| テスト選択 | stats 収集で関数→テストの対応を取り、mutant ごとに関係テストのみ実行 | なし（mutant ごとに指定テストコマンドを全実行） | coverage ベースで意味のある mutant のみ生成 |
| 並列実行 | 自前の process pool（CPU 数） | セッション分散（local / http distributor で複数 worker） | なし |
| 差分限定実行 | 結果キャッシュ + `mutmut run <mutant名パターン>` の部分実行 | `cr-filter-git` で git 差分外の mutant を skip | サンプリング方式（全数実行しない設計） |
| CI 向け出力 | `export-cicd-stats` / `badge` | `cr-report` / `cr-rate`（閾値で exit code 制御） | JSON / テキストレポート |
| 設定 | `pyproject.toml::[tool.mutmut]` | 専用 TOML | CLI 引数 / TOML |

- mutmut を実測対象に選んだ理由: 3 ツール中で唯一「カバレッジ統計に基づく mutant ごとの
  テスト選択」を組み込みで持ち、実行時間の主因（mutant 数 × スイート実行時間）を
  構造的に削れる。設定も `pyproject.toml` に閉じ、pytest をそのまま in-process 実行する。
  mutatest は休眠しており新規導入の対象にならない。cosmic-ray は分散実行が強みだが、
  単一マシン PoC ではセットアップ（セッション DB・worker 起動）が重く、テスト選択が
  無いため 1 mutant あたりのコストが mutmut より高い。

## CI 品質ゲート化の実現性評価

### 全体適用の推定実行時間

mutant 数はコード量に概ね比例する（configuration/ 19 ファイルで 3,723 mutants）。
src 全体 453 ファイルへの適用は粗い比例で約 **8.9 万 mutants**。mutant 実行レートを
本 PoC の 2.20 mutations/秒（軽量な 488 テスト選択時の値 = 楽観値）としても
**約 11.2 時間** + 固定オーバーヘッド（stats / clean tests で全スイート単プロセス 2 周 ≧ 44 分、
実測では clean tests が 2.6 時間で中断）となり、GitHub Actions の job 上限 6 時間を超える。
実際には対象モジュールが広いほど mutant ごとの選択テスト数が増えレートは悪化するため、
これは下限の見積りである。

### 差分限定実行の可否

機構としては可能だが、本リポジトリでは固定オーバーヘッドが支配的で成立しない。
`mutmut run` は mutant 名パターンの部分実行と結果キャッシュを持つため、変更ファイルの
mutant に限定する運用は組める。しかし stats / clean tests の全スイート実行は
変更量に関係なく毎回かかり（≧ 44 分/回）、さらに `-x` 前提のため 10,190 件スイート中の
flaky テスト 1 件で全体が中断する（実測で 2 回発生: `test_collection_serve_lifecycle`、
`test_broadcast_recovery` — いずれも通常環境の単体実行では green）。
deselect リスト（41 nodeid）の保守も継続コストになる。
テスト選択を `tests/configuration` のような scope に固定すれば安定するが、
それは「差分ゲート」ではなく「モジュール限定監査」であり、CI で常時回す価値と釣り合わない。

### 採否推奨

**CI 品質ゲートとしては不採用**（上記 3 点: 実行時間・flake 感受性・deselect 保守）。
**「閉じたモジュール + 所有テストディレクトリ」単位のオンデマンド監査としては条件付き採用**:
39 分で完走し、survived diff がテスト強化の具体的な出発点になることは実証済み。
恒久導入（dev 依存追加・`[tool.mutmut]` コミット）は行わず、必要時に下記の再現手順で
一時環境に導入して実行する。survived triage から出るテスト追加候補は別 issue に起票する。

## 再現手順

PoC はリポジトリの一時クローンで行う（`mutants/` ディレクトリと pyproject 追記を
作業ツリーに持ち込まないため）。

```bash
# 1. 一時クローンを作る（実測時のベース: 09e2255c）
git clone --depth 1 "file://$(git rev-parse --show-toplevel)" /tmp/mutmut-poc
cd /tmp/mutmut-poc

# 2. pyproject.toml に PoC 設定を追記する（コミットしない）
cat >> pyproject.toml <<'EOF'

[tool.mutmut]
source_paths = ["src"]
only_mutate = ["src/youtube_automation/configuration/*"]
also_copy = [
    ".agents", ".claude", ".codex", ".envrc", ".gitattributes", ".github",
    ".gitignore", ".hallmark", ".nix", ".python-version", ".takt",
    "AGENTS.md", "CHANGELOG.md", "CLAUDE.md", "LICENSE", "ONBOARDING.md",
    "README.md", "audio-studio", "bench", "changelog.d", "dashboard", "docs",
    "evals", "examples", "extensions", "flake.lock", "flake.nix",
    "hatch_build.py", "infra", "plans", "site", "skills-lock.json", "uv.lock",
]
pytest_add_cli_args_test_selection = ["tests/configuration"]
pytest_add_cli_args = ["--deselect=tests/configuration/test_skill_config.py::test_load_skill_config_postmortem_warns_for_legacy_override", "--deselect=tests/configuration/test_thumbnail_skill_assets.py::test_thumbnail_compare_is_disclosed_as_a_thumbnail_mode"]
EOF

# 3. devShell 内で venv を作り、mutmut を入れて実行する。
#    shellHook の uv sync が lockfile 外パッケージ（mutmut）を削除するため、
#    install と run は必ず同一 shell 内で連結する
nix develop --command bash -c '
  uv sync &&
  uv pip install -q -p .venv mutmut==3.7.0 &&
  uv run --no-sync mutmut run
'

# 4. 結果の確認
nix develop --command bash -c '
  uv pip install -q -p .venv mutmut==3.7.0 &&
  uv run --no-sync mutmut results | grep -c ": survived"   # → 985
'
# 個別 mutant の diff は: uv run --no-sync mutmut show <mutant名>
# 対話ブラウズは:        uv run --no-sync mutmut browse
```

補足:

- 実測は devShell 外の同一 uv toolchain（uv 0.12.3 / Python 3.11）で行い、
  手順 3〜4 の devShell 経由でも同一結果になることを `mutmut results` で確認済み
- テスト選択を全スイートに広げる場合は `pytest_add_cli_args_test_selection` を外し、
  「落とし穴」節の deselect 41 件（`tests/repo/` ほか）を追加する。ただし clean tests
  フェーズが数時間規模になり flake で中断し得ることは上記のとおり
- deselect 対象の全 nodeid 一覧は、`--maxfail=0` を `pytest_add_cli_args` に一時追加して
  `mutmut run` を実行するとベースライン失敗として一括列挙できる
