from __future__ import annotations

import hashlib
import io
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from youtube_automation.core.errors import ConfigError, MediaStoreError
from youtube_automation.domains.media_store import MediaKey
from youtube_automation.infrastructure.media_store.r2 import MultipartTransferConfig, R2MediaStore, R2MediaStoreConfig


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, dict[str, str]]] = {}
        self.multipart_uploads: dict[str, dict[str, object]] = {}
        self.create_calls = 0
        self.uploaded_parts: list[int] = []
        self.interrupt_part: int | None = None

    def upload_fileobj(
        self,
        file_object: io.BufferedReader,
        bucket: str,
        key: str,
        *,
        ExtraArgs: dict[str, object],
        Config: object,
    ) -> None:
        del Config
        metadata = ExtraArgs["Metadata"]
        assert isinstance(metadata, dict)
        self.objects[(bucket, key)] = (file_object.read(), metadata)

    def download_fileobj(
        self,
        bucket: str,
        key: str,
        file_object: io.BufferedWriter,
        *,
        Config: object,
    ) -> None:
        del Config
        file_object.write(self.objects[(bucket, key)][0])

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        try:
            payload, metadata = self.objects[(Bucket, Key)]
        except KeyError as exc:
            raise FakeClientError(404, "missing") from exc
        return {"ContentLength": len(payload), "Metadata": metadata, "ETag": '"fixture-etag"'}

    def create_multipart_upload(self, *, Bucket: str, Key: str, Metadata: dict[str, str]) -> dict[str, object]:
        self.create_calls += 1
        upload_id = f"upload-{self.create_calls}"
        self.multipart_uploads[upload_id] = {
            "bucket": Bucket,
            "key": Key,
            "metadata": Metadata,
            "parts": {},
        }
        return {"UploadId": upload_id}

    def upload_part(
        self,
        *,
        Bucket: str,
        Key: str,
        PartNumber: int,
        UploadId: str,
        Body: bytes,
    ) -> dict[str, object]:
        upload = self.multipart_uploads[UploadId]
        assert upload["bucket"] == Bucket
        assert upload["key"] == Key
        if self.interrupt_part == PartNumber:
            self.interrupt_part = None
            raise RuntimeError("connection interrupted")
        parts = upload["parts"]
        assert isinstance(parts, dict)
        parts[PartNumber] = Body
        self.uploaded_parts.append(PartNumber)
        return {"ETag": f'"etag-{PartNumber}"'}

    def list_parts(
        self,
        *,
        Bucket: str,
        Key: str,
        UploadId: str,
        PartNumberMarker: int | None = None,
    ) -> dict[str, object]:
        del PartNumberMarker
        try:
            upload = self.multipart_uploads[UploadId]
        except KeyError as exc:
            raise FakeClientError(404, "NoSuchUpload") from exc
        assert upload["bucket"] == Bucket
        assert upload["key"] == Key
        parts = upload["parts"]
        assert isinstance(parts, dict)
        return {
            "Parts": [
                {"PartNumber": part_number, "ETag": f'"etag-{part_number}"', "Size": len(payload)}
                for part_number, payload in sorted(parts.items())
            ],
            "IsTruncated": False,
        }

    def complete_multipart_upload(
        self,
        *,
        Bucket: str,
        Key: str,
        UploadId: str,
        MultipartUpload: dict[str, object],
    ) -> dict[str, object]:
        upload = self.multipart_uploads.pop(UploadId)
        assert upload["bucket"] == Bucket
        assert upload["key"] == Key
        parts = upload["parts"]
        metadata = upload["metadata"]
        assert isinstance(parts, dict)
        assert isinstance(metadata, dict)
        requested = MultipartUpload["Parts"]
        assert isinstance(requested, list)
        payload = b"".join(parts[part["PartNumber"]] for part in requested)
        self.objects[(Bucket, Key)] = (payload, metadata)
        return {"ETag": '"completed-etag"'}

    def abort_multipart_upload(self, *, Bucket: str, Key: str, UploadId: str) -> None:
        del Bucket, Key
        self.multipart_uploads.pop(UploadId, None)


class FakeClientError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.response = {"ResponseMetadata": {"HTTPStatusCode": status}}


def _config() -> R2MediaStoreConfig:
    return R2MediaStoreConfig(
        account_id="account-id",
        access_key_id="access-key-id",
        api_token="api-token-value",
        bucket="media-handoffs",
        prefix="automation/v1",
    )


def _key() -> MediaKey:
    return MediaKey("ambient-lab", "rain-night", "video-upload", "Master.mp4")


def test_r2_push_pull_round_trip_uses_scoped_bucket_and_prefix(tmp_path: Path) -> None:
    client = FakeS3Client()
    store = R2MediaStore(_config(), client=client, transfer_config=object())
    payload = b"r2-streaming-payload" * 8192
    source = tmp_path / "Master.mp4"
    source.write_bytes(payload)

    pushed = store.push(source, _key())
    destination = tmp_path / "download" / "Master.mp4"
    pulled = store.pull(_key(), destination)

    object_key = "automation/v1/ambient-lab/rain-night/video-upload/Master.mp4"
    assert ("media-handoffs", object_key) in client.objects
    assert destination.read_bytes() == payload
    assert pushed.sha256 == pulled.sha256 == hashlib.sha256(payload).hexdigest()
    assert store.exists(_key()) is True
    assert store.metadata(_key()) == pushed


def test_r2_config_resolves_api_token_through_the_secret_owner() -> None:
    environment = {
        "R2_ACCOUNT_ID": "account-id",
        "R2_ACCESS_KEY_ID": "access-key-id",
        "R2_BUCKET": "media-handoffs",
        "R2_PREFIX": "automation/v1",
    }
    with (
        patch.dict("os.environ", environment, clear=True),
        patch("youtube_automation.infrastructure.media_store.r2.get_secret", return_value="api-token") as secret,
    ):
        config = R2MediaStoreConfig.from_environment()

    assert config.api_token == "api-token"
    secret.assert_called_once_with("R2_API_TOKEN")


def test_r2_s3_secret_is_derived_without_using_the_raw_api_token() -> None:
    config = _config()

    assert config.secret_access_key == hashlib.sha256(config.api_token.encode()).hexdigest()
    assert config.secret_access_key != config.api_token


def test_r2_config_fails_closed_when_authentication_is_missing() -> None:
    environment = {
        "R2_ACCOUNT_ID": "account-id",
        "R2_ACCESS_KEY_ID": "access-key-id",
        "R2_BUCKET": "media-handoffs",
    }
    with (
        patch.dict("os.environ", environment, clear=True),
        patch(
            "youtube_automation.infrastructure.media_store.r2.get_secret",
            side_effect=ConfigError("R2_API_TOKEN unavailable"),
        ),
    ):
        with pytest.raises(ConfigError, match="R2_API_TOKEN"):
            R2MediaStoreConfig.from_environment()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("account_id", "account.example/escape"),
        ("bucket", "../other-bucket"),
        ("bucket", "media..handoffs"),
        ("prefix", "../other-prefix"),
        ("prefix", "/absolute"),
    ],
)
def test_r2_config_rejects_bucket_or_prefix_boundary_escape(field: str, value: str) -> None:
    values = {
        "account_id": "account-id",
        "access_key_id": "access-key-id",
        "api_token": "api-token-value",
        "bucket": "media-handoffs",
        "prefix": "automation/v1",
    }
    values[field] = value

    with pytest.raises(ConfigError, match=field):
        R2MediaStoreConfig(**values)


def test_r2_errors_are_redacted_and_do_not_expose_credentials(tmp_path: Path) -> None:
    class FailingClient(FakeS3Client):
        def upload_fileobj(self, *args: object, **kwargs: object) -> None:
            del args, kwargs
            raise RuntimeError("token=api-token-value authorization=access-key-id")

    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    store = R2MediaStore(_config(), client=FailingClient(), transfer_config=object())

    with pytest.raises(MediaStoreError) as raised:
        store.push(source, _key())
    message = str(raised.value)
    assert "api-token-value" not in message
    assert "access-key-id" not in message


def test_r2_pull_removes_partial_output_when_checksum_does_not_match(tmp_path: Path) -> None:
    class CorruptingClient(FakeS3Client):
        def download_fileobj(
            self,
            bucket: str,
            key: str,
            file_object: io.BufferedWriter,
            *,
            Config: object,
        ) -> None:
            del bucket, key, Config
            file_object.write(b"corrupt")

    client = CorruptingClient()
    store = R2MediaStore(_config(), client=client, transfer_config=object())
    source = tmp_path / "source.bin"
    source.write_bytes(b"expected")
    store.push(source, _key())
    destination = tmp_path / "download.bin"

    with pytest.raises(MediaStoreError, match="checksum"):
        store.pull(_key(), destination)
    assert not destination.exists()


def test_r2_metadata_without_checksum_is_rejected(tmp_path: Path) -> None:
    del tmp_path

    class MetadataMissingClient(FakeS3Client):
        def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
            del Bucket, Key
            return {"ContentLength": 7, "Metadata": {}, "ETag": '"fixture"'}

    store = R2MediaStore(_config(), client=MetadataMissingClient(), transfer_config=object())

    with pytest.raises(MediaStoreError, match="metadata が不正"):
        store.metadata(_key())


def test_r2_multipart_resumes_remote_parts_after_process_interruption(tmp_path: Path) -> None:
    part_size = 5 * 1024 * 1024
    payload = b"a" * part_size + b"b" * part_size + b"tail"
    source = tmp_path / "Master.mp4"
    source.write_bytes(payload)
    client = FakeS3Client()
    client.interrupt_part = 2
    transfer = MultipartTransferConfig(threshold=part_size, part_size=part_size)
    first_store = R2MediaStore(_config(), client=client, transfer_config=object(), multipart_transfer_config=transfer)

    with pytest.raises(MediaStoreError, match="connection interrupted"):
        first_store.push(source, _key())

    checkpoint = next((tmp_path / ".yt-r2-multipart").glob("*.json"))
    assert stat.S_IMODE(checkpoint.stat().st_mode) == 0o600
    assert client.uploaded_parts == [1]

    resumed_store = R2MediaStore(_config(), client=client, transfer_config=object(), multipart_transfer_config=transfer)
    remote = resumed_store.push(source, _key())

    assert client.create_calls == 1
    assert client.uploaded_parts == [1, 2, 3]
    object_key = "automation/v1/ambient-lab/rain-night/video-upload/Master.mp4"
    assert client.objects[("media-handoffs", object_key)][0] == payload
    assert remote.sha256 == hashlib.sha256(payload).hexdigest()
    assert not checkpoint.exists()


def test_r2_multipart_push_is_idempotent_after_completion(tmp_path: Path) -> None:
    part_size = 5 * 1024 * 1024
    source = tmp_path / "Master.mp4"
    source.write_bytes(b"x" * (part_size + 1))
    client = FakeS3Client()
    store = R2MediaStore(
        _config(),
        client=client,
        transfer_config=object(),
        multipart_transfer_config=MultipartTransferConfig(threshold=part_size, part_size=part_size),
    )

    first = store.push(source, _key())
    uploads_after_first_push = list(client.uploaded_parts)
    second = store.push(source, _key())

    assert second == first
    assert client.create_calls == 1
    assert client.uploaded_parts == uploads_after_first_push


def test_r2_small_push_keeps_the_managed_transfer_path(tmp_path: Path) -> None:
    source = tmp_path / "small.bin"
    source.write_bytes(b"small")
    client = FakeS3Client()
    store = R2MediaStore(
        _config(),
        client=client,
        transfer_config=object(),
        multipart_transfer_config=MultipartTransferConfig(threshold=5 * 1024 * 1024, part_size=5 * 1024 * 1024),
    )

    store.push(source, _key())

    assert client.create_calls == 0
    assert client.uploaded_parts == []
