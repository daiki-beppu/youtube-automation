"""ローカライゼーション設定の責務別 dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Localizations:
    """`localizations.json`（`config/` 直下、`config/channel/` の外）の内容.

    - `exists=True` 時: `data` には JSON 全量、`supported_languages` / `default_language` も埋める
    - `exists=False` 時: `data={}`、`supported_languages=[youtube.api.language]`、`default_language=""`
    """

    data: dict = field(default_factory=dict)
    exists: bool = False
    supported_languages: list[str] = field(default_factory=list)
    default_language: str = ""
