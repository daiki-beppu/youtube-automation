# tests 配置規約

この文書は `tests/` の配置とパス参照に関する正本である。テストを追加・移動するときは、次の規則に従う。

## 鏡像規則

`src/youtube_automation/<layer>/<sub>/<module>.py` のテストは、対応する `tests/<layer>/<sub>/test_<module>.py` に置く。既存テストを移動する場合も、まず対応する production module の canonical owner を確認する。

同じ production module に複数のテスト module が対応する場合は、テストの basename を変更せず、それぞれを独立した module として同じ鏡像ディレクトリに置く。鏡像規則は 1 module = 1 test の単射を要求しない。

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

## `tests/` 直下に残るテスト

次のテストは、単一の production module の鏡像へ帰属できないか、対象外の境界を横断するため、現段階では `tests/` 直下に残す。

- `test_analytics_cli_integration.py`: 複数 layer の CLI 実経路を検証する統合テスト
- `test_b3_domain_migration_contract.py`: architecture contract（`tests/contracts/` 再編は対象外）
- `test_b4_auth_resource_contract.py`: architecture/package contract（同上）
- `test_b4_reorganization_contract.py`: architecture contract（同上）
- `test_bench_cost_tracker.py`: `bench/bench_cost_tracker.py` が source package 外
- `test_channel_new_fetch_branding_snapshot.py`: skill reference executable
- `test_cli_help_contract.py`: `entrypoints.py` の root module と複数 console script の契約
- `test_cli_stdio.py`: `cli_stdio.py` の root module の契約
- `test_codex_image_batch.py`: skill batch executable
- `test_codex_thumbnail_routing.py`: 複数 layer にまたがり単一の同名 owner がない routing 契約
- `test_community_draft_batch.py`: skill subprocess / filesystem 実経路
- `test_conftest_isolation.py`: `tests/conftest.py` 自体の試験
- `test_entrypoints.py`: `entrypoints.py` の root module の契約
- `test_generate_videos_script.py`: skill shell / process / filesystem 実経路
- `test_wf_new_analytics_fallback_skill_contract.py`: production import と skill subprocess を横断する契約（`tests/integration/` 再編は対象外）
- `test_oauth_onboarding_contract.py`: docs / scripts / auth 境界を横断する契約
- `test_package_version.py`: package root `__init__.py` の契約
- `test_streaming_healthcheck.py`: streaming 領域の統合契約（streaming 再編は対象外）
