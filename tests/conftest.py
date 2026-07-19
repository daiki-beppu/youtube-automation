"""pytest 設定 - テスト環境設定

テスト実行時に `CHANNEL_DIR` を `tests/fixtures/sample_channel/` を **コピーした**
tmp 配下に向けることで、`cost_tracker` などの実行ログが git 管理下の fixture を
汚染しないようにする（issue #286）。

`CHANNEL_DIR` を確定する処理はモジュールトップで実行する。
session-scope の autouse fixture では、`tests/test_metadata_audit.py` のように
**import 時点** で `channel_dir()` を呼び出すテストの collection phase に間に合わないため。

ユーザが明示的に `CHANNEL_DIR` を指定している場合（例: 別 fixture をデバッグ用に
向ける）はその指定を尊重し、コピー処理をスキップする。

新 loader (`youtube_automation.utils.config`) のシングルトンは各テスト前後で
function-scope の autouse fixture でリセットする。
"""

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# editable install されていない場合に備えて src/ を sys.path に追加
_AUTOMATION_DIR = Path(__file__).resolve().parent.parent
_SRC_DIR = _AUTOMATION_DIR / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

# テスト用フィクスチャディレクトリ（git 管理下のオリジナル）
_FIXTURE_CHANNEL_DIR = Path(__file__).resolve().parent / "fixtures" / "sample_channel"
_OP_READ_DISABLED_ENV = "YOUTUBE_AUTOMATION_DISABLE_OP_READ"
_TEST_TMP_PREFIX = "yt-automation-tests-"
# conftest が CHANNEL_DIR を自動設定したことを示すマーカー。
# xdist worker はこれを見て「ユーザー明示指定」と「controller の自動設定の継承」を
# 区別し、後者なら worker 専用のコピーを作り直す（共有 tmp への並行書き込みを防ぐ）。
_ISOLATED_MARKER_ENV = "YOUTUBE_AUTOMATION_TEST_ISOLATED_CHANNEL_DIR"

# Fast lane から分離する分類の単一 registry。repo_contract は production
# behavior を起動せず repository 内の docs / workflow / packaging を読む module、
# slow は実 tool/process・socket TTL・意図的待機を含む module / node に限定する。
REPO_CONTRACT_MODULES = frozenset(
    {
        "test_actions_parallel_workflows.py",
        "test_analytics_analyze_skill_contract.py",
        "test_analytics_revenue_skill_contract.py",
        "test_changelog_ci_contract.py",
        "test_channel_new_analysis_mode.py",
        "test_cli_stdio.py",
        "test_codex_thumbnail_routing_docs.py",
        "test_comments_reply_skill_doc.py",
        "test_extension_package_manager_contract.py",
        "test_extension_readme_allow_extension_contract.py",
        "test_features_catalog_documentation.py",
        "test_flop_analysis_skill_contract.py",
        "test_lifecycle_skills_no_tayk.py",
        "test_loop_video_preview_skill_contract.py",
        "test_market_research_skill_contract.py",
        "test_no_google_auth_httplib2_direct_import.py",
        "test_pytest_lane_contract.py",
        "test_readme_dev_install_documentation.py",
        "test_scripts_layout.py",
        "test_server_discovery_docs.py",
        "test_skill_api_call_estimate_contract.py",
        "test_skill_cost_documentation.py",
        "test_skill_frontmatter_yaml.py",
        "test_suno_skill_doc.py",
        "test_upgrade_guide_command_guard.py",
        "test_video_description_skill_contract.py",
        "test_wf_new_analytics_fallback_skill_contract.py",
    }
)

SLOW_MODULES = frozenset(
    {
        "test_actions_parallel_workflows.py",
        "test_codex_image_batch.py",
        "test_collection_serve.py",
        "test_collection_serve_discovery.py",
        "test_collection_serve_lifecycle.py",
        "test_community_endpoint.py",
        "test_distrokid_collections_endpoint.py",
        "test_distrokid_prepare.py",
        "test_distrokid_release_endpoint.py",
        "test_generate_videos_script.py",
        "test_lefthook_installation_contract.py",
        "test_preflight_cli.py",
        "test_skills_sync_installed_wheel.py",
        "test_streaming_healthcheck.py",
        "test_thumbnail_codex_image_skill.py",
        "test_thumbnail_skill_assets.py",
        "test_verify_extensions_script.py",
    }
)

SLOW_NODE_IDS = (
    "tests/test_analytics_cli_integration.py::test_yt_analytics_returns_failure_when_subscribed_status_collection_fails",
    "tests/test_audience_analytics.py::TestGetDeviceAnalytics::test_retries_transient_api_failure_through_analytics_entrypoint",
    "tests/test_audience_analytics.py::TestGetSubscribedStatusAnalytics::test_retries_transient_api_failure",
    "tests/test_audience_analytics.py::TestGetSubscribedStatusAnalytics::test_returns_error_shape_for_http_error",
    "tests/test_benchmark_collector_channels_batch.py::TestFetchChannelsMetadata::test_retries_transient_api_failure_through_benchmark_collector",
    "tests/test_comments_fetcher.py::test_retries_transient_api_failure_through_comments_entrypoint",
    "tests/test_competitor_discovery.py::TestDiscoverCompetitors::test_retries_transient_api_failure_through_discovery_entrypoint",
    "tests/test_playlist_manager.py::TestCreatePlaylist::test_retries_transient_api_failure_through_playlist_manager",
)


os.environ.setdefault(_OP_READ_DISABLED_ENV, "1")


def _pid_is_running(pid: int) -> bool:
    """Return whether a process exists without sending it a signal."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _cleanup_stale_isolated_channel_dirs() -> None:
    """Remove leftovers from killed pytest runs without touching active runs."""
    system_tmp = Path(tempfile.gettempdir())
    for candidate in system_tmp.glob(f"{_TEST_TMP_PREFIX}*"):
        if not candidate.is_dir() or candidate.is_symlink():
            continue

        suffix = candidate.name.removeprefix(_TEST_TMP_PREFIX)
        pid_text, separator, _ = suffix.partition("-")
        if separator and pid_text.isdigit() and _pid_is_running(int(pid_text)):
            continue

        shutil.rmtree(candidate, ignore_errors=True)


def _prepare_isolated_channel_dir() -> None:
    """`CHANNEL_DIR` を tmp 配下の sample_channel コピーに向ける。

    ユーザーの既存 env 上書きがあれば尊重する（setdefault 相当）。
    ただし pytest-xdist の worker では、controller が自動設定した値
    （`_ISOLATED_MARKER_ENV` 付き）を継承している場合に限り、worker 専用の
    コピーを作り直して並行書き込みの衝突を防ぐ。
    tmp dir は `atexit` で session（worker プロセス）終了時に削除する。
    """
    _cleanup_stale_isolated_channel_dirs()

    if os.environ.get("CHANNEL_DIR"):
        inherited_from_controller = bool(os.environ.get(_ISOLATED_MARKER_ENV) and os.environ.get("PYTEST_XDIST_WORKER"))
        if not inherited_from_controller:
            return

    tmp_root = Path(tempfile.mkdtemp(prefix=f"{_TEST_TMP_PREFIX}{os.getpid()}-"))
    atexit.register(shutil.rmtree, tmp_root, ignore_errors=True)

    isolated = tmp_root / "sample_channel"
    shutil.copytree(_FIXTURE_CHANNEL_DIR, isolated)
    os.environ["CHANNEL_DIR"] = str(isolated)
    os.environ[_ISOLATED_MARKER_ENV] = "1"


_prepare_isolated_channel_dir()


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Apply registered lane markers before pytest evaluates ``-m`` selection."""
    for item in items:
        module_name = Path(str(item.path)).name
        if module_name in REPO_CONTRACT_MODULES:
            item.add_marker(pytest.mark.repo_contract)
        if module_name in SLOW_MODULES or any(item.nodeid.startswith(prefix) for prefix in SLOW_NODE_IDS):
            item.add_marker(pytest.mark.slow)


@pytest.fixture(autouse=True)
def _reset_config_singleton():
    """新 loader (utils.config) のシングルトン state を各テスト前後でリセット."""
    from youtube_automation.utils.config import reset as reset_config

    reset_config()
    yield
    reset_config()


@pytest.fixture
def no_retry_backoff(monkeypatch):
    """retry backoff の実 sleep を無効化する。

    `execute_with_retry` / `retry_youtube_api` のリトライ経路を通るテストで
    実 backoff（attempt 毎に数秒）を待たないために使う。`time.sleep` を
    グローバルに patch せず、retry モジュールのシームだけを差し替える。
    """
    from youtube_automation.utils import retry as retry_module

    monkeypatch.setattr(retry_module, "_DEFAULT_SLEEP", lambda _seconds: None)
    monkeypatch.setattr(retry_module, "_DEFAULT_JITTER", lambda low, _high: low)
