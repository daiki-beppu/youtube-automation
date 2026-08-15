import argparse

import pytest

from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.core.errors import AutomationError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--value", default="default")
    return parser


def test_run_cli_parses_explicit_argv_and_returns_operation_code():
    seen: list[str] = []

    exit_code = run_cli(_parser, lambda args: seen.append(args.value) or 7, ["--value", "chosen"])

    assert exit_code == 7
    assert seen == ["chosen"]


def test_run_cli_defaults_none_operation_result_to_zero():
    assert run_cli(_parser, lambda _args: None, []) == 0


def test_run_cli_redacts_automation_error_to_stderr(capsys):
    def fail(_args: argparse.Namespace) -> None:
        raise AutomationError("access_token=ya29.secret-value /Users/example/client_secret.json")

    assert run_cli(_parser, fail, []) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "❌ エラー: access_token=<redacted-token> <redacted-path>\n"


def test_run_cli_allows_error_exit_code_and_message_override(capsys):
    def fail(_args: argparse.Namespace) -> None:
        raise AutomationError("domain failure")

    assert run_cli(_parser, fail, [], failure_message="失敗", failure_exit_code=9) == 9
    assert capsys.readouterr().err == "❌ 失敗: domain failure\n"


def test_run_cli_preserves_configured_keyboard_interrupt_contract(capsys):
    def interrupt(_args: argparse.Namespace) -> None:
        raise KeyboardInterrupt

    assert run_cli(_parser, interrupt, [], interrupt_message="中断されました", interrupt_exit_code=130) == 130
    assert capsys.readouterr().out == "\n🛑 中断されました\n"


def test_run_cli_can_treat_keyboard_interrupt_as_success(capsys):
    def interrupt(_args: argparse.Namespace) -> None:
        raise KeyboardInterrupt

    assert run_cli(_parser, interrupt, [], interrupt_message="処理が中断されました", interrupt_exit_code=None) == 0
    assert capsys.readouterr().out == "\n🛑 処理が中断されました\n"


def test_run_cli_does_not_hide_unexpected_exceptions():
    def fail(_args: argparse.Namespace) -> None:
        raise RuntimeError("programming failure")

    with pytest.raises(RuntimeError, match="programming failure"):
        run_cli(_parser, fail, [])


def test_run_cli_parses_help_before_running_operation(capsys):
    called = False

    def run(_args: argparse.Namespace) -> None:
        nonlocal called
        called = True

    with pytest.raises(SystemExit) as exc_info:
        run_cli(_parser, run, ["--help"])

    assert exc_info.value.code == 0
    assert not called
    assert "usage:" in capsys.readouterr().out
