from __future__ import annotations

import subprocess
import sys

from tests.helpers.paths import REPO_ROOT

_RUNNER = REPO_ROOT / ".claude/skills/wf-new/references/validate_persona_chain.py"


def test_cli_requires_both_document_paths() -> None:
    result = subprocess.run(
        [sys.executable, str(_RUNNER)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "--persona-json" in result.stderr
    assert "--scene-json" in result.stderr
