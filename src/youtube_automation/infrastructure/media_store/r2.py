"""Cloudflare R2 の S3-compatible MediaStore adapter。"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol, cast

from youtube_automation.core.errors import ConfigError, MediaStoreError
from youtube_automation.domains.media_store import MediaKey, MediaObjectMetadata
from youtube_automation.infrastructure.auth.redaction import redact_sensitive_data
from youtube_automation.infrastructure.media_store._files import atomic_destination, require_regular_source, sha256_file
from youtube_automation.infrastructure.secrets import get_secret

_BUCKET_RE = re.compile(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]\Z")
_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")
_PREFIX_SEGMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_DEFAULT_MULTIPART_CHUNK_SIZE = 100 * 1024 * 1024


class _S3Client(Protocol):
    def upload_fileobj(
        self,
        file_object: BinaryIO,
        bucket: str,
        key: str,
        *,
        ExtraArgs: dict[str, object],
        Config: object,
    ) -> None: ...

    def download_fileobj(
        self,
        bucket: str,
        key: str,
        file_object: BinaryIO,
        *,
        Config: object,
    ) -> None: ...

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]: ...


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"R2 MediaStore の設定 {name} がありません")
    return value


def _validate_prefix(prefix: str) -> None:
    if not prefix:
        return
    if prefix.startswith("/") or prefix.endswith("/"):
        raise ConfigError("R2 MediaStore の prefix は相対 path かつ末尾 slash なしで指定してください")
    if any(not _PREFIX_SEGMENT_RE.fullmatch(segment) or segment in {".", ".."} for segment in prefix.split("/")):
        raise ConfigError("R2 MediaStore の prefix に境界外 path は指定できません")


@dataclass(frozen=True)
class R2MediaStoreConfig:
    """R2 接続情報。token は既存 secret owner からだけ取得する。"""

    account_id: str
    access_key_id: str
    api_token: str
    bucket: str
    prefix: str = ""

    def __post_init__(self) -> None:
        for field in ("account_id", "access_key_id"):
            if not _IDENTIFIER_RE.fullmatch(getattr(self, field)):
                raise ConfigError(f"R2 MediaStore の {field} が不正です")
        if not self.api_token.strip():
            raise ConfigError("R2 MediaStore の api_token は空にできません")
        if not _BUCKET_RE.fullmatch(self.bucket) or ".." in self.bucket:
            raise ConfigError("R2 MediaStore の bucket が不正です")
        _validate_prefix(self.prefix)

    @classmethod
    def from_environment(cls) -> R2MediaStoreConfig:
        return cls(
            account_id=_required_environment("R2_ACCOUNT_ID"),
            access_key_id=_required_environment("R2_ACCESS_KEY_ID"),
            api_token=get_secret("R2_API_TOKEN"),
            bucket=_required_environment("R2_BUCKET"),
            prefix=os.environ.get("R2_PREFIX", "").strip(),
        )

    @property
    def endpoint_url(self) -> str:
        return f"https://{self.account_id}.r2.cloudflarestorage.com"

    @property
    def secret_access_key(self) -> str:
        return hashlib.sha256(self.api_token.encode("utf-8")).hexdigest()


def _build_client(config: R2MediaStoreConfig) -> tuple[_S3Client, object]:
    import boto3
    from boto3.s3.transfer import TransferConfig
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=config.endpoint_url,
        aws_access_key_id=config.access_key_id,
        aws_secret_access_key=config.secret_access_key,
        region_name="auto",
        config=Config(
            signature_version="s3v4",
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )
    transfer = TransferConfig(
        multipart_threshold=_DEFAULT_MULTIPART_CHUNK_SIZE,
        multipart_chunksize=_DEFAULT_MULTIPART_CHUNK_SIZE,
    )
    return cast(_S3Client, client), transfer


def _status_code(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return None
    metadata = response.get("ResponseMetadata")
    if not isinstance(metadata, dict):
        return None
    status = metadata.get("HTTPStatusCode")
    return status if isinstance(status, int) else None


class R2MediaStore:
    """bucket / prefix 境界を constructor で固定した R2 adapter。"""

    def __init__(
        self,
        config: R2MediaStoreConfig,
        *,
        client: _S3Client | None = None,
        transfer_config: object | None = None,
    ) -> None:
        self._config = config
        if client is None or transfer_config is None:
            built_client, built_transfer = _build_client(config)
            self._client = client or built_client
            self._transfer_config = transfer_config or built_transfer
        else:
            self._client = client
            self._transfer_config = transfer_config

    def _object_key(self, key: MediaKey) -> str:
        parts = (self._config.prefix, key.as_posix()) if self._config.prefix else (key.as_posix(),)
        return "/".join(parts)

    def _error(self, operation: str, exc: Exception) -> MediaStoreError:
        message = redact_sensitive_data(str(exc))
        for secret in (self._config.api_token, self._config.access_key_id, self._config.secret_access_key):
            message = message.replace(secret, "<redacted-token>")
        return MediaStoreError(f"R2 MediaStore {operation} に失敗しました: {message}")

    def push(self, source: Path, key: MediaKey) -> MediaObjectMetadata:
        require_regular_source(source)
        size, checksum = sha256_file(source)
        object_key = self._object_key(key)
        try:
            with source.open("rb") as file_object:
                self._client.upload_fileobj(
                    file_object,
                    self._config.bucket,
                    object_key,
                    ExtraArgs={"Metadata": {"sha256": checksum}},
                    Config=self._transfer_config,
                )
            remote = self.metadata(key)
        except Exception as exc:
            raise self._error("push", exc) from exc
        if remote is None or remote.size != size or remote.sha256 != checksum:
            raise MediaStoreError(f"R2 MediaStore push 後の完全性検証に失敗しました: {key.as_posix()}")
        return remote

    def pull(self, key: MediaKey, destination: Path) -> MediaObjectMetadata:
        remote = self.metadata(key)
        if remote is None:
            raise MediaStoreError(f"R2 MediaStore object が見つかりません: {key.as_posix()}")
        try:
            with atomic_destination(destination) as temporary:
                with temporary.open("wb") as file_object:
                    self._client.download_fileobj(
                        self._config.bucket,
                        self._object_key(key),
                        file_object,
                        Config=self._transfer_config,
                    )
                size, checksum = sha256_file(temporary)
                if size != remote.size or checksum != remote.sha256:
                    raise MediaStoreError(f"R2 MediaStore pull の checksum 検証に失敗しました: {key.as_posix()}")
        except MediaStoreError:
            raise
        except Exception as exc:
            raise self._error("pull", exc) from exc
        return remote

    def exists(self, key: MediaKey) -> bool:
        return self.metadata(key) is not None

    def metadata(self, key: MediaKey) -> MediaObjectMetadata | None:
        try:
            response = self._client.head_object(Bucket=self._config.bucket, Key=self._object_key(key))
        except Exception as exc:
            if _status_code(exc) == 404:
                return None
            raise self._error("metadata", exc) from exc
        size = response.get("ContentLength")
        raw_metadata = response.get("Metadata")
        etag = response.get("ETag")
        checksum = raw_metadata.get("sha256") if isinstance(raw_metadata, dict) else None
        if not isinstance(size, int) or size < 0 or not isinstance(checksum, str) or not _SHA256_RE.fullmatch(checksum):
            raise MediaStoreError(f"R2 MediaStore metadata が不正です: {key.as_posix()}")
        return MediaObjectMetadata(
            size=size,
            sha256=checksum,
            etag=etag.strip('"') if isinstance(etag, str) else None,
        )
