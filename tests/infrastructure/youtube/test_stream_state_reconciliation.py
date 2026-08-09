from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from youtube_automation.core.errors import ConfigError, YouTubeAPIError
from youtube_automation.infrastructure.youtube.streaming import state_reconciliation


class _Response:
    def __init__(self, payload: object) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False


def test_fetch_tagged_instances_filters_vultr_tags_and_paginates() -> None:
    first_page_instances = [{"id": f"managed-{index}", "tags": ["youtube-stream"]} for index in range(500)]
    untrusted_cursor = "https://attacker.example/collect?token=opaque value"
    pages = [
        _Response(
            {
                "instances": first_page_instances,
                "meta": {"links": {"next": untrusted_cursor}},
            }
        ),
        _Response(
            {
                "instances": [{"id": "unmanaged", "tags": ["youtube-stream", "prod"]}],
                "meta": {"links": {"next": ""}},
            }
        ),
    ]

    with patch(
        "youtube_automation.infrastructure.youtube.streaming.state_reconciliation.urllib.request.urlopen",
        side_effect=pages,
    ) as mock_open:
        result = state_reconciliation.fetch_tagged_instance_ids(api_key="secret")

    assert len(result) == 501
    assert "managed-499" in result
    assert "unmanaged" in result
    assert mock_open.call_count == 2
    assert all(call.args[0].get_header("Authorization") == "Bearer secret" for call in mock_open.call_args_list)
    assert mock_open.call_args_list[0].args[0].full_url == "https://api.vultr.com/v2/instances?per_page=500"
    assert mock_open.call_args_list[1].args[0].full_url == (
        "https://api.vultr.com/v2/instances?per_page=500&"
        "cursor=https%3A%2F%2Fattacker.example%2Fcollect%3Ftoken%3Dopaque+value"
    )


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"instances": {}},
        {"instances": [{"id": "vps", "tags": "youtube-stream"}]},
        {"instances": []},
        {"instances": [], "meta": None},
        {"instances": [], "meta": []},
        {"instances": [], "meta": {}},
        {"instances": [], "meta": {"links": []}},
        {"instances": [], "meta": {"links": {}}},
        {"instances": [], "meta": {"links": {"next": None}}},
        {"instances": [], "meta": {"links": {"next": 1}}},
    ],
)
def test_fetch_tagged_instances_rejects_unexpected_api_shapes(payload: object) -> None:
    with patch(
        "youtube_automation.infrastructure.youtube.streaming.state_reconciliation.urllib.request.urlopen",
        return_value=_Response(payload),
    ):
        with pytest.raises(YouTubeAPIError, match="unexpected shape"):
            state_reconciliation.fetch_tagged_instance_ids(api_key="secret")


@pytest.mark.parametrize(
    ("payload", "field_path"),
    [
        ({"instances": {"default_password": "do-not-leak"}}, "instances"),
        (
            {
                "instances": [{"id": "vps", "tags": 1, "default_password": "do-not-leak"}],
                "meta": {"links": {"next": ""}},
            },
            "instances[0].tags",
        ),
    ],
)
def test_fetch_tagged_instances_does_not_expose_response_secrets(payload: object, field_path: str) -> None:
    with patch(
        "youtube_automation.infrastructure.youtube.streaming.state_reconciliation.urllib.request.urlopen",
        return_value=_Response(payload),
    ):
        with pytest.raises(YouTubeAPIError) as exc_info:
            state_reconciliation.fetch_tagged_instance_ids(api_key="secret")

    assert field_path in str(exc_info.value)
    assert "do-not-leak" not in str(exc_info.value)


def test_load_managed_ids_reads_every_gcs_workspace_state(tmp_path) -> None:
    terraform_dir = tmp_path / "streaming"
    metadata = terraform_dir / ".terraform" / "terraform.tfstate"
    metadata.parent.mkdir(parents=True)
    metadata.write_text(
        json.dumps({"backend": {"type": "gcs", "config": {"bucket": "state-bucket", "prefix": "streaming"}}}),
        encoding="utf-8",
    )
    commands: list[list[str]] = []

    def run_command(cmd: list[str], _timeout: int, *, cwd=None) -> tuple[int, str, str]:
        commands.append(cmd)
        if cmd[:3] == ["gcloud", "storage", "ls"]:
            return 0, "gs://state-bucket/streaming/a.tfstate\ngs://state-bucket/streaming/b.tfstate\n", ""
        instance_id = "a-id" if cmd[-1].endswith("a.tfstate") else "b-id"
        state = {
            "resources": [
                {"type": "vultr_instance", "instances": [{"attributes": {"id": instance_id}}]},
                {"type": "local_file", "instances": [{"attributes": {"id": "ignored"}}]},
            ]
        }
        return 0, json.dumps(state), ""

    result = state_reconciliation.load_managed_instance_ids(
        terraform_dir=terraform_dir,
        run_command=run_command,
    )

    assert result == frozenset({"a-id", "b-id"})
    assert commands[0] == ["gcloud", "storage", "ls", "gs://state-bucket/streaming/*.tfstate"]


def test_load_managed_ids_fails_when_backend_metadata_is_missing(tmp_path) -> None:
    with pytest.raises(ConfigError, match="terraform init"):
        state_reconciliation.load_managed_instance_ids(
            terraform_dir=tmp_path,
            run_command=lambda *_args, **_kwargs: (0, "", ""),
        )


@pytest.mark.parametrize(
    "stderr",
    ["CommandException: matched no URLs", "One or more URLs matched no objects."],
)
def test_load_managed_ids_treats_gcloud_empty_listing_as_empty(tmp_path, stderr: str) -> None:
    metadata = tmp_path / ".terraform" / "terraform.tfstate"
    metadata.parent.mkdir()
    metadata.write_text(
        json.dumps({"backend": {"type": "gcs", "config": {"bucket": "bucket", "prefix": "streaming"}}}),
        encoding="utf-8",
    )

    result = state_reconciliation.load_managed_instance_ids(
        terraform_dir=tmp_path,
        run_command=lambda *_args, **_kwargs: (1, "", stderr),
    )

    assert result == frozenset()


def test_load_managed_ids_rejects_malformed_state_instead_of_ignoring_it(tmp_path) -> None:
    metadata = tmp_path / ".terraform" / "terraform.tfstate"
    metadata.parent.mkdir()
    metadata.write_text(
        json.dumps({"backend": {"type": "gcs", "config": {"bucket": "bucket", "prefix": "streaming"}}}),
        encoding="utf-8",
    )

    def run_command(cmd: list[str], _timeout: int, *, cwd=None) -> tuple[int, str, str]:
        if cmd[2] == "ls":
            return 0, "gs://bucket/streaming/default.tfstate\n", ""
        return 0, json.dumps({"resources": {}}), ""

    with pytest.raises(ConfigError, match="unexpected shape"):
        state_reconciliation.load_managed_instance_ids(terraform_dir=tmp_path, run_command=run_command)
