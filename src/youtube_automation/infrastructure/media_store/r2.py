"""Cloudflare R2 の S3-compatible MediaStore adapter。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol, cast

from youtube_automation.core.errors import ConfigError, MediaStoreError
from youtube_automation.domains.media_store import MediaKey, MediaObjectMetadata
from youtube_automation.infrastructure.auth.redaction import redact_sensitive_data
from youtube_automation.infrastructure.file_lock import file_lock
from youtube_automation.infrastructure.media_store._files import (
    atomic_destination,
    reject_symlink_components,
    require_regular_source,
    sha256_file,
)
from youtube_automation.infrastructure.secrets import get_secret

_BUCKET_RE = re.compile(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]\Z")
_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")
_PREFIX_SEGMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_DEFAULT_MULTIPART_CHUNK_SIZE = 100 * 1024 * 1024
_MINIMUM_MULTIPART_PART_SIZE = 5 * 1024 * 1024
_MAXIMUM_MULTIPART_PARTS = 10_000
_MULTIPART_STATE_DIRECTORY = ".yt-r2-multipart"
_MULTIPART_CHECKPOINT_VERSION = 1


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

    def create_multipart_upload(self, *, Bucket: str, Key: str, Metadata: dict[str, str]) -> dict[str, object]: ...

    def upload_part(
        self,
        *,
        Bucket: str,
        Key: str,
        PartNumber: int,
        UploadId: str,
        Body: bytes,
    ) -> dict[str, object]: ...

    def list_parts(
        self,
        *,
        Bucket: str,
        Key: str,
        UploadId: str,
        PartNumberMarker: int | None = None,
    ) -> dict[str, object]: ...

    def complete_multipart_upload(
        self,
        *,
        Bucket: str,
        Key: str,
        UploadId: str,
        MultipartUpload: dict[str, object],
    ) -> dict[str, object]: ...

    def abort_multipart_upload(self, *, Bucket: str, Key: str, UploadId: str) -> None: ...

    def list_objects_v2(
        self,
        *,
        Bucket: str,
        Prefix: str,
        ContinuationToken: str | None = None,
    ) -> dict[str, object]: ...


@dataclass(frozen=True)
class MultipartTransferConfig:
    """R2 multipart の固定境界。test は R2 最小 part size まで縮小できる。"""

    threshold: int = _DEFAULT_MULTIPART_CHUNK_SIZE
    part_size: int = _DEFAULT_MULTIPART_CHUNK_SIZE

    def __post_init__(self) -> None:
        if self.threshold < _MINIMUM_MULTIPART_PART_SIZE:
            raise ConfigError("R2 multipart threshold は 5 MiB 以上にしてください")
        if self.part_size < _MINIMUM_MULTIPART_PART_SIZE:
            raise ConfigError("R2 multipart part_size は 5 MiB 以上にしてください")


@dataclass(frozen=True)
class _MultipartCheckpoint:
    bucket: str
    object_key: str
    source_size: int
    source_sha256: str
    part_size: int
    upload_id: str

    def matches(self, *, bucket: str, object_key: str, source_size: int, source_sha256: str, part_size: int) -> bool:
        return (
            self.bucket == bucket
            and self.object_key == object_key
            and self.source_size == source_size
            and self.source_sha256 == source_sha256
            and self.part_size == part_size
        )


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
        multipart_transfer_config: MultipartTransferConfig | None = None,
    ) -> None:
        self._config = config
        self._multipart_transfer_config = multipart_transfer_config or MultipartTransferConfig()
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
            existing = self.metadata(key)
            if existing is not None and existing.size == size and existing.sha256 == checksum:
                if size >= self._multipart_transfer_config.threshold:
                    checkpoint_path = self._checkpoint_path(source, object_key)
                    with file_lock(checkpoint_path):
                        checkpoint_path.unlink(missing_ok=True)
                return existing
            if size >= self._multipart_transfer_config.threshold:
                self._push_multipart(source, object_key, size=size, checksum=checksum)
            else:
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

    def _push_multipart(self, source: Path, object_key: str, *, size: int, checksum: str) -> None:
        part_size = self._multipart_transfer_config.part_size
        part_count = (size + part_size - 1) // part_size
        if part_count > _MAXIMUM_MULTIPART_PARTS:
            raise MediaStoreError(f"R2 multipart part 数が上限 {_MAXIMUM_MULTIPART_PARTS} を超えます")
        checkpoint_path = self._checkpoint_path(source, object_key)
        with file_lock(checkpoint_path):
            if self._remote_object_matches(object_key, size=size, checksum=checksum):
                checkpoint_path.unlink(missing_ok=True)
                return
            checkpoint = self._load_checkpoint(checkpoint_path)
            if checkpoint is not None and (
                checkpoint.bucket != self._config.bucket or checkpoint.object_key != object_key
            ):
                raise MediaStoreError("R2 multipart checkpoint の bucket / key 境界が不正です")
            if checkpoint is not None and not checkpoint.matches(
                bucket=self._config.bucket,
                object_key=object_key,
                source_size=size,
                source_sha256=checksum,
                part_size=part_size,
            ):
                self._client.abort_multipart_upload(
                    Bucket=checkpoint.bucket,
                    Key=checkpoint.object_key,
                    UploadId=checkpoint.upload_id,
                )
                checkpoint_path.unlink(missing_ok=True)
                checkpoint = None
            if checkpoint is None:
                checkpoint = self._create_multipart_checkpoint(
                    checkpoint_path,
                    object_key=object_key,
                    size=size,
                    checksum=checksum,
                    part_size=part_size,
                )
            try:
                completed = self._list_completed_parts(checkpoint, size=size)
            except Exception as exc:
                if _status_code(exc) != 404:
                    raise
                checkpoint_path.unlink(missing_ok=True)
                checkpoint = self._create_multipart_checkpoint(
                    checkpoint_path,
                    object_key=object_key,
                    size=size,
                    checksum=checksum,
                    part_size=part_size,
                )
                completed = {}
            parts = self._upload_missing_parts(source, checkpoint, completed, part_count=part_count)
            self._client.complete_multipart_upload(
                Bucket=self._config.bucket,
                Key=object_key,
                UploadId=checkpoint.upload_id,
                MultipartUpload={"Parts": parts},
            )
            checkpoint_path.unlink(missing_ok=True)

    def _remote_object_matches(self, object_key: str, *, size: int, checksum: str) -> bool:
        try:
            response = self._client.head_object(Bucket=self._config.bucket, Key=object_key)
        except Exception as exc:
            if _status_code(exc) == 404:
                return False
            raise
        metadata = response.get("Metadata")
        return (
            response.get("ContentLength") == size and isinstance(metadata, dict) and metadata.get("sha256") == checksum
        )

    def _checkpoint_path(self, source: Path, object_key: str) -> Path:
        state_directory = source.parent / _MULTIPART_STATE_DIRECTORY
        reject_symlink_components(state_directory)
        state_directory.mkdir(mode=0o700, exist_ok=True)
        reject_symlink_components(state_directory)
        identifier = hashlib.sha256(f"{self._config.bucket}\0{object_key}".encode()).hexdigest()
        return state_directory / f"{identifier}.json"

    def _load_checkpoint(self, path: Path) -> _MultipartCheckpoint | None:
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
            raise MediaStoreError("R2 multipart checkpoint が通常ファイルではありません")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("version") != _MULTIPART_CHECKPOINT_VERSION:
                raise ValueError("unsupported version")
            checkpoint = _MultipartCheckpoint(
                bucket=payload["bucket"],
                object_key=payload["object_key"],
                source_size=payload["source_size"],
                source_sha256=payload["source_sha256"],
                part_size=payload["part_size"],
                upload_id=payload["upload_id"],
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MediaStoreError("R2 multipart checkpoint が不正です") from exc
        if (
            not isinstance(checkpoint.bucket, str)
            or not isinstance(checkpoint.object_key, str)
            or not isinstance(checkpoint.source_size, int)
            or checkpoint.source_size < 0
            or not isinstance(checkpoint.source_sha256, str)
            or not _SHA256_RE.fullmatch(checkpoint.source_sha256)
            or not isinstance(checkpoint.part_size, int)
            or checkpoint.part_size < _MINIMUM_MULTIPART_PART_SIZE
            or not isinstance(checkpoint.upload_id, str)
            or not checkpoint.upload_id
        ):
            raise MediaStoreError("R2 multipart checkpoint が不正です")
        return checkpoint

    def _create_multipart_checkpoint(
        self,
        path: Path,
        *,
        object_key: str,
        size: int,
        checksum: str,
        part_size: int,
    ) -> _MultipartCheckpoint:
        response = self._client.create_multipart_upload(
            Bucket=self._config.bucket,
            Key=object_key,
            Metadata={"sha256": checksum},
        )
        upload_id = response.get("UploadId")
        if not isinstance(upload_id, str) or not upload_id:
            raise MediaStoreError("R2 multipart upload ID が不正です")
        checkpoint = _MultipartCheckpoint(
            bucket=self._config.bucket,
            object_key=object_key,
            source_size=size,
            source_sha256=checksum,
            part_size=part_size,
            upload_id=upload_id,
        )
        try:
            self._write_checkpoint(path, checkpoint)
        except Exception:
            self._client.abort_multipart_upload(Bucket=self._config.bucket, Key=object_key, UploadId=upload_id)
            raise
        return checkpoint

    @staticmethod
    def _write_checkpoint(path: Path, checkpoint: _MultipartCheckpoint) -> None:
        payload = {
            "version": _MULTIPART_CHECKPOINT_VERSION,
            "bucket": checkpoint.bucket,
            "object_key": checkpoint.object_key,
            "source_size": checkpoint.source_size,
            "source_sha256": checkpoint.source_sha256,
            "part_size": checkpoint.part_size,
            "upload_id": checkpoint.upload_id,
        }
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as file_object:
                json.dump(payload, file_object, sort_keys=True)
                file_object.flush()
                os.fsync(file_object.fileno())
            reject_symlink_components(path)
            os.replace(temporary, path)
        except Exception:
            with suppress(OSError):
                os.close(descriptor)
            temporary.unlink(missing_ok=True)
            raise

    def _list_completed_parts(self, checkpoint: _MultipartCheckpoint, *, size: int) -> dict[int, str]:
        completed: dict[int, str] = {}
        marker: int | None = None
        while True:
            if marker is None:
                response = self._client.list_parts(
                    Bucket=checkpoint.bucket,
                    Key=checkpoint.object_key,
                    UploadId=checkpoint.upload_id,
                )
            else:
                response = self._client.list_parts(
                    Bucket=checkpoint.bucket,
                    Key=checkpoint.object_key,
                    UploadId=checkpoint.upload_id,
                    PartNumberMarker=marker,
                )
            raw_parts = response.get("Parts", [])
            if not isinstance(raw_parts, list):
                raise MediaStoreError("R2 multipart parts 応答が不正です")
            for raw_part in raw_parts:
                if not isinstance(raw_part, dict):
                    raise MediaStoreError("R2 multipart part 応答が不正です")
                number = raw_part.get("PartNumber")
                etag = raw_part.get("ETag")
                part_bytes = raw_part.get("Size")
                if not isinstance(number, int) or not isinstance(etag, str) or not isinstance(part_bytes, int):
                    raise MediaStoreError("R2 multipart part 応答が不正です")
                expected_size = min(checkpoint.part_size, size - (number - 1) * checkpoint.part_size)
                if number < 1 or expected_size <= 0:
                    raise MediaStoreError("R2 multipart part 番号が不正です")
                if part_bytes == expected_size:
                    completed[number] = etag
            if response.get("IsTruncated") is not True:
                return completed
            next_marker = response.get("NextPartNumberMarker")
            if not isinstance(next_marker, int) or next_marker <= (marker or 0):
                raise MediaStoreError("R2 multipart pagination が不正です")
            marker = next_marker

    def _upload_missing_parts(
        self,
        source: Path,
        checkpoint: _MultipartCheckpoint,
        completed: dict[int, str],
        *,
        part_count: int,
    ) -> list[dict[str, object]]:
        parts: list[dict[str, object]] = []
        with source.open("rb") as file_object:
            for number in range(1, part_count + 1):
                body = file_object.read(checkpoint.part_size)
                etag = completed.get(number)
                if etag is None:
                    response = self._client.upload_part(
                        Bucket=checkpoint.bucket,
                        Key=checkpoint.object_key,
                        PartNumber=number,
                        UploadId=checkpoint.upload_id,
                        Body=body,
                    )
                    etag = response.get("ETag")
                    if not isinstance(etag, str) or not etag:
                        raise MediaStoreError("R2 multipart ETag が不正です")
                parts.append({"PartNumber": number, "ETag": etag})
        return parts

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

    def retained_bytes(self) -> int:
        prefix = f"{self._config.prefix}/" if self._config.prefix else ""
        total = 0
        continuation: str | None = None
        try:
            while True:
                if continuation is None:
                    response = self._client.list_objects_v2(Bucket=self._config.bucket, Prefix=prefix)
                else:
                    response = self._client.list_objects_v2(
                        Bucket=self._config.bucket,
                        Prefix=prefix,
                        ContinuationToken=continuation,
                    )
                contents = response.get("Contents", [])
                if not isinstance(contents, list):
                    raise MediaStoreError("R2 retained capacity 応答が不正です")
                for item in contents:
                    if not isinstance(item, dict):
                        raise MediaStoreError("R2 retained capacity object が不正です")
                    key = item.get("Key")
                    size = item.get("Size")
                    if (
                        not isinstance(key, str)
                        or not key.startswith(prefix)
                        or not isinstance(size, int)
                        or isinstance(size, bool)
                        or size < 0
                    ):
                        raise MediaStoreError("R2 retained capacity object が不正です")
                    total += size
                if response.get("IsTruncated") is not True:
                    return total
                next_continuation = response.get("NextContinuationToken")
                if not isinstance(next_continuation, str) or not next_continuation or next_continuation == continuation:
                    raise MediaStoreError("R2 retained capacity pagination が不正です")
                continuation = next_continuation
        except MediaStoreError:
            raise
        except Exception as exc:
            raise self._error("retained capacity", exc) from exc
