"""Vultr streaming VPS と Terraform GCS state の読み取り専用突合。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.parse import urlencode

from youtube_automation.core.errors import ConfigError, YouTubeAPIError

_VULTR_INSTANCES_ENDPOINT = "https://api.vultr.com/v2/instances"
_VULTR_PAGE_SIZE = 500
_VULTR_INSTANCES_URL = f"{_VULTR_INSTANCES_ENDPOINT}?{urlencode({'per_page': _VULTR_PAGE_SIZE})}"
_STREAMING_TAG = "youtube-stream"
_HTTP_TIMEOUT_SECONDS = 30
_COMMAND_TIMEOUT_SECONDS = 30
_GCLOUD_EMPTY_STATE_MESSAGES = ("matched no URLs", "One or more URLs matched no objects.")

CommandRunner = Callable[..., tuple[int, str, str]]


@dataclass(frozen=True)
class StreamingVpsInventory:
    actual_instance_ids: frozenset[str]
    managed_instance_ids: frozenset[str]

    @property
    def unmanaged_instance_ids(self) -> frozenset[str]:
        return self.actual_instance_ids - self.managed_instance_ids


def fetch_tagged_instance_ids(*, api_key: str) -> frozenset[str]:
    """Vultr API の streaming tag 付き instance ID を全 page から取得する。"""
    instance_ids: set[str] = set()
    url: str | None = _VULTR_INSTANCES_URL
    while url is not None:
        payload = _fetch_vultr_page(url=url, api_key=api_key)
        instances = payload.get("instances")
        if not isinstance(instances, list):
            raise _unexpected_vultr_shape("instances")
        for index, instance in enumerate(instances):
            instance_id, tags = _parse_vultr_instance(instance, index=index)
            if _STREAMING_TAG in tags:
                instance_ids.add(instance_id)
        url = _next_page_url(payload)
    return frozenset(instance_ids)


def _fetch_vultr_page(*, url: str, api_key: str) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_SECONDS) as response:
            payload: object = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise YouTubeAPIError(f"Vultr instances API request failed: {error}") from error
    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        raise _unexpected_vultr_shape("$")
    return cast(dict[str, object], payload)


def _parse_vultr_instance(instance: object, *, index: int) -> tuple[str, frozenset[str]]:
    field_path = f"instances[{index}]"
    if not isinstance(instance, dict):
        raise _unexpected_vultr_shape(field_path)
    instance_id = instance.get("id")
    tags = instance.get("tags")
    if not isinstance(instance_id, str) or not instance_id:
        raise _unexpected_vultr_shape(f"{field_path}.id")
    if not isinstance(tags, list):
        raise _unexpected_vultr_shape(f"{field_path}.tags")
    if not all(isinstance(tag, str) for tag in tags):
        raise _unexpected_vultr_shape(f"{field_path}.tags")
    return instance_id, frozenset(tags)


def _next_page_url(payload: dict[str, object]) -> str | None:
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        raise _unexpected_vultr_shape("meta")
    links = meta.get("links")
    if not isinstance(links, dict):
        raise _unexpected_vultr_shape("meta.links")
    next_cursor = links.get("next")
    if not isinstance(next_cursor, str):
        raise _unexpected_vultr_shape("meta.links.next")
    if next_cursor == "":
        return None
    query = urlencode({"per_page": _VULTR_PAGE_SIZE, "cursor": next_cursor})
    return f"{_VULTR_INSTANCES_ENDPOINT}?{query}"


def _unexpected_vultr_shape(field_path: str) -> YouTubeAPIError:
    return YouTubeAPIError(f"Vultr instances API field `{field_path}` has unexpected shape")


def load_managed_instance_ids(*, terraform_dir: Path, run_command: CommandRunner) -> frozenset[str]:
    """initialized GCS backend の全 workspace state から Vultr instance ID を読む。"""
    bucket, prefix = _load_gcs_backend(terraform_dir)
    state_root = f"gs://{bucket}/{prefix}"
    returncode, stdout, stderr = run_command(
        ["gcloud", "storage", "ls", f"{state_root}/*.tfstate"],
        _COMMAND_TIMEOUT_SECONDS,
        cwd=terraform_dir,
    )
    if returncode != 0:
        if any(message in stderr for message in _GCLOUD_EMPTY_STATE_MESSAGES):
            return frozenset()
        raise ConfigError(f"streaming Terraform state 一覧の取得に失敗: {stderr.strip() or returncode}")

    state_uris = [line.strip() for line in stdout.splitlines() if line.strip()]
    managed_ids: set[str] = set()
    for state_uri in state_uris:
        if not state_uri.startswith(f"{state_root}/") or not state_uri.endswith(".tfstate"):
            raise ConfigError(f"streaming Terraform state URI has unexpected shape: {state_uri!r}")
        managed_ids.update(_load_state_instance_ids(state_uri, terraform_dir, run_command))
    return frozenset(managed_ids)


def _load_gcs_backend(terraform_dir: Path) -> tuple[str, str]:
    metadata_path = terraform_dir / ".terraform" / "terraform.tfstate"
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        message = f"streaming backend metadata がありません: `{terraform_dir}` で terraform init を実行してください"
        raise ConfigError(message) from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ConfigError(f"streaming backend metadata を読み込めません: {error}") from error

    if not isinstance(payload, dict) or not isinstance(payload.get("backend"), dict):
        raise ConfigError("streaming backend metadata has unexpected shape")
    backend = payload["backend"]
    config = backend.get("config")
    if backend.get("type") != "gcs" or not isinstance(config, dict):
        raise ConfigError("streaming backend metadata has unexpected shape")
    bucket = config.get("bucket")
    prefix = config.get("prefix")
    if not isinstance(bucket, str) or not bucket or not isinstance(prefix, str) or not prefix:
        raise ConfigError("streaming GCS backend config has unexpected shape")
    return bucket.rstrip("/"), prefix.strip("/")


def _load_state_instance_ids(
    state_uri: str,
    terraform_dir: Path,
    run_command: CommandRunner,
) -> set[str]:
    returncode, stdout, stderr = run_command(
        ["gcloud", "storage", "cat", state_uri],
        _COMMAND_TIMEOUT_SECONDS,
        cwd=terraform_dir,
    )
    if returncode != 0:
        raise ConfigError(f"streaming Terraform state の取得に失敗 ({state_uri}): {stderr.strip() or returncode}")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise ConfigError(f"streaming Terraform state が不正 JSON ({state_uri}): {error}") from error
    return _parse_state_instance_ids(payload, state_uri)


def _parse_state_instance_ids(payload: object, state_uri: str) -> set[str]:
    if not isinstance(payload, dict) or not isinstance(payload.get("resources"), list):
        raise ConfigError(f"streaming Terraform state has unexpected shape ({state_uri})")
    instance_ids: set[str] = set()
    for resource in payload["resources"]:
        if not isinstance(resource, dict):
            raise ConfigError(f"streaming Terraform state has unexpected shape ({state_uri})")
        if resource.get("type") != "vultr_instance":
            continue
        instances = resource.get("instances")
        if not isinstance(instances, list):
            raise ConfigError(f"streaming Terraform state has unexpected shape ({state_uri})")
        for instance in instances:
            if not isinstance(instance, dict) or not isinstance(instance.get("attributes"), dict):
                raise ConfigError(f"streaming Terraform state has unexpected shape ({state_uri})")
            instance_id = instance["attributes"].get("id")
            if not isinstance(instance_id, str) or not instance_id:
                raise ConfigError(f"streaming Terraform state has unexpected shape ({state_uri})")
            instance_ids.add(instance_id)
    return instance_ids


def reconcile_streaming_vps(
    *,
    terraform_dir: Path,
    api_key: str,
    run_command: CommandRunner,
) -> StreamingVpsInventory:
    """Terraform 管理 ID と Vultr 実インスタンス ID を読み取り専用で突合する。"""
    managed_ids = load_managed_instance_ids(terraform_dir=terraform_dir, run_command=run_command)
    actual_ids = fetch_tagged_instance_ids(api_key=api_key)
    return StreamingVpsInventory(actual_instance_ids=actual_ids, managed_instance_ids=managed_ids)
