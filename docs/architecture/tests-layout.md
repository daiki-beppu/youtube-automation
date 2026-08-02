# tests 配置規約

この文書は `tests/` の配置とパス参照に関する正本である。テストを追加・移動するときは、次の規則に従う。

## 鏡像規則

`src/youtube_automation/<layer>/<sub>/<module>.py` のテストは、対応する `tests/<layer>/<sub>/test_<module>.py` に置く。既存テストを移動する場合も、まず対応する production module の canonical owner を確認する。

## `tests/repo/`

`youtube_automation` を実行時に import せず、docs、CI、packaging、skill などリポジトリ自体の構造・配布物・静的契約を検査するテストは `tests/repo/` に置く。既存の repository contract は後続の配置変更でこの規則に従って移動する。

## `tests/integration/`

複数 layer をまたいで実際の tool、process、filesystem、network 境界を検証する end-to-end テストは `tests/integration/` に置く。これは鏡像規則の例外として扱う。

## `tests/helpers/`

`tests/helpers/` はテスト module ではなく、複数テストが利用する helper package である。鏡像規則の対象外とし、helper はこの領域に置く。テスト専用の repository path は `tests.helpers.paths` が公開する `REPO_ROOT`、`TESTS_DIR`、`FIXTURES_DIR` から解決する。

## 同名衝突の裁定

同じ stem のテストが複数 layer に対応し得る場合は、そのテストが最も多く import している layer に置く。同数の場合は、テスト名が指す production module の canonical owner の layer に置く。

## パス参照

`tests/helpers/paths.py` 以外では `Path(__file__)` からパスを組み立てない。repository root、`tests/`、fixture の各境界は、必ず `tests.helpers.paths` の `REPO_ROOT`、`TESTS_DIR`、`FIXTURES_DIR` を利用する。`paths.py` 自身だけが固定された helper package の深さから `REPO_ROOT` を導出する。
