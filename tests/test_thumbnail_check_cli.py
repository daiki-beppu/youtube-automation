"""yt-thumbnail-check CLI の単体テスト (#489)

Gemini Client は DI 不能 (CLI が境界で `create_genai_client` を呼ぶ) なので、
モジュールレベルの helper を直接テストして argparse / lock 分岐 /
JSON 解析を回帰させる。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from youtube_automation.scripts import thumbnail_check
from youtube_automation.utils import skill_config
from youtube_automation.utils.exceptions import ValidationError


@pytest.fixture(autouse=True)
def reset_skill_cache():
    skill_config.reset()
    yield
    skill_config.reset()


# ---------------------------------------------------------------------------
# _parse_json_response
# ---------------------------------------------------------------------------


def test_parse_json_response_strips_code_fence():
    text = '```json\n{"checks": [], "pass": true}\n```'
    data = thumbnail_check._parse_json_response(text)
    assert data == {"checks": [], "pass": True}


def test_parse_json_response_raw_object():
    text = '{"pass": false}'
    data = thumbnail_check._parse_json_response(text)
    assert data == {"pass": False}


def test_parse_json_response_empty_raises():
    with pytest.raises(ValidationError):
        thumbnail_check._parse_json_response("")


def test_parse_json_response_invalid_json_raises():
    with pytest.raises(ValidationError):
        thumbnail_check._parse_json_response("not json {")


def test_parse_json_response_root_must_be_object():
    with pytest.raises(ValidationError):
        thumbnail_check._parse_json_response("[1, 2, 3]")


# ---------------------------------------------------------------------------
# _check_image (Gemini 呼出を mock)
# ---------------------------------------------------------------------------


def _make_fake_client(response_text: str):
    """response.text に response_text を返す最小 fake client"""

    class _FakeModels:
        def generate_content(self, *args, **kwargs):
            return SimpleNamespace(text=response_text)

    return SimpleNamespace(models=_FakeModels())


def test_check_image_passes_when_all_yes(tmp_path):
    image = tmp_path / "ok.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    client = _make_fake_client(
        json.dumps(
            {
                "checks": [
                    {"index": 1, "question": "wet runway?", "answer": "YES", "reason": "ok"},
                    {"index": 2, "question": "matte-black car?", "answer": "YES", "reason": "ok"},
                ],
                "pass": True,
            }
        )
    )
    result = thumbnail_check._check_image(image_path=image, prompt="prompt", client=client, model="gemini-2.5-flash")
    assert result.passed is True
    assert len(result.checks) == 2
    assert result.error is None


def test_check_image_fails_when_any_no(tmp_path):
    image = tmp_path / "bad.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    client = _make_fake_client(
        json.dumps(
            {
                "checks": [
                    {"index": 1, "question": "wet runway?", "answer": "NO", "reason": "missing"},
                ],
                "pass": False,
            }
        )
    )
    result = thumbnail_check._check_image(image_path=image, prompt="p", client=client, model="m")
    assert result.passed is False
    assert result.checks[0]["answer"] == "NO"


def test_check_image_derives_pass_from_answers_when_pass_field_missing(tmp_path):
    """`pass` フィールドが応答に無い場合、checks の YES/NO から導出する"""
    image = tmp_path / "x.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    client = _make_fake_client(
        json.dumps(
            {
                "checks": [
                    {"index": 1, "answer": "YES"},
                    {"index": 2, "answer": "YES"},
                ]
            }
        )
    )
    result = thumbnail_check._check_image(image_path=image, prompt="p", client=client, model="m")
    assert result.passed is True


def test_check_image_missing_file_returns_error(tmp_path):
    image = tmp_path / "ghost.png"
    client = _make_fake_client("{}")
    result = thumbnail_check._check_image(image_path=image, prompt="p", client=client, model="m")
    assert result.passed is False
    assert result.error and "not found" in result.error


def test_check_image_gemini_exception_returns_error(tmp_path):
    image = tmp_path / "img.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")

    class _Boom:
        def generate_content(self, *a, **kw):
            raise RuntimeError("network down")

    client = SimpleNamespace(models=_Boom())
    result = thumbnail_check._check_image(image_path=image, prompt="p", client=client, model="m")
    assert result.passed is False
    assert "network down" in (result.error or "")


def test_check_image_invalid_json_returns_error(tmp_path):
    image = tmp_path / "img.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    client = _make_fake_client("not even json {")
    result = thumbnail_check._check_image(image_path=image, prompt="p", client=client, model="m")
    assert result.passed is False
    assert result.raw_response == "not even json {"
    assert result.error is not None


# ---------------------------------------------------------------------------
# _resolve_check_config / build_parser
# ---------------------------------------------------------------------------


def test_build_parser_accepts_multiple_images_and_extra_checks():
    parser = thumbnail_check.build_parser()
    args = parser.parse_args(["a.png", "b.png", "--check", "Q1?", "--check", "Q2?", "--json"])
    assert args.images == [Path("a.png"), Path("b.png")]
    assert args.check == ["Q1?", "Q2?"]
    assert args.json is True
    assert args.quiet is False


def test_main_print_prompt_skips_gemini(tmp_path, monkeypatch, capsys):
    """--print-prompt は Gemini 呼出をスキップして prompt を stdout 出力"""
    channel_dir = tmp_path / "ch"
    channel_dir.mkdir()
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    # Gemini Client が呼ばれたら test を壊す
    def _boom(*args, **kwargs):
        raise AssertionError("Gemini Client must not be created in --print-prompt path")

    monkeypatch.setattr("youtube_automation.utils.genai_client.create_genai_client", _boom)

    rc = thumbnail_check.main(["dummy.png", "--print-prompt"])
    assert rc == 0
    captured = capsys.readouterr().out
    assert "Checklist:" in captured


def test_main_skips_when_self_check_disabled(tmp_path, monkeypatch, capsys):
    """self_check.enabled=false のとき検査をスキップして exit 0"""
    import yaml

    channel_dir = tmp_path / "ch"
    (channel_dir / "config" / "skills").mkdir(parents=True)
    override = channel_dir / "config" / "skills" / "collection-ideate.yaml"
    override.write_text(
        yaml.safe_dump({"self_check": {"enabled": False}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))

    def _boom(*args, **kwargs):
        raise AssertionError("Gemini Client must not be created when self_check disabled")

    monkeypatch.setattr("youtube_automation.utils.genai_client.create_genai_client", _boom)

    rc = thumbnail_check.main(["nonexistent.png"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "skip" in err.lower()


def test_render_text_includes_pass_fail_marker():
    result_pass = thumbnail_check.CheckResult(
        image_path=Path("a.png"),
        passed=True,
        checks=[{"answer": "YES", "question": "Q?", "reason": "ok"}],
    )
    result_fail = thumbnail_check.CheckResult(
        image_path=Path("b.png"),
        passed=False,
        checks=[],
        error="boom",
    )
    out = thumbnail_check._render_text([result_pass, result_fail])
    assert "[PASS] a.png" in out
    assert "[FAIL] b.png" in out
    assert "ERROR: boom" in out
    assert "[YES] Q?" in out
