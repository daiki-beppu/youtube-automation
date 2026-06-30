"""Suno artifact route contract tests."""

from __future__ import annotations

from youtube_automation.utils.suno_artifact_contracts import collection_downloaded_route


def test_collection_downloaded_route_encodes_collection_id_path_segment():
    """Given スペース入り collection id
    When downloaded route を組み立てる
    Then collection id を path segment encode する。
    """
    assert (
        collection_downloaded_route("20260601-clm-rainy jazz-collection")
        == "/collections/20260601-clm-rainy%20jazz-collection/downloaded"
    )
