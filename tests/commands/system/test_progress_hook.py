from __future__ import annotations

import io
import json

import pytest

from youtube_automation.commands.system import progress_hook

EXPECTED_PROGRESS = """```
  ✓  企画
  ✓  音源生成
  ✓  マスター化
  ▸  動画化
  ○  サムネイル
  ○  アップロード
  ○  公開後処理
  ○  分析
```"""


def _run(payload: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    exit_code = progress_hook.main([], stdin=io.StringIO(payload))
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def test_should_emit_progress_system_message_when_background_bash_starts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"run_in_background": True}})

    exit_code, stdout, stderr = _run(payload, capsys)

    assert exit_code == 0
    assert json.loads(stdout) == {"systemMessage": EXPECTED_PROGRESS}
    assert stderr == ""


def test_should_emit_nothing_when_foreground_bash_starts(capsys: pytest.CaptureFixture[str]) -> None:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {}})

    exit_code, stdout, stderr = _run(payload, capsys)

    assert exit_code == 0
    assert stdout == ""
    assert stderr == ""


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        json.dumps({"tool_name": "Agent", "tool_input": {"run_in_background": True}}),
        json.dumps({"tool_name": "Bash", "tool_input": []}),
        json.dumps({"tool_name": "Bash", "tool_input": {"run_in_background": "true"}}),
    ],
)
def test_should_emit_nothing_when_payload_is_invalid_or_unsupported(
    payload: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code, stdout, stderr = _run(payload, capsys)

    assert exit_code == 0
    assert stdout == ""
    assert stderr == ""
