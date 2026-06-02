"""`extensions/suno-helper/manifest.json` の最小権限契約を検証する。

issue #692 のレビューで、未使用の `"tabs"` permission が最小権限違反として
検出された (family_tag: least-privilege)。`chrome.tabs.query` が返す `tab.id` や
`chrome.tabs.sendMessage` は `"tabs"` 権限なしで動作し（特権プロパティ
`url`/`title`/`favIconUrl`/`pendingUrl` を参照しないため）、messaging は
`host_permissions` + `activeTab` で成立する。

manifest の権限宣言はコード由来テストの対象外で、不要権限が混入しても
他テストが pass してしまうため、権限契約をこのテストで機械的に担保し再発を防ぐ。
"""

from __future__ import annotations

import json
from pathlib import Path

# リポジトリルート (tests/ の親)
_REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = _REPO_ROOT / "extensions" / "suno-helper" / "manifest.json"

# 拡張が実際に使う最小権限。chrome.storage.local + activeTab のみ。
EXPECTED_PERMISSIONS = {"storage", "activeTab"}
# 最小権限違反となる、未使用かつ過剰な権限。
FORBIDDEN_PERMISSIONS = {"tabs"}


def _load() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_exists() -> None:
    """Given リポジトリ
    When suno-helper manifest.json を探す
    Then ファイルが存在する。
    """
    assert MANIFEST.exists(), f"{MANIFEST} が存在しません"


def test_manifest_is_v3() -> None:
    """Given manifest.json
    When manifest_version を読む
    Then Manifest V3 である。
    """
    assert _load()["manifest_version"] == 3


def test_manifest_permissions_are_least_privilege() -> None:
    """Given manifest.json
    When permissions を読む
    Then 実使用する最小権限のみで、未使用の `tabs` 等を含まない。
    """
    permissions = set(_load()["permissions"])
    assert permissions == EXPECTED_PERMISSIONS, (
        f"permissions が最小権限と一致しない: {sorted(permissions)} "
        f"(期待: {sorted(EXPECTED_PERMISSIONS)})"
    )


def test_manifest_has_no_forbidden_permissions() -> None:
    """Given manifest.json
    When permissions を読む
    Then 未使用の過剰権限（`tabs`）を宣言していない。
    """
    permissions = set(_load()["permissions"])
    leaked = permissions & FORBIDDEN_PERMISSIONS
    assert not leaked, f"未使用の過剰権限が宣言されている: {sorted(leaked)}"
