from __future__ import annotations

import json
import subprocess
import sys

import pytest

from tests.helpers.paths import REPO_ROOT

_SCRIPT = REPO_ROOT / ".claude" / "skills" / "automation" / "references" / "guard_secret_edit.py"


# Claude Code Desktop が渡しうる BOM 付き / BOM なしの UTF-8・UTF-16・UTF-32 を網羅する。
@pytest.mark.parametrize(
    "encoding",
    ["utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "utf-32", "utf-32-le", "utf-32-be"],
)
def test_guard_accepts_non_secret_edit_payload_with_non_utf8_encoding(encoding: str) -> None:
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Edit",
        "tool_input": {"file_path": "C:/tmp/x.py"},
    }

    completed = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        input=json.dumps(payload).encode(encoding),
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
