# loader.py survived mutant triage（issue #4623）

## 結論

`loader.py` を現行 HEAD (`e551469`) で再計測し、3,208 mutants のうち 782 survived を
差分単位で triage した。実ロジックの検出漏れは `_build_overlays` の 21 件、非契約の
エラー・警告文言変異は 149 件、受理済み入力領域で観測上同値となる変異は 612 件だった。
実ロジック 21 件は full override の未観測フィールドを positive assertion へ追加した後、
すべて killed になることを部分再実行で確認した。

#4620 の 886 件は `docs/investigations/2026-08-26-4620-mutmut-adoption.md`（`09e2255c` 時点、
configuration 全体を変異対象にした計測のうち `loader.py` 分）の値である。現行コードだけを
`loader.py` に限定した今回の再計測では、生成数と関数構成が変わっているため 782 件を
triage の母数とした。依存を恒久追加せず、一時クローン `/tmp/mutmut-4623` だけで実行した。

## 分類

| 分類 | before | after | 判断基準 |
|---|---:|---:|---|
| 実ロジック検出漏れ | 21 | 0 | override の入力キーを別キー・既定値へ変えると返却 dataclass が変わる |
| 方針上固定しない | 149 | 149 | `XX...XX` への文字列置換など、例外・警告の非契約文言だけを変える |
| equivalent | 612 | 612 | 正規化・型検査後の受理済み入力領域では返却値または例外種別が同じ |
| **合計** | **782** | **761** | |

「方針上固定しない」は `ConfigError` の例外種別や問題キーの部分一致を既存テストが固定して
いる一方、文章全体を固定しないものに限定した。equivalent は受理前の型検査、`bool` / `str`
正規化、既定値と同値の置換を代表例ごとに確認し、kill 率のためだけの実装詳細 assert は
追加していない。

## 実ロジック検出漏れの全件

次の 21 mutants は、full override fixture に値が存在するのに返却値を assert していなかった
フィールドに対応する。追加 assertion 後の部分再実行ですべて killed になった。

- `x__build_overlays__mutmut_219`
- `x__build_overlays__mutmut_223`
- `x__build_overlays__mutmut_283`
- `x__build_overlays__mutmut_307`
- `x__build_overlays__mutmut_311`
- `x__build_overlays__mutmut_312`
- `x__build_overlays__mutmut_338`
- `x__build_overlays__mutmut_341`
- `x__build_overlays__mutmut_343`
- `x__build_overlays__mutmut_385`
- `x__build_overlays__mutmut_388`
- `x__build_overlays__mutmut_411`
- `x__build_overlays__mutmut_414`
- `x__build_overlays__mutmut_428`
- `x__build_overlays__mutmut_431`
- `x__build_overlays__mutmut_612`
- `x__build_overlays__mutmut_615`
- `x__build_overlays__mutmut_642`
- `x__build_overlays__mutmut_645`
- `x__build_overlays__mutmut_669`
- `x__build_overlays__mutmut_672`

代表差分は `mode` / `fscale` / `win_func`、gradient の `top`、rounding の `contrast`、
独立 glow の `opacity`、encoder の `codec` / `pix_fmt` / `profile` のキーまたは既定値置換。
これらを出力側で直接観測する assertion を追加した。

## 再実測

一時クローンの `pyproject.toml` にだけ次の限定設定を置いた。

```toml
[tool.mutmut]
source_paths = ["src"]
only_mutate = ["src/youtube_automation/configuration/loader.py"]
pytest_add_cli_args_test_selection = ["tests/configuration/test_config_loader.py"]
```

実行コマンド:

```bash
UV_PROJECT_ENVIRONMENT=/tmp/mutmut-4623/.venv uv sync --frozen
uv pip install -q -p /tmp/mutmut-4623/.venv mutmut==3.7.0
/tmp/mutmut-4623/.venv/bin/mutmut run
/tmp/mutmut-4623/.venv/bin/mutmut results
/tmp/mutmut-4623/.venv/bin/mutmut run 'youtube_automation.configuration.loader.x__build_overlays*'
```

| 計測 | killed | no tests | survived |
|---|---:|---:|---:|
| before | 2,155 | 271 | 782 |
| assertion 追加後 | 2,176 | 271 | 761 |

部分再実行は対象 21 件が killed へ移ったことを mutant 名の集合差でも確認した。エラー文言の
完全一致 assert は追加していない。`src/` と恒久依存・mutmut 設定への変更もない。
