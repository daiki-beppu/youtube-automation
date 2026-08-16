from __future__ import annotations

import hashlib
import io
from pathlib import Path
from unittest.mock import patch

import pytest

from youtube_automation.core.errors import ConfigError, MediaStoreError
from youtube_automation.domains.media_store import MediaKey
from youtube_automation.infrastructure.media_store.r2 import R2MediaStore, R2MediaStoreConfig


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, dict[str, str]]] = {}

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
