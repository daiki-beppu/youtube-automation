"""cost_tracker の quota 記録 + yt-cost-report 集計のユニットテスト。

Issue #2006: YouTube Data API quota の記録 schema と yt-cost-report 集計を追加する。

- 要件 1: quota event（service/bucket/units）を既存 cost record と同じ保存境界
  （CHANNEL_DIR/data/ + file lock + JSON list）で永続化できる
- 要件 2: 保存済み quota を yt-cost-report で集計表示できる
- 要件 3: quota 無しの既存データと後方互換に集計できる
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.cli import cost_report
from youtube_automation.utils import cost_tracker


@pytest.fixture
def tmp_channel(tmp_path: Path, monkeypatch):
    """一時ディレクトリをチャンネルディレクトリとして使う。"""
    monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))
    (tmp_path / "config" / "channel").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "channel" / "meta.json").write_text(
        json.dumps(
            {
                "channel": {"name": "test", "slug": "test", "default_language": "ja"},
                "youtube_channel": {"id": "UC_TEST", "handle": "@test", "url": "https://youtube.com/@test"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "config" / "channel" / "content.json").write_text(
        json.dumps(
            {
                "genre": {"primary": "test"},
                "tags": {"base": []},
                "descriptions": {"short": "", "long": ""},
                "title": {"prefix": "", "suffix": ""},
            }
        ),
        encoding="utf-8",
    )
    from youtube_automation.utils.config import reset

    reset()
    yield tmp_path
    reset()


def _read_quota_file(channel_dir: Path) -> list[dict]:
    path = channel_dir / "data" / "quota_costs.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _write_quota_file(channel_dir: Path, entries: list[dict]) -> None:
    path = channel_dir / "data" / "quota_costs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")


# ============================================================
# log_quota: 記録 schema + 永続化（要件 1）
# ============================================================


def test_log_quota_persists_service_bucket_units(tmp_channel: Path):
    """Given service/bucket/units を渡して log_quota
    When data/quota_costs.json を読む
    Then schema どおりのエントリが永続化されている。
    """
    entry = cost_tracker.log_quota(
        "youtube-data-api",
        "videos.insert",
        1600,
        metadata={"video_id": "abc123"},
    )
    assert entry is not None
    assert entry["service"] == "youtube-data-api"
    assert entry["bucket"] == "videos.insert"
    assert entry["units"] == 1600
    assert entry["metadata"]["video_id"] == "abc123"
    assert entry["timestamp"]

    persisted = _read_quota_file(tmp_channel)
    assert len(persisted) == 1
    assert persisted[0]["service"] == "youtube-data-api"
    assert persisted[0]["bucket"] == "videos.insert"
    assert persisted[0]["units"] == 1600
    assert "estimated_cost_usd" not in persisted[0]


def test_log_quota_appends_to_existing_entries(tmp_channel: Path):
    """Given 既存 quota エントリがある
    When log_quota を追加で呼ぶ
    Then 既存エントリを保持したまま追記される。
    """
    cost_tracker.log_quota("youtube-data-api", "videos.insert", 1600)
    cost_tracker.log_quota("youtube-data-api", "videos.list", 1)
    persisted = _read_quota_file(tmp_channel)
    assert [e["bucket"] for e in persisted] == ["videos.insert", "videos.list"]


def test_log_quota_rejects_empty_service(tmp_channel: Path):
    with pytest.raises(ValueError, match="service"):
        cost_tracker.log_quota("", "videos.insert", 1600)


def test_log_quota_rejects_empty_bucket(tmp_channel: Path):
    with pytest.raises(ValueError, match="bucket"):
        cost_tracker.log_quota("youtube-data-api", "", 1600)


@pytest.mark.parametrize("units", [0, -1])
def test_log_quota_rejects_non_positive_units(tmp_channel: Path, units: int):
    with pytest.raises(ValueError, match="units"):
        cost_tracker.log_quota("youtube-data-api", "videos.insert", units)


def test_log_quota_concurrent_writes_preserve_all_entries(tmp_channel: Path):
    """ThreadPoolExecutor 並列呼び出しで全エントリが欠落せずに記録されること。"""
    from concurrent.futures import ThreadPoolExecutor

    N = 20
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [
            ex.submit(
                cost_tracker.log_quota,
                "youtube-data-api",
                "videos.list",
                1,
                metadata={"idx": i},
            )
            for i in range(N)
        ]
        for f in futures:
            f.result()

    persisted = _read_quota_file(tmp_channel)
    assert len(persisted) == N
    indices = sorted(e["metadata"]["idx"] for e in persisted)
    assert indices == list(range(N))


def test_log_quota_write_failure_warns_and_returns_none(tmp_channel: Path, monkeypatch, capsys):
    """Given 書き込みが失敗する
    When log_quota を呼ぶ
    Then 例外を伝播させず None を返す（呼び出し元を失敗させない契約）。
    """

    def fail_read_entries(path: Path) -> list[dict]:
        raise RuntimeError("forced read failure")

    monkeypatch.setattr(cost_tracker, "_read_entries", fail_read_entries)
    entry = cost_tracker.log_quota("youtube-data-api", "videos.insert", 1600)
    assert entry is None
    assert "quota ログ書き込み失敗" in capsys.readouterr().out


# ============================================================
# read_quota_log: reader + 互換吸収（要件 1 / 3）
# ============================================================


def test_read_quota_log_returns_empty_when_file_absent(tmp_channel: Path):
    """quota ファイルが存在しない既存チャンネルでも空リストで読める（後方互換）。"""
    assert cost_tracker.read_quota_log() == []


def test_read_quota_log_normalizes_missing_keys(tmp_channel: Path):
    """Given キー欠落・型不正のエントリ
    When read_quota_log で読む
    Then デフォルト値で吸収され例外にならない。
    """
    _write_quota_file(
        tmp_channel,
        [
            {"timestamp": "2026-07-01T10:00:00+00:00"},
            {"service": "youtube-data-api", "bucket": "videos.insert", "units": "broken", "metadata": "bad"},
        ],
    )
    entries = cost_tracker.read_quota_log()
    assert len(entries) == 2
    assert entries[0]["service"] == "unknown"
    assert entries[0]["bucket"] == "unknown"
    assert entries[0]["units"] == 0
    assert entries[0]["metadata"] == {}
    assert entries[1]["units"] == 0
    assert entries[1]["metadata"] == {}


# ============================================================
# print_quota_summary: 集計表示（要件 2）
# ============================================================


def test_print_quota_summary_aggregates_by_service_month_bucket(tmp_channel: Path, capsys):
    """Given 複数月・複数 bucket の quota エントリ
    When print_quota_summary を呼ぶ
    Then 総消費 units とサービス別 / 月別 / bucket 別集計が表示される。
    """
    _write_quota_file(
        tmp_channel,
        [
            {
                "timestamp": "2026-06-15T10:00:00+00:00",
                "service": "youtube-data-api",
                "bucket": "videos.insert",
                "units": 1600,
                "metadata": {},
            },
            {
                "timestamp": "2026-07-01T10:00:00+00:00",
                "service": "youtube-data-api",
                "bucket": "videos.insert",
                "units": 1600,
                "metadata": {},
            },
            {
                "timestamp": "2026-07-02T10:00:00+00:00",
                "service": "youtube-data-api",
                "bucket": "videos.list",
                "units": 3,
                "metadata": {},
            },
        ],
    )
    cost_tracker.print_quota_summary()
    out = capsys.readouterr().out
    assert "API Quota Summary" in out
    assert "3203 units" in out
    assert "youtube-data-api: 3203 units" in out
    assert "2026-06: 1600 units" in out
    assert "2026-07: 1603 units" in out
    assert "videos.insert: 3200 units" in out
    assert "videos.list: 3 units" in out


def test_print_quota_summary_without_data_shows_placeholder(tmp_channel: Path, capsys):
    cost_tracker.print_quota_summary()
    out = capsys.readouterr().out
    assert "quota 履歴がまだありません" in out


# ============================================================
# yt-cost-report CLI 統合（要件 2 / 3）
# ============================================================


def _run_cli(monkeypatch, argv: list[str]) -> int:
    monkeypatch.setattr("sys.argv", ["yt-cost-report", *argv])
    return cost_report.main()


def test_cli_quota_flag_shows_quota_summary_only(tmp_channel: Path, monkeypatch, capsys):
    cost_tracker.log_quota("youtube-data-api", "videos.insert", 1600)
    capsys.readouterr()
    assert _run_cli(monkeypatch, ["--quota"]) == 0
    out = capsys.readouterr().out
    assert "API Quota Summary" in out
    assert "Generation Cost Summary" not in out


def test_cli_quota_detail_lists_entries(tmp_channel: Path, monkeypatch, capsys):
    cost_tracker.log_quota("youtube-data-api", "videos.insert", 1600, metadata={"video_id": "abc"})
    capsys.readouterr()
    assert _run_cli(monkeypatch, ["--quota", "--detail"]) == 0
    out = capsys.readouterr().out
    assert "Quota Entries" in out
    assert "videos.insert" in out
    assert "1600 units" in out
    assert "video_id=abc" in out


def test_cli_quota_detail_month_filter(tmp_channel: Path, monkeypatch, capsys):
    _write_quota_file(
        tmp_channel,
        [
            {
                "timestamp": "2026-06-15T10:00:00+00:00",
                "service": "youtube-data-api",
                "bucket": "videos.insert",
                "units": 1600,
                "metadata": {},
            },
            {
                "timestamp": "2026-07-01T10:00:00+00:00",
                "service": "youtube-data-api",
                "bucket": "videos.list",
                "units": 1,
                "metadata": {},
            },
        ],
    )
    assert _run_cli(monkeypatch, ["--quota", "--detail", "--month", "2026-07"]) == 0
    out = capsys.readouterr().out
    assert "videos.list" in out
    assert "videos.insert" not in out


def test_cli_default_summary_appends_quota_when_present(tmp_channel: Path, monkeypatch, capsys):
    """Given 生成コストと quota の両方が記録済み
    When 引数なしで yt-cost-report を実行
    Then 生成サマリに続けて quota サマリが表示される。
    """
    cost_tracker.log_generation("image", model="gemini-3.1-flash-image-preview", quantity=1, unit="image")
    cost_tracker.log_quota("youtube-data-api", "videos.insert", 1600)
    capsys.readouterr()
    assert _run_cli(monkeypatch, []) == 0
    out = capsys.readouterr().out
    assert "Generation Cost Summary" in out
    assert "API Quota Summary" in out


def test_cli_default_summary_without_quota_is_backward_compatible(tmp_channel: Path, monkeypatch, capsys):
    """Given quota 記録の無い既存データのみ（要件 3）
    When 引数なしで yt-cost-report を実行
    Then 従来どおり生成サマリのみで quota セクションは表示されない。
    """
    cost_tracker.log_generation("image", model="gemini-3.1-flash-image-preview", quantity=1, unit="image")
    capsys.readouterr()
    assert _run_cli(monkeypatch, []) == 0
    out = capsys.readouterr().out
    assert "Generation Cost Summary" in out
    assert "API Quota Summary" not in out
    assert "quota 履歴がまだありません" not in out


def test_cli_quota_and_category_are_mutually_exclusive(tmp_channel: Path, monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        _run_cli(monkeypatch, ["--quota", "--category", "image"])
    assert exc.value.code == 2
