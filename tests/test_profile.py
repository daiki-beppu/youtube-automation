"""Tests for `youtube_automation.utils.profile`."""

from __future__ import annotations

import json
from contextlib import nullcontext

import pytest

from youtube_automation.utils import profile


@pytest.fixture(autouse=True)
def _reset_profile():
    profile.reset()
    yield
    profile.reset()


def test_section_is_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("YT_PROFILE", raising=False)
    cm = profile.section("foo")
    # 無効時は nullcontext のシングルトンを返す（オーバーヘッドゼロ）
    assert cm is profile._NOOP
    with cm:
        pass


def test_section_records_when_enabled(monkeypatch, capsys):
    monkeypatch.setenv("YT_PROFILE", "1")
    with profile.section("bar"):
        pass
    captured = capsys.readouterr()
    assert "section=bar" in captured.err
    assert "elapsed_ms=" in captured.err
    assert "bar" in profile._records
    assert len(profile._records["bar"]) == 1


def test_section_writes_jsonl_when_out_path_set(monkeypatch, tmp_path):
    out = tmp_path / "profile.jsonl"
    monkeypatch.setenv("YT_PROFILE", "1")
    monkeypatch.setenv("YT_PROFILE_OUT", str(out))
    with profile.section("baz", count=42):
        pass
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["section"] == "baz"
    assert record["count"] == 42
    assert isinstance(record["elapsed_ms"], float)


def test_extra_kwargs_are_included_in_stderr(monkeypatch, capsys):
    monkeypatch.setenv("YT_PROFILE", "1")
    with profile.section("qux", n=3, label="x"):
        pass
    err = capsys.readouterr().err
    assert "section=qux" in err
    assert "n=3" in err
    assert "label=x" in err


def test_dump_summary_outputs_percentiles(monkeypatch, capsys):
    monkeypatch.setenv("YT_PROFILE", "1")
    for _ in range(5):
        with profile.section("perc"):
            pass
    profile._dump_summary()
    err = capsys.readouterr().err
    assert "PROFILE SUMMARY" in err
    assert "perc" in err
    assert "p50=" in err
    assert "p95=" in err


def test_flag_truthy_variants(monkeypatch):
    for value in ("1", "true", "TRUE", "Yes"):
        monkeypatch.setenv("YT_PROFILE", value)
        assert profile._flag("YT_PROFILE") is True
    for value in ("", "0", "no", "false"):
        monkeypatch.setenv("YT_PROFILE", value)
        assert profile._flag("YT_PROFILE") is False


def test_noop_is_nullcontext():
    assert isinstance(profile._NOOP, type(nullcontext()))
