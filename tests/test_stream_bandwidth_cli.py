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

from pathlib import Path
from unittest.mock import patch

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
            from youtube_automation.utils.exceptions import ConfigError

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
        patch(
            "youtube_automation.cli.stream_bandwidth.get_youtube",
            return_value=object(),
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
    """
    bw = {"2026-04-01": {"incoming_bytes": 1024**3, "outgoing_bytes": 0}}
    mocks = _patch_all(bandwidth=bw)
    enters = _enter(mocks)
    try:
        rc = stream_bandwidth.main(["--instance-id", "VULTR_X"])
    finally:
        _exit(mocks)
    assert rc == 0
    out = capsys.readouterr().out
    # サマリ出力を確認 (GB を含む)
    assert "GB" in out
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


# ---------- --check-threshold ----------


def test_check_threshold_silent_when_under_threshold():
    """Given usage が閾値未満
    When --check-threshold
    Then notify は呼ばれない (silent)。
    """
    # 100 GB (閾値 1638.4 GB を大きく下回る)
    bw = {"2026-04-15": {"incoming_bytes": 1024**3 * 100, "outgoing_bytes": 0}}
    mocks = _patch_all(bandwidth=bw)
    enters = _enter(mocks)
    try:
        rc = stream_bandwidth.main(["--check-threshold", "--instance-id", "VULTR_X"])
    finally:
        _exit(mocks)
    assert rc == 0
    notify_mock = enters[4]
    notify_mock.assert_not_called()


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
