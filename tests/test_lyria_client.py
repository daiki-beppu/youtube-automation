"""utils/lyria_client.py のユニットテスト。"""

from __future__ import annotations

import base64
import os
from unittest.mock import MagicMock, patch

import pytest

from youtube_automation.infrastructure.errors import ConfigError


@pytest.fixture(autouse=True)
def clean_env():
    saved = os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
    yield
    if saved is None:
        os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
    else:
        os.environ["GOOGLE_CLOUD_PROJECT"] = saved


@pytest.fixture(autouse=True)
def mock_adc():
    """`google.auth.default()` を差し替える。デフォルトでは project None を返す。"""
    with patch(
        "youtube_automation.utils.google_cloud_project.google_auth_default",
        return_value=(MagicMock(), None),
    ) as m:
        yield m


@pytest.fixture
def mock_token():
    with patch("youtube_automation.utils.lyria_client._access_token", return_value="fake-token"):
        yield


def _ok_response(audio_bytes: bytes) -> MagicMock:
    resp = MagicMock()
    resp.ok = True
    resp.json.return_value = {
        "status": "completed",
        "outputs": [
            {"type": "text", "text": "lyrics"},
            {"type": "audio", "mime_type": "audio/mpeg", "data": base64.b64encode(audio_bytes).decode()},
        ],
    }
    return resp


class TestGenerateMusic:
    def test_returns_audio_bytes_on_success(self, mock_token):
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"
        audio = b"\xff\xfb\x90\x00fake-mp3"

        from youtube_automation.utils import lyria_client

        with patch.object(lyria_client.requests, "post", return_value=_ok_response(audio)) as mock_post:
            result = lyria_client.generate_music("ambient test", "lyria-3-pro-preview")

        assert result == audio
        args, kwargs = mock_post.call_args
        assert args[0] == "https://aiplatform.googleapis.com/v1beta1/projects/my-project/locations/global/interactions"
        assert kwargs["json"] == {
            "model": "lyria-3-pro-preview",
            "input": [{"type": "text", "text": "ambient test"}],
        }
        assert kwargs["headers"]["Authorization"] == "Bearer fake-token"

    def test_without_project_raises_config_error(self):
        from youtube_automation.utils import lyria_client

        with pytest.raises(ConfigError, match="ADC credentials に project_id が含まれていません"):
            lyria_client.generate_music("prompt", "lyria-3-pro-preview")

    def test_falls_back_to_adc_project(self, mock_token, mock_adc):
        """env 未設定でも ADC quota project から URL を組み立てる"""
        mock_adc.return_value = (MagicMock(), "adc-project")
        audio = b"\xff\xfb\x90\x00fake-mp3"

        from youtube_automation.utils import lyria_client

        with patch.object(lyria_client.requests, "post", return_value=_ok_response(audio)) as mock_post:
            result = lyria_client.generate_music("ambient test", "lyria-3-pro-preview")

        assert result == audio
        args, _ = mock_post.call_args
        assert args[0] == "https://aiplatform.googleapis.com/v1beta1/projects/adc-project/locations/global/interactions"

    def test_returns_none_on_http_error(self, mock_token):
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"

        resp = MagicMock()
        resp.ok = False
        resp.status_code = 400
        resp.text = "INVALID_ARGUMENT"

        from youtube_automation.utils import lyria_client

        with patch.object(lyria_client.requests, "post", return_value=resp):
            result = lyria_client.generate_music("p", "lyria-3-pro-preview")

        assert result is None

    def test_returns_none_when_no_audio_in_response(self, mock_token):
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"

        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {"status": "completed", "outputs": [{"type": "text", "text": "only text"}]}

        from youtube_automation.utils import lyria_client

        with patch.object(lyria_client.requests, "post", return_value=resp):
            result = lyria_client.generate_music("p", "lyria-3-pro-preview")

        assert result is None

    def test_returns_none_on_network_exception(self, mock_token):
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"

        from youtube_automation.utils import lyria_client

        with patch.object(lyria_client.requests, "post", side_effect=lyria_client.requests.ConnectionError("boom")):
            result = lyria_client.generate_music("p", "lyria-3-pro-preview")

        assert result is None

    def test_bpm_embedded_in_payload_prompt(self, mock_token):
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"
        audio = b"\xff\xfb\x90\x00fake-mp3"

        from youtube_automation.utils import lyria_client

        with patch.object(lyria_client.requests, "post", return_value=_ok_response(audio)) as mock_post:
            lyria_client.generate_music("solo piano", "lyria-3-pro-preview", bpm=120)

        _, kwargs = mock_post.call_args
        assert kwargs["json"]["input"][0]["text"] == "solo piano, 120 BPM"

    def test_intensity_embedded_in_payload_prompt(self, mock_token):
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"
        audio = b"\xff\xfb\x90\x00fake-mp3"

        from youtube_automation.utils import lyria_client

        with patch.object(lyria_client.requests, "post", return_value=_ok_response(audio)) as mock_post:
            lyria_client.generate_music("solo piano", "lyria-3-pro-preview", intensity="low")

        _, kwargs = mock_post.call_args
        assert kwargs["json"]["input"][0]["text"].startswith("mellow, low-energy, solo piano")

    def test_mode_embedded_in_payload_prompt(self, mock_token):
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"
        audio = b"\xff\xfb\x90\x00fake-mp3"

        from youtube_automation.utils import lyria_client

        with patch.object(lyria_client.requests, "post", return_value=_ok_response(audio)) as mock_post:
            lyria_client.generate_music("solo piano", "lyria-3-pro-preview", mode="instrumental")

        _, kwargs = mock_post.call_args
        assert kwargs["json"]["input"][0]["text"] == "solo piano. Instrumental."

    def test_lyrics_embedded_in_payload_prompt(self, mock_token):
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"
        audio = b"\xff\xfb\x90\x00fake-mp3"

        from youtube_automation.utils import lyria_client

        with patch.object(lyria_client.requests, "post", return_value=_ok_response(audio)) as mock_post:
            lyria_client.generate_music("solo piano", "lyria-3-pro-preview", lyrics="[Verse]\nla")

        _, kwargs = mock_post.call_args
        assert "Lyrics: [Verse]\nla" in kwargs["json"]["input"][0]["text"]

    def test_reference_image_added_to_payload_input(self, mock_token, tmp_path):
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"
        audio = b"\xff\xfb\x90\x00fake-mp3"
        img_path = tmp_path / "main.png"
        img_bytes = b"\x89PNG\r\n\x1a\nfake-image-bytes"
        img_path.write_bytes(img_bytes)

        from youtube_automation.utils import lyria_client

        with patch.object(lyria_client.requests, "post", return_value=_ok_response(audio)) as mock_post:
            lyria_client.generate_music("solo piano", "lyria-3-pro-preview", reference_image=img_path)

        _, kwargs = mock_post.call_args
        inputs = kwargs["json"]["input"]
        assert len(inputs) == 2
        assert inputs[0] == {"type": "text", "text": "solo piano"}
        assert inputs[1]["type"] == "image"
        assert inputs[1]["mime_type"] == "image/png"
        assert base64.b64decode(inputs[1]["data"]) == img_bytes

    def test_missing_reference_image_raises_config_error(self, mock_token, tmp_path):
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"
        missing = tmp_path / "missing.png"

        from youtube_automation.utils import lyria_client

        with pytest.raises(ConfigError, match="参照画像が存在しません"):
            lyria_client.generate_music("p", "lyria-3-pro-preview", reference_image=missing)

    def test_returns_audio_bytes_from_new_schema_response(self, mock_token):
        # Given: HTTP レスポンスが公式新 schema (steps[*].content[*]) のみ
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"
        audio = b"\xff\xfb\x90\x00new-schema-mp3"
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {
            "steps": [
                {
                    "type": "model_output",
                    "content": [
                        {"type": "audio", "mime_type": "audio/mpeg", "data": base64.b64encode(audio).decode()},
                    ],
                }
            ]
        }

        from youtube_automation.utils import lyria_client

        # When: generate_music を呼ぶ
        with patch.object(lyria_client.requests, "post", return_value=resp):
            result = lyria_client.generate_music("p", "lyria-3-pro-preview")

        # Then: 新 schema からデコード済み audio bytes が返る
        assert result == audio

    def test_prefers_legacy_when_both_schemas_in_http_response(self, mock_token):
        # Given: HTTP レスポンスに legacy outputs と新 schema steps が同居
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"
        legacy_audio = b"\xff\xfb\x90\x00legacy"
        new_audio = b"\xff\xfb\x90\x00new"
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {
            "outputs": [
                {"type": "audio", "mime_type": "audio/mpeg", "data": base64.b64encode(legacy_audio).decode()},
            ],
            "steps": [
                {
                    "type": "model_output",
                    "content": [
                        {"type": "audio", "mime_type": "audio/mpeg", "data": base64.b64encode(new_audio).decode()},
                    ],
                }
            ],
        }

        from youtube_automation.utils import lyria_client

        # When: generate_music を呼ぶ
        with patch.object(lyria_client.requests, "post", return_value=resp):
            result = lyria_client.generate_music("p", "lyria-3-pro-preview")

        # Then: 既存挙動互換のため legacy 側が優先される
        assert result == legacy_audio


class TestInterruptRecovery:
    """#481: response 受信後の Ctrl+C で支払い済みオーディオを失わない。"""

    def test_post_interrupt_reraises_without_recovery(self, mock_token, tmp_path, monkeypatch):
        # Given: requests.post 中（API 処理中）に Ctrl+C
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"
        from youtube_automation.utils import lyria_client

        monkeypatch.setattr(lyria_client, "channel_dir", lambda: tmp_path)

        with patch.object(lyria_client.requests, "post", side_effect=KeyboardInterrupt):
            # When / Then: response 未受信のため救済せず KeyboardInterrupt を再送出
            with pytest.raises(KeyboardInterrupt):
                lyria_client.generate_music("p", "lyria-3-pro-preview")

        # 退避ファイルは作られない
        assert not (tmp_path / "tmp" / "lyria-recovered").exists()

    def test_recovers_paid_audio_on_interrupt_after_response(self, mock_token, tmp_path, monkeypatch):
        # Given: response 受信後（課金確定後）に Ctrl+C
        os.environ["GOOGLE_CLOUD_PROJECT"] = "my-project"
        audio = b"\xff\xfb\x90\x00paid-audio"
        from youtube_automation.utils import lyria_client

        monkeypatch.setattr(lyria_client, "channel_dir", lambda: tmp_path)

        resp = MagicMock()
        resp.ok = True
        good_body = {
            "outputs": [{"type": "audio", "mime_type": "audio/mpeg", "data": base64.b64encode(audio).decode()}]
        }
        # 1 回目（本処理）の json() で中断、復旧時の再 json() は正常 body
        resp.json.side_effect = [KeyboardInterrupt(), good_body]

        with patch.object(lyria_client.requests, "post", return_value=resp):
            # When / Then: 中断は最終的に伝播する
            with pytest.raises(KeyboardInterrupt):
                lyria_client.generate_music("p", "lyria-3-pro-preview")

        # 支払い済み bytes が退避ファイルに保存されている
        recovered = list((tmp_path / "tmp" / "lyria-recovered").glob("*.mp3"))
        assert len(recovered) == 1
        assert recovered[0].read_bytes() == audio

    def test_persist_recovered_audio_writes_sha1_path_idempotently(self, tmp_path, monkeypatch):
        import hashlib

        from youtube_automation.utils import lyria_client

        monkeypatch.setattr(lyria_client, "channel_dir", lambda: tmp_path)
        audio = b"some-paid-bytes"

        p1 = lyria_client.persist_recovered_audio(audio)
        p2 = lyria_client.persist_recovered_audio(audio)

        # 内容ハッシュ命名で冪等（同一応答は同一パス）
        assert p1 == p2
        assert p1.read_bytes() == audio
        assert p1.name == hashlib.sha1(audio).hexdigest() + ".mp3"
        assert p1.parent == tmp_path / "tmp" / "lyria-recovered"

    def test_recover_skips_when_no_audio_in_response(self, tmp_path, monkeypatch, capsys):
        # Given: 中断時に再抽出しても audio が無い（救済不能）
        from youtube_automation.utils import lyria_client

        monkeypatch.setattr(lyria_client, "channel_dir", lambda: tmp_path)
        resp = MagicMock()
        resp.json.return_value = {"outputs": [{"type": "text", "text": "no audio"}]}

        lyria_client._recover_audio_on_interrupt(resp)

        # 退避ファイルは作られず、その旨が表示される
        assert not (tmp_path / "tmp" / "lyria-recovered").exists()
        assert "退避可能なオーディオデータがありませんでした" in capsys.readouterr().out


class TestExtractAudioBytes:
    def test_returns_audio_from_legacy_outputs(self):
        # Given: legacy outputs schema の body
        from youtube_automation.utils.lyria_client import _extract_audio_bytes

        audio = b"\xff\xfb\x90\x00fake-mp3"
        body = {
            "outputs": [
                {"type": "text", "text": "lyrics"},
                {"type": "audio", "mime_type": "audio/mpeg", "data": base64.b64encode(audio).decode()},
            ]
        }

        # When: ヘルパーで抽出
        result = _extract_audio_bytes(body)

        # Then: 原バイト列が返る
        assert result == audio

    def test_returns_audio_from_new_schema_steps(self):
        # Given: 公式新 schema (steps[*].content[*]) の body
        from youtube_automation.utils.lyria_client import _extract_audio_bytes

        audio = b"\xff\xfb\x90\x00fake-mp3"
        body = {
            "status": "completed",
            "steps": [
                {
                    "type": "model_output",
                    "content": [
                        {"type": "text", "text": "lyrics"},
                        {"type": "audio", "mime_type": "audio/mpeg", "data": base64.b64encode(audio).decode()},
                    ],
                }
            ],
        }

        # When: ヘルパーで抽出
        result = _extract_audio_bytes(body)

        # Then: 原バイト列が返る
        assert result == audio

    def test_prefers_legacy_when_both_schemas_present(self):
        # Given: legacy outputs と 新 schema steps が同時に存在する移行期 body
        from youtube_automation.utils.lyria_client import _extract_audio_bytes

        legacy_audio = b"\xff\xfb\x90\x00legacy"
        new_audio = b"\xff\xfb\x90\x00new"
        body = {
            "outputs": [
                {"type": "audio", "mime_type": "audio/mpeg", "data": base64.b64encode(legacy_audio).decode()},
            ],
            "steps": [
                {
                    "type": "model_output",
                    "content": [
                        {"type": "audio", "mime_type": "audio/mpeg", "data": base64.b64encode(new_audio).decode()},
                    ],
                }
            ],
        }

        # When: ヘルパーで抽出
        result = _extract_audio_bytes(body)

        # Then: 既存挙動互換のため legacy が優先される
        assert result == legacy_audio

    def test_skips_non_audio_content_in_new_schema(self):
        # Given: 新 schema で先頭 content が image, 2 番目が audio
        from youtube_automation.utils.lyria_client import _extract_audio_bytes

        audio = b"\xff\xfb\x90\x00fake-mp3"
        body = {
            "steps": [
                {
                    "type": "model_output",
                    "content": [
                        {"type": "image", "mime_type": "image/png", "data": base64.b64encode(b"img").decode()},
                        {"type": "audio", "mime_type": "audio/mpeg", "data": base64.b64encode(audio).decode()},
                    ],
                }
            ]
        }

        # When: ヘルパーで抽出
        result = _extract_audio_bytes(body)

        # Then: type=audio の content が拾われる
        assert result == audio

    def test_picks_audio_across_multiple_steps(self):
        # Given: 複数 steps のうち 2 つ目に audio がある
        from youtube_automation.utils.lyria_client import _extract_audio_bytes

        audio = b"\xff\xfb\x90\x00fake-mp3"
        image_content = {"type": "image", "mime_type": "image/png", "data": base64.b64encode(b"img").decode()}
        audio_content = {"type": "audio", "mime_type": "audio/mpeg", "data": base64.b64encode(audio).decode()}
        body = {
            "steps": [
                {"type": "thought", "content": [image_content]},
                {"type": "model_output", "content": [audio_content]},
            ]
        }

        # When: ヘルパーで抽出
        result = _extract_audio_bytes(body)

        # Then: 2 つ目の step から audio が拾われる
        assert result == audio

    def test_skips_legacy_entry_with_non_audio_mime(self):
        # Given: type=audio だが mime_type が video/mp4 の legacy entry
        from youtube_automation.utils.lyria_client import _extract_audio_bytes

        body = {
            "outputs": [
                {"type": "audio", "mime_type": "video/mp4", "data": base64.b64encode(b"vid").decode()},
            ]
        }

        # When: ヘルパーで抽出
        result = _extract_audio_bytes(body)

        # Then: startswith("audio/") フィルタで skip → None
        assert result is None

    def test_skips_legacy_entry_with_missing_mime(self):
        # Given: legacy entry に mime_type キーが欠落、次の entry に正常 audio
        from youtube_automation.utils.lyria_client import _extract_audio_bytes

        audio = b"\xff\xfb\x90\x00fake-mp3"
        body = {
            "outputs": [
                {"type": "audio", "data": base64.b64encode(b"x").decode()},
                {"type": "audio", "mime_type": "audio/mpeg", "data": base64.b64encode(audio).decode()},
            ]
        }

        # When: ヘルパーで抽出
        result = _extract_audio_bytes(body)

        # Then: mime_type 欠落の entry は skip し、後続の正常 entry を拾う
        assert result == audio

    def test_skips_legacy_entry_with_missing_data(self):
        # Given: legacy entry の data キーが欠落、後続 entry に正常 audio
        from youtube_automation.utils.lyria_client import _extract_audio_bytes

        audio = b"\xff\xfb\x90\x00fake-mp3"
        body = {
            "outputs": [
                {"type": "audio", "mime_type": "audio/mpeg"},
                {"type": "audio", "mime_type": "audio/mpeg", "data": base64.b64encode(audio).decode()},
            ]
        }

        # When: ヘルパーで抽出
        result = _extract_audio_bytes(body)

        # Then: 例外を投げず skip し、次の audio を返す
        assert result == audio

    def test_skips_new_schema_entry_with_missing_data(self):
        # Given: 新 schema で content[*].data が欠落、後続 content に正常 audio
        from youtube_automation.utils.lyria_client import _extract_audio_bytes

        audio = b"\xff\xfb\x90\x00fake-mp3"
        body = {
            "steps": [
                {
                    "type": "model_output",
                    "content": [
                        {"type": "audio", "mime_type": "audio/mpeg"},
                        {"type": "audio", "mime_type": "audio/mpeg", "data": base64.b64encode(audio).decode()},
                    ],
                }
            ]
        }

        # When: ヘルパーで抽出
        result = _extract_audio_bytes(body)

        # Then: data 欠落は skip し、次の正常 audio を返す
        assert result == audio

    def test_skips_new_schema_entry_with_missing_mime(self):
        # Given: 新 schema で content[*].mime_type が欠落、後続 content に正常 audio
        from youtube_automation.utils.lyria_client import _extract_audio_bytes

        audio = b"\xff\xfb\x90\x00fake-mp3"
        body = {
            "steps": [
                {
                    "type": "model_output",
                    "content": [
                        {"type": "audio", "data": base64.b64encode(b"x").decode()},
                        {"type": "audio", "mime_type": "audio/mpeg", "data": base64.b64encode(audio).decode()},
                    ],
                }
            ]
        }

        # When: ヘルパーで抽出
        result = _extract_audio_bytes(body)

        # Then: mime_type 欠落は skip し、後続の正常 audio を返す
        assert result == audio

    def test_returns_none_for_empty_body(self):
        # Given: 空の body
        from youtube_automation.utils.lyria_client import _extract_audio_bytes

        # When: ヘルパーで抽出
        result = _extract_audio_bytes({})

        # Then: None
        assert result is None

    def test_returns_none_when_no_audio_in_either_schema(self):
        # Given: legacy outputs に text のみ、新 schema steps にも image のみ
        from youtube_automation.utils.lyria_client import _extract_audio_bytes

        body = {
            "outputs": [
                {"type": "text", "text": "no audio"},
            ],
            "steps": [
                {
                    "type": "model_output",
                    "content": [
                        {"type": "image", "mime_type": "image/png", "data": base64.b64encode(b"img").decode()},
                    ],
                }
            ],
        }

        # When: ヘルパーで抽出
        result = _extract_audio_bytes(body)

        # Then: 両 schema いずれにも audio がないため None
        assert result is None

    def test_returns_none_when_step_content_missing(self):
        # Given: steps[0] に content キーが無い
        from youtube_automation.utils.lyria_client import _extract_audio_bytes

        body = {"steps": [{"type": "model_output"}]}

        # When: ヘルパーで抽出
        result = _extract_audio_bytes(body)

        # Then: None
        assert result is None

    def test_returns_none_when_step_content_empty(self):
        # Given: steps[0].content が空 list
        from youtube_automation.utils.lyria_client import _extract_audio_bytes

        body = {"steps": [{"type": "model_output", "content": []}]}

        # When: ヘルパーで抽出
        result = _extract_audio_bytes(body)

        # Then: None
        assert result is None

    def test_skips_when_outputs_is_not_list(self):
        # Given: legacy outputs が dict / 新 schema 側に正常 audio
        from youtube_automation.utils.lyria_client import _extract_audio_bytes

        audio = b"\xff\xfb\x90\x00fake-mp3"
        body = {
            "outputs": {"type": "audio", "mime_type": "audio/mpeg", "data": base64.b64encode(b"x").decode()},
            "steps": [
                {
                    "type": "model_output",
                    "content": [
                        {"type": "audio", "mime_type": "audio/mpeg", "data": base64.b64encode(audio).decode()},
                    ],
                }
            ],
        }

        # When: ヘルパーで抽出
        result = _extract_audio_bytes(body)

        # Then: 不正型の outputs は型ガードで skip し、新 schema を拾う
        assert result == audio

    def test_skips_when_steps_is_not_list(self):
        # Given: 新 schema steps が dict（list 以外）
        from youtube_automation.utils.lyria_client import _extract_audio_bytes

        body = {"steps": {"type": "model_output", "content": []}}

        # When: ヘルパーで抽出
        result = _extract_audio_bytes(body)

        # Then: 型ガードで skip → None
        assert result is None

    def test_skips_when_step_is_not_dict(self):
        # Given: steps の要素が None / 文字列
        from youtube_automation.utils.lyria_client import _extract_audio_bytes

        audio = b"\xff\xfb\x90\x00fake-mp3"
        body = {
            "steps": [
                None,
                "not-a-dict",
                {
                    "type": "model_output",
                    "content": [
                        {"type": "audio", "mime_type": "audio/mpeg", "data": base64.b64encode(audio).decode()},
                    ],
                },
            ]
        }

        # When: ヘルパーで抽出
        result = _extract_audio_bytes(body)

        # Then: 不正な要素は skip し、有効な step から audio を返す
        assert result == audio

    def test_skips_when_content_is_not_list(self):
        # Given: step.content が list 以外
        from youtube_automation.utils.lyria_client import _extract_audio_bytes

        body = {"steps": [{"type": "model_output", "content": "not-a-list"}]}

        # When: ヘルパーで抽出
        result = _extract_audio_bytes(body)

        # Then: 型ガードで skip → None
        assert result is None

    def test_skips_when_content_entry_is_not_dict(self):
        # Given: content の要素が None / 文字列、後続に正常 audio
        from youtube_automation.utils.lyria_client import _extract_audio_bytes

        audio = b"\xff\xfb\x90\x00fake-mp3"
        body = {
            "steps": [
                {
                    "type": "model_output",
                    "content": [
                        None,
                        "not-a-dict",
                        {"type": "audio", "mime_type": "audio/mpeg", "data": base64.b64encode(audio).decode()},
                    ],
                }
            ]
        }

        # When: ヘルパーで抽出
        result = _extract_audio_bytes(body)

        # Then: 不正な content 要素は skip し、正常 entry から audio を返す
        assert result == audio

    def test_skips_legacy_entry_that_is_not_dict(self):
        # Given: outputs の要素が None / 文字列、後続に正常 audio
        from youtube_automation.utils.lyria_client import _extract_audio_bytes

        audio = b"\xff\xfb\x90\x00fake-mp3"
        body = {
            "outputs": [
                None,
                "not-a-dict",
                {"type": "audio", "mime_type": "audio/mpeg", "data": base64.b64encode(audio).decode()},
            ]
        }

        # When: ヘルパーで抽出
        result = _extract_audio_bytes(body)

        # Then: 不正な要素は skip し、後続の正常 entry を返す
        assert result == audio


class TestComposePrompt:
    def test_none_params_returns_base_as_is(self):
        from youtube_automation.utils.lyria_client import _compose_prompt

        assert _compose_prompt("solo piano", None, None, None, None) == "solo piano"

    def test_bpm_appended_after_base(self):
        from youtube_automation.utils.lyria_client import _compose_prompt

        assert _compose_prompt("solo piano", 120, None, None, None) == "solo piano, 120 BPM"

    def test_intensity_low_prepended(self):
        from youtube_automation.utils.lyria_client import _compose_prompt

        result = _compose_prompt("solo piano", None, "low", None, None)
        assert result.startswith("mellow, low-energy, ")
        assert "solo piano" in result

    def test_intensity_medium_prepended(self):
        from youtube_automation.utils.lyria_client import _compose_prompt

        result = _compose_prompt("solo piano", None, "medium", None, None)
        assert result.startswith("balanced, moderate energy, ")

    def test_intensity_high_prepended(self):
        from youtube_automation.utils.lyria_client import _compose_prompt

        result = _compose_prompt("solo piano", None, "high", None, None)
        assert result.startswith("driving, high-energy, ")

    def test_mode_instrumental_appended(self):
        from youtube_automation.utils.lyria_client import _compose_prompt

        assert _compose_prompt("solo piano", None, None, "instrumental", None) == "solo piano. Instrumental."

    def test_mode_vocal_without_lyrics_appends_with_vocals(self):
        from youtube_automation.utils.lyria_client import _compose_prompt

        assert _compose_prompt("solo piano", None, None, "vocal", None) == "solo piano. With vocals."

    def test_mode_vocal_with_lyrics_skips_with_vocals(self):
        from youtube_automation.utils.lyria_client import _compose_prompt

        result = _compose_prompt("solo piano", None, None, "vocal", "[Verse]\nla la la")
        assert "With vocals" not in result
        assert "Lyrics: [Verse]\nla la la" in result

    def test_lyrics_appended(self):
        from youtube_automation.utils.lyria_client import _compose_prompt

        result = _compose_prompt("solo piano", None, None, None, "[Chorus]\nsing")
        assert result == "solo piano. Lyrics: [Chorus]\nsing"

    def test_all_params_combined_order(self):
        from youtube_automation.utils.lyria_client import _compose_prompt

        result = _compose_prompt("solo piano in A minor", 90, "low", "vocal", "[Verse]\nmelody")
        assert result == "mellow, low-energy, solo piano in A minor, 90 BPM. Lyrics: [Verse]\nmelody"

    def test_all_params_instrumental_with_lyrics(self):
        from youtube_automation.utils.lyria_client import _compose_prompt

        result = _compose_prompt("jazz trio", 130, "high", "instrumental", "hum")
        assert result == "driving, high-energy, jazz trio, 130 BPM. Instrumental. Lyrics: hum"


class TestEncodeReferenceImage:
    def test_png_encoded_with_correct_mime(self, tmp_path):
        from youtube_automation.utils.lyria_client import _encode_reference_image

        path = tmp_path / "img.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        result = _encode_reference_image(path)
        assert result["type"] == "image"
        assert result["mime_type"] == "image/png"
        assert base64.b64decode(result["data"]) == b"\x89PNG\r\n\x1a\nfake"

    def test_jpg_encoded_as_image_jpeg(self, tmp_path):
        from youtube_automation.utils.lyria_client import _encode_reference_image

        path = tmp_path / "img.jpg"
        path.write_bytes(b"\xff\xd8\xff\xe0fake-jpg")
        result = _encode_reference_image(path)
        assert result["mime_type"] == "image/jpeg"

    def test_jpeg_encoded_as_image_jpeg(self, tmp_path):
        from youtube_automation.utils.lyria_client import _encode_reference_image

        path = tmp_path / "img.jpeg"
        path.write_bytes(b"\xff\xd8\xff\xe0fake-jpg")
        result = _encode_reference_image(path)
        assert result["mime_type"] == "image/jpeg"

    def test_webp_encoded_as_image_webp(self, tmp_path):
        from youtube_automation.utils.lyria_client import _encode_reference_image

        path = tmp_path / "img.webp"
        path.write_bytes(b"RIFFxxxxWEBPfake")
        result = _encode_reference_image(path)
        assert result["mime_type"] == "image/webp"

    def test_unsupported_extension_raises_config_error(self, tmp_path):
        from youtube_automation.utils.lyria_client import _encode_reference_image

        path = tmp_path / "img.gif"
        path.write_bytes(b"GIF89afake")
        with pytest.raises(ConfigError, match="対応していない画像形式"):
            _encode_reference_image(path)

    def test_missing_file_raises_config_error(self, tmp_path):
        from youtube_automation.utils.lyria_client import _encode_reference_image

        path = tmp_path / "missing.png"
        with pytest.raises(ConfigError, match="参照画像が存在しません"):
            _encode_reference_image(path)
