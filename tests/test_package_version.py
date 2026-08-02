"""Package metadata から解決する公開 version 契約のテスト。"""

from __future__ import annotations

import importlib.metadata
import runpy
from unittest.mock import patch

from tests.helpers.paths import REPO_ROOT

PACKAGE_INIT = REPO_ROOT / "src" / "youtube_automation" / "__init__.py"


def test_version_uses_installed_package_metadata() -> None:
    with patch.object(importlib.metadata, "version", return_value="9.8.7") as version:
        namespace = runpy.run_path(str(PACKAGE_INIT))

    assert namespace["__version__"] == "9.8.7"
    version.assert_called_once_with("youtube-channels-automation")


def test_version_falls_back_when_package_metadata_is_unavailable() -> None:
    with patch.object(
        importlib.metadata,
        "version",
        side_effect=importlib.metadata.PackageNotFoundError("youtube-channels-automation"),
    ):
        namespace = runpy.run_path(str(PACKAGE_INIT))

    assert namespace["__version__"] == "0.0.0+unknown"
