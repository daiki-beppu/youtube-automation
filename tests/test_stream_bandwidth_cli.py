"""cli/stream_bandwidth.py のユニットテスト。

要件 R3/R12: `yt-stream-bandwidth` CLI のコマンド分岐をテストする。

CLI モード:
- 引数なし: 現状サマリ stdout
- --report [--month YYYY-MM]: 月次レポート + webhook 投稿
- --check-threshold: 80% 超のみ webhook 投稿、未超は静黙
- --probe-bitrate <PATH>: ffprobe 実測 vs 想定 4 Mbps 照合

すべての I/O 境界 (vultr / terraform / youtube / webhook / probe) を patch する。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from youtube_automation.cli import stream_bandwidth

# ---------- 共通 patch ヘルパー ----------


def _patch_all(
    *,
    instance_id: str = "VULTR_TEST",
    bandwidth: dict | None = None,
    archives: int = 60,
    secrets: dict[str, str] | None = None,
):
    """CLI から呼ばれる全 I/O 境界を一括差し替えるコンテキスト。"""
    bandwidth = bandwidth if bandwidth is not None else {}
    secrets_map = secrets or {
        "VULTR_API_KEY": "fake-vultr-key",
        "STREAM_WEBHOOK_URL": "https://example.com/hook",
    }

    def fake_get_secret(name: str):
        if name not in secrets_map:
            from youtube_automation.infrastructure.errors import ConfigError

            raise ConfigError(f"missing secret: {name}")
        return secrets_map[name]

    return [
        patch(
            "youtube_automation.cli.stream_bandwidth.resolve_instance_id",
            return_value=instance_id,
        ),
        patch(
            "youtube_automation.cli.stream_bandwidth.fetch_bandwidth",
            return_value=bandwidth,
        ),
        patch(
            "youtube_automation.cli.stream_bandwidth.count_archives",
            return_value=archives,
        ),
        patch(
            "youtube_automation.cli.stream_bandwidth.get_secret",
            side_effect=fake_get_secret,
        ),
        patch(
            "youtube_automation.cli.stream_bandwidth.notify",
        ),
    ]


def _enter(mocks):
    return [m.__enter__() for m in mocks]


def _exit(mocks):
    for m in reversed(mocks):
        m.__exit__(None, None, None)


# ---------- default mode (no flags) ----------


def test_default_mode_prints_summary_no_webhook(capsys):
    """Given 引数なし
    When CLI を実行
    Then 現状サマリが stdout に出力され、webhook 投稿は呼ばれない。

    `today()` を当月 (2026-04) の月末に凍結することで、fixture 由来の
    100 GB が `monthly_total_gb` に反映されることを保証する。`today()`
    patch を外すと `"100.0 GB"` assertion が失敗するため、当月不一致
    fixture による偽陽性 pass を防ぐ。
    """
    # 当月 100 GB (1024**3 * 100 bytes)
    bw = {"2026-04-01": {"incoming_bytes": 1024**3 * 100, "outgoing_bytes": 0}}
    mocks = _patch_all(bandwidth=bw)
    enters = _enter(mocks)
    try:
        with patch(
            "youtube_automation.cli.stream_bandwidth.today",
            return_value=date(2026, 4, 30),
        ):
            rc = stream_bandwidth.main(["--instance-id", "VULTR_X"])
    finally:
        _exit(mocks)
    assert rc == 0
    out = capsys.readouterr().out
    # patch を外すと "0.0 GB" になり失敗する形にすることでリグレッションを検出
    assert "100.0 GB" in out
    # notify は呼ばれない
    notify_mock = enters[4]
    notify_mock.assert_not_called()


# ---------- --report ----------


def test_report_mode_calls_notify_with_formatted_text():
    """Given --report
    When CLI を実行
    Then notify が webhook_url 付きで呼ばれ、content にレポート文字列が渡る。
    """
    bw = {
        "2026-03-15": {"incoming_bytes": 1024**3 * 100, "outgoing_bytes": 0},
        "2026-04-15": {"incoming_bytes": 1024**3 * 200, "outgoing_bytes": 0},
    }
    mocks = _patch_all(bandwidth=bw, archives=58)
    enters = _enter(mocks)
    try:
        rc = stream_bandwidth.main(["--report", "--month", "2026-04", "--instance-id", "VULTR_X"])
    finally:
        _exit(mocks)
    assert rc == 0
    notify_mock = enters[4]
    notify_mock.assert_called_once()
    kwargs = notify_mock.call_args.kwargs
    args = notify_mock.call_args.args
    content = kwargs.get("content") if "content" in kwargs else (args[0] if args else None)
    webhook_url = kwargs.get("webhook_url") if "webhook_url" in kwargs else (args[1] if len(args) > 1 else None)
    assert webhook_url == "https://example.com/hook"
    assert content is not None
    assert "2026-04" in content


def test_report_mode_skips_youtube_archive_count_when_archives_are_not_expected():
    """Given ARCHIVES_EXPECTED=False
    When --report を実行
    Then YouTube API 境界とアーカイブ計数を呼ばずにレポートする。
    """
    bw = {"2026-04-15": {"incoming_bytes": 1024**3 * 200, "outgoing_bytes": 0}}
    mocks = _patch_all(bandwidth=bw)
    enters = _enter(mocks)
    try:
        rc = stream_bandwidth.main(["--report", "--month", "2026-04", "--instance-id", "VULTR_X"])
    finally:
        _exit(mocks)

    assert rc == 0
    count_archives_mock = enters[2]
    notify_mock = enters[4]
    count_archives_mock.assert_not_called()
    content = notify_mock.call_args.kwargs["content"]
    assert "アーカイブ数ベース判定なし" in content
    assert "アーカイブ件数: 実測" not in content


def test_report_mode_emits_na_when_previous_month_has_no_data():
    """Given 前月キーを持たない fixture
    When --report --month 2026-04
    Then notify content に "N/A" / "前月データなし" が含まれる。

    `cli/stream_bandwidth.py:136-139` の `previous_usage_gb == 0 → None` 変換と、
    `monthly_report._format_diff_gb` (`utils/streaming/monthly_report.py:20-23`) の
    `"前月比: N/A (前月データなし)"` 出力経路を結合検証する。前月キー (2026-03-*) を
    fixture に含めないことで `monthly_total_gb` が 0.0 を返す経路を素直に通す。
    """
    # 対象月 2026-04 のキーのみ (前月 2026-03 のキーなし)
    bw = {"2026-04-15": {"incoming_bytes": 1024**3 * 200, "outgoing_bytes": 0}}
    mocks = _patch_all(bandwidth=bw)
    enters = _enter(mocks)
    # `_run_report` は --month 明示時 today() を経由しないが、_previous_month の
    # 引数解決と将来の経路変化に備えて凍結し意図を固定する。
    with patch(
        "youtube_automation.cli.stream_bandwidth.today",
        return_value=date(2026, 5, 1),
    ):
        try:
            rc = stream_bandwidth.main(["--report", "--month", "2026-04", "--instance-id", "VULTR_X"])
        finally:
            _exit(mocks)
    assert rc == 0
    notify_mock = enters[4]
    notify_mock.assert_called_once()
    kwargs = notify_mock.call_args.kwargs
    args = notify_mock.call_args.args
    content = kwargs.get("content") if "content" in kwargs else (args[0] if args else None)
    assert content is not None
    assert "N/A" in content
    assert "前月データなし" in content


def test_report_mode_defaults_to_previous_month_when_month_not_given():
    """Given --report のみ (--month 省略)
    When CLI を実行
    Then 前月 (実行日からの前月) を使ってレポートする。
    フリーズ日付で挙動を固定する。
    """
    bw = {
        "2026-03-15": {"incoming_bytes": 1024**3 * 50, "outgoing_bytes": 0},
        "2026-04-10": {"incoming_bytes": 1024**3 * 50, "outgoing_bytes": 0},
    }
    mocks = _patch_all(bandwidth=bw)
    enters = _enter(mocks)
    # 2026-05-01 を「今日」とみなして前月を 2026-04 に解決させる
    with patch("youtube_automation.cli.stream_bandwidth.today", return_value=__import__("datetime").date(2026, 5, 1)):
        try:
            rc = stream_bandwidth.main(["--report", "--instance-id", "VULTR_X"])
        finally:
            _exit(mocks)
    assert rc == 0
    notify_mock = enters[4]
    notify_mock.assert_called_once()
    kwargs = notify_mock.call_args.kwargs
    args = notify_mock.call_args.args
    content = kwargs.get("content") if "content" in kwargs else (args[0] if args else None)
    assert "2026-04" in content


def test_report_mode_january_first_resolves_to_previous_year_december():
    """Given --report のみ かつ 今日が 1/1 (年跨ぎ cron 起動)
    When CLI を実行
    Then 前年 12 月のレポートを生成する。

    cron `0 0 1 * *` が 1 月 1 日 0:00 に発火した際、前月 = 前年 12 月に
    解決される必要がある。R11「月初 cron で前月レポートを自動投稿」の
    年跨ぎエッジケース（_previous_month の `month == 1` 分岐）の回帰防止。
    """
    bw = {
        "2025-12-15": {"incoming_bytes": 1024**3 * 100, "outgoing_bytes": 0},
        "2026-01-01": {"incoming_bytes": 1024**3 * 1, "outgoing_bytes": 0},
    }
    mocks = _patch_all(bandwidth=bw)
    enters = _enter(mocks)
    with patch(
        "youtube_automation.cli.stream_bandwidth.today",
        return_value=__import__("datetime").date(2026, 1, 1),
    ):
        try:
            rc = stream_bandwidth.main(["--report", "--instance-id", "VULTR_X"])
        finally:
            _exit(mocks)
    assert rc == 0
    notify_mock = enters[4]
    notify_mock.assert_called_once()
    kwargs = notify_mock.call_args.kwargs
    args = notify_mock.call_args.args
    content = kwargs.get("content") if "content" in kwargs else (args[0] if args else None)
    # 前年 12 月のレポートが生成され、当月 (2026-01) のデータでは無いこと。
    assert "2025-12" in content
    assert "2026-01" not in content


# ---------- --check-threshold ----------


def test_check_threshold_silent_when_under_threshold():
    """Given usage が閾値未満
    When --check-threshold
    Then notify は呼ばれない (silent)。

    silent モードは stdout を持たないため `notify.assert_not_called()` だけでは
    0 GB 経路と 100 GB 経路を区別できない。`today()` を当月に凍結したうえで
    `is_over_threshold` を spy 化し、call_args.usage_gb=100.0 を verify する
    ことで、fixture 由来の usage が閾値判定に届いていることを白箱検証する。
    """
    # 100 GB (閾値 1638.4 GB を大きく下回る)
    bw = {"2026-04-15": {"incoming_bytes": 1024**3 * 100, "outgoing_bytes": 0}}
    mocks = _patch_all(bandwidth=bw)
    enters = _enter(mocks)
    try:
        with (
            patch(
                "youtube_automation.cli.stream_bandwidth.today",
                return_value=date(2026, 4, 30),
            ),
            patch(
                "youtube_automation.cli.stream_bandwidth.is_over_threshold",
                return_value=False,
            ) as mock_threshold,
        ):
            rc = stream_bandwidth.main(["--check-threshold", "--instance-id", "VULTR_X"])
    finally:
        _exit(mocks)
    assert rc == 0
    notify_mock = enters[4]
    notify_mock.assert_not_called()
    # 閾値判定は fixture 由来の 100 GB で評価されている (0 GB 経路の偽陽性ではない)
    assert mock_threshold.call_args.kwargs["usage_gb"] == pytest.approx(100.0)


def test_check_threshold_alerts_when_over_80_percent():
    """Given usage が 1700 GB (閾値 1638.4 GB 超)
    When --check-threshold
    Then notify が webhook_url 付きで呼ばれる。
    """
    bw = {"2026-04-15": {"incoming_bytes": 1024**3 * 1700, "outgoing_bytes": 0}}
    mocks = _patch_all(bandwidth=bw)
    enters = _enter(mocks)
    try:
        # 当月扱い (今日に対する月) の判定が必要なら CLI が解決する想定
        with patch(
            "youtube_automation.cli.stream_bandwidth.today",
            return_value=__import__("datetime").date(2026, 4, 30),
        ):
            rc = stream_bandwidth.main(["--check-threshold", "--instance-id", "VULTR_X"])
    finally:
        _exit(mocks)
    assert rc == 0
    notify_mock = enters[4]
    notify_mock.assert_called_once()


# ---------- --probe-bitrate ----------


def test_probe_bitrate_mode_compares_against_4mbps(capsys, tmp_path: Path):
    """Given --probe-bitrate <PATH>
    When CLI を実行
    Then probe_bitrate を呼び、想定 4 Mbps と比較した結果が stdout に出る。
    """
    fake_path = tmp_path / "stream.mp4"
    fake_path.write_bytes(b"")
    # 5 Mbps 相当
    with (
        patch(
            "youtube_automation.cli.stream_bandwidth.probe_bitrate",
            return_value=5_000_000.0,
        ),
    ):
        rc = stream_bandwidth.main(["--probe-bitrate", str(fake_path)])
    assert rc == 0
    out = capsys.readouterr().out
    # 想定 4 Mbps と実測 5 Mbps の両方が読める
    assert "4" in out
    assert "5" in out
    assert ("Mbps" in out) or ("mbps" in out.lower())


def test_probe_bitrate_returns_nonzero_when_probe_fails(tmp_path: Path):
    """Given probe_bitrate が None を返す (ffprobe 未インストール等)
    When --probe-bitrate
    Then exit code 非 0 で失敗を表現する (フォールバックで成功扱いにしない)。
    """
    fake_path = tmp_path / "stream.mp4"
    fake_path.write_bytes(b"")
    with patch(
        "youtube_automation.cli.stream_bandwidth.probe_bitrate",
        return_value=None,
    ):
        rc = stream_bandwidth.main(["--probe-bitrate", str(fake_path)])
    assert rc != 0


# ---------- argparse 妥当性 ----------


def test_main_returns_int_for_systemd_exit():
    """Given 引数なし
    When main を呼ぶ
    Then int を返す (sys.exit(main()) で使われる)。
    """
    bw = {"2026-04-01": {"incoming_bytes": 0, "outgoing_bytes": 0}}
    mocks = _patch_all(bandwidth=bw)
    _enter(mocks)
    try:
        rc = stream_bandwidth.main(["--instance-id", "VULTR_X"])
    finally:
        _exit(mocks)
    assert isinstance(rc, int)


# ---------- R13: --help が落ちない (% リテラルのエスケープ回帰防止) ----------


def test_format_help_does_not_crash_on_percent_literal():
    """Given _build_parser() で構築した parser
    When format_help() を呼ぶ
    Then ValueError 等の例外を投げず、ヘルプ文字列を返す。

    R13 (Issue #110 派生): description / help 文字列内の "80%" は argparse の
    `_expand_help` が `%(prog)s` 形式の format 指定として解釈するため、
    `%%` でエスケープしないと `ValueError: unsupported format character ...`
    で `--help` 経路全体が異常終了する。本テストは parser 構築だけで完結し
    I/O 境界に到達しない pure な経路で `format_help()` を呼ぶことで、
    description (R13: stream_bandwidth.py:72) と --check-threshold の
    help (R13: stream_bandwidth.py:84) の両方を一度に検証する。
    """
    parser = stream_bandwidth._build_parser()

    # format_help() は ValueError を含む一切の例外を投げてはならない。
    help_text = parser.format_help()

    # エスケープ後 (`80%%`) も画面表示時には `80%` に戻ること。
    # 利用者が「閾値が 80% であること」をヘルプから読み取れる契約。
    assert "80%" in help_text


def test_help_flag_prints_usage_with_zero_exit(capsys):
    """Given `--help`
    When CLI を実行
    Then SystemExit(0) で終了し、stdout に usage を出力する。

    R13 の利用者到達経路全体の回帰防止。argparse の `--help` は
    `print_help()` を経由して `format_help()` を呼ぶため、内部で
    例外が起きると SystemExit(0) ではなく未捕捉例外で死ぬ。
    """
    with pytest.raises(SystemExit) as exc_info:
        stream_bandwidth.main(["--help"])

    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    # argparse は usage 行から始まるヘルプを stdout に出す。
    assert "usage" in out.lower()
    assert "--report" in out
    assert "--check-threshold" in out
    assert "--probe-bitrate" in out
