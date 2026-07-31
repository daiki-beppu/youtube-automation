"""Executable thumbnail-routing scenarios replacing prose-string contracts (#2815)."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
from matplotlib import font_manager
from PIL import Image

from tests.test_generate_videos_script import (
    _create_collection as _create_video_collection,
)
from tests.test_generate_videos_script import (
    _create_stub_bin,
    _run_generate_videos,
)
from tests.test_thumbnail_auto_selection import (
    _NEAR_COLOR,
    _setup_channel,
    _setup_collection,
    _solid_image,
)
from tests.test_thumbnail_codex_image_skill import (
    _CODEX_IMAGE_SH,
    _parse_invocations,
    _prepare_fake_codex_env,
    _run_script,
)
from youtube_automation.commands.media import generate_image, generate_lyria_master
from youtube_automation.commands.thumbnail import auto_select_thumbnail
from youtube_automation.configuration import skills as skill_config
from youtube_automation.core.errors import ConfigError
from youtube_automation.domains.media.image import (
    ImageGenerationRequest,
    ImageGenerationResult,
)
from youtube_automation.domains.thumbnail.references import plan_ttp_reference_assignments
from youtube_automation.domains.thumbnail.text import OverlaySpec, TextStyle, compose_thumbnail_text
from youtube_automation.infrastructure.media.collection_paths import CollectionPaths
from youtube_automation.infrastructure.media.image_provider import get_provider
from youtube_automation.infrastructure.media.image_provider.config import (
    build_codex_prompt,
    parse_image_generation_config,
)


@pytest.fixture(autouse=True)
def _reset_skill_config() -> None:
    skill_config.reset()
    yield
    skill_config.reset()


class _RecordingProvider:
    name = "gemini"
    supported_aspect_ratios = ("16:9",)

    def __init__(self) -> None:
        self.requests: list[ImageGenerationRequest] = []

    def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        self.requests.append(request)
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        request.output_path.write_bytes(b"generated")
        return ImageGenerationResult(success=True, saved_path=request.output_path)


def _gemini_skill_config(*, max_attempts: int = 1) -> dict[str, object]:
    return {
        "image_generation": {
            "provider": "gemini",
            "gemini": {
                "generation_mode": "single_step",
                "single_step": {"max_attempts": max_attempts, "rotate": True},
                "reference_images": {"dedup_recent_collections": 0},
                "composition_rules": {"text_lines": "2 lines"},
            },
        }
    }


def _run_generate_image(
    monkeypatch: pytest.MonkeyPatch,
    channel_root: Path,
    provider: _RecordingProvider,
    argv: list[str],
    *,
    max_attempts: int = 1,
    confirm_cost: bool = True,
) -> int:
    config = _gemini_skill_config(max_attempts=max_attempts)
    parsed = parse_image_generation_config(config)
    monkeypatch.setattr(generate_image, "load_image_generation_config", lambda: parsed)
    monkeypatch.setattr(generate_image, "get_provider", lambda _cfg: provider)
    monkeypatch.setattr(generate_image, "_channel_root", lambda: channel_root)
    monkeypatch.setattr(skill_config, "load_skill_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(generate_image, "confirm_cost", lambda *_args, **_kwargs: confirm_cost)
    monkeypatch.setattr(sys, "argv", ["yt-generate-image", *argv])
    with pytest.raises(SystemExit) as exc_info:
        generate_image.main()
    return int(exc_info.value.code)


def _benchmark_refs(channel_root: Path, *names: str, channel: str = "winner") -> list[Path]:
    root = channel_root / "data" / "thumbnail_compare" / "benchmark" / channel
    root.mkdir(parents=True, exist_ok=True)
    paths = [root / name for name in names]
    for path in paths:
        path.write_bytes(b"reference")
    return paths


def _overlay_spec() -> OverlaySpec:
    font = Path(font_manager.findfont("DejaVu Sans"))
    return OverlaySpec(
        title_style=TextStyle(
            font_path=font,
            size=72,
            color="#FFFFFF",
            stroke_width=3,
            stroke_color="#000000",
        ),
        channel_name_style=None,
        anchor="bottom-center",
        margin_x=40,
        margin_y=32,
        line_spacing=1.1,
        gap=16,
    )


def test_full_mode_auto_selects_thumbnail_and_records_state(tmp_path, monkeypatch, capsys) -> None:
    _setup_channel(tmp_path, monkeypatch, mode="full")
    collection = _setup_collection(tmp_path)
    _solid_image(collection / "10-assets" / "thumbnail-v1.jpg", _NEAR_COLOR)
    state_path = collection / "workflow-state.json"
    state_path.write_text(json.dumps({"stage": "planning"}), encoding="utf-8")

    assert auto_select_thumbnail.main([str(collection), "--apply", "--json"]) == 0

    assert (collection / "10-assets" / "thumbnail.jpg").is_file()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["thumbnail_auto_selection"]["mode"] == "full"
    assert json.loads(capsys.readouterr().out)["status"] == "ok"


def test_standard_flow_renders_thumbnail_from_textless_main_without_mutating_it(tmp_path) -> None:
    assets = tmp_path / "collection" / "10-assets"
    assets.mkdir(parents=True)
    main = assets / "main.png"
    Image.new("RGB", (640, 360), "#123456").save(main)
    before = main.read_bytes()

    output = compose_thumbnail_text(
        background=main,
        output=assets / "thumbnail-v1.jpg",
        channel_root=tmp_path,
        spec=_overlay_spec(),
        title_lines=["Night Focus"],
    )

    assert output.is_file()
    assert main.read_bytes() == before
    assert output.read_bytes() != before


def test_single_step_executes_thumbnail_then_textless_main_as_distinct_artifacts(tmp_path, monkeypatch) -> None:
    channel = tmp_path / "channel"
    reference = _benchmark_refs(channel, "reference.jpg")[0]
    provider = _RecordingProvider()
    assets = tmp_path / "collection" / "10-assets"

    first = _run_generate_image(
        monkeypatch,
        channel,
        provider,
        [
            "--prompt",
            "thumbnail",
            "--output",
            str(assets / "thumbnail-v1.jpg"),
            "--reference",
            str(reference),
            "--yes",
            "--max-workers",
            "1",
        ],
    )
    second = _run_generate_image(
        monkeypatch,
        channel,
        provider,
        [
            "--prompt",
            "remove text",
            "--output",
            str(assets / "main-v1.png"),
            "--reference",
            str(assets / "thumbnail-v1.jpg"),
            "--yes",
            "--max-workers",
            "1",
        ],
    )

    assert first == second == 0
    assert (assets / "thumbnail-v1.jpg").read_bytes() == b"generated"
    assert (assets / "main-v1.png").read_bytes() == b"generated"
    assert provider.requests[0].references == [reference]
    assert provider.requests[1].references == [assets / "thumbnail-v1.jpg"]


def test_single_step_config_is_loaded_as_executable_policy() -> None:
    parsed = parse_image_generation_config(_gemini_skill_config(max_attempts=3))

    assert parsed.provider == "gemini"
    assert parsed.gemini is not None
    assert parsed.gemini.model


def test_codex_provider_is_rejected_by_api_route_before_network(monkeypatch) -> None:
    codex_config = parse_image_generation_config(
        {
            "image_generation": {
                "provider": "codex",
                "codex": {"default_prompt_template": "TTP {title}"},
            }
        }
    )
    monkeypatch.setattr(generate_image, "load_image_generation_config", lambda: codex_config)
    monkeypatch.setattr(sys, "argv", ["yt-generate-image", "--prompt", "x", "--output", "out.png", "--yes"])

    with pytest.raises(SystemExit, match="1"):
        generate_image.main()
    with pytest.raises(ConfigError, match="codex-image.sh"):
        get_provider(codex_config)


def test_parallel_codex_route_executes_one_reference_per_candidate(tmp_path) -> None:
    refs = [tmp_path / "ref-a.png", tmp_path / "ref-b.png"]
    for ref in refs:
        ref.write_bytes(b"reference")
    prompts = ["short A", "short B"]
    outputs = [tmp_path / "a.png", tmp_path / "b.png"]
    observed_images: list[str] = []

    for prompt, output, reference in zip(prompts, outputs, refs, strict=True):
        runner_root = output.parent / output.stem
        runner_root.mkdir()
        env, log = _prepare_fake_codex_env(runner_root)
        result = _run_script(
            _CODEX_IMAGE_SH,
            "--require-reference",
            prompt,
            str(output),
            str(reference),
            env=env,
        )
        assert result.returncode == 0, result.stderr
        invocations = _parse_invocations(log.read_text(encoding="utf-8"))
        generation = [args for args in invocations if args and args[0] == "exec"][-1]
        image_index = generation.index("--image")
        observed_images.append(generation[image_index + 1])

    assert observed_images == [str(ref) for ref in refs]
    assert all(path.is_file() for path in outputs)


def test_reference_planner_rejects_duplicate_and_mixed_channel_inputs(tmp_path) -> None:
    same = _benchmark_refs(tmp_path, "a.jpg", "b.jpg", channel="alpha")
    mixed = _benchmark_refs(tmp_path, "c.jpg", channel="beta")
    benchmark_root = tmp_path / "data" / "thumbnail_compare" / "benchmark"

    with pytest.raises(ConfigError, match="同一参照画像"):
        plan_ttp_reference_assignments([same[0], same[0]], 2, True, benchmark_root=benchmark_root)
    with pytest.raises(ConfigError, match="同じベンチマークチャンネル"):
        plan_ttp_reference_assignments([same[0], mixed[0]], 2, True, benchmark_root=benchmark_root)


def test_parallel_api_route_assigns_one_reference_per_attempt(tmp_path, monkeypatch) -> None:
    channel = tmp_path / "channel"
    refs = _benchmark_refs(channel, "a.jpg", "b.jpg")
    provider = _RecordingProvider()

    code = _run_generate_image(
        monkeypatch,
        channel,
        provider,
        [
            "--prompt",
            "candidate",
            "--output",
            str(tmp_path / "preview.png"),
            "--reference",
            str(refs[0]),
            "--reference",
            str(refs[1]),
            "--ttp-strict-references",
            "--max-attempts",
            "2",
            "--max-workers",
            "1",
            "--yes",
        ],
        max_attempts=2,
    )

    assert code == 0
    assert [list(request.references) for request in provider.requests] == [[refs[0]], [refs[1]]]


def test_sequential_api_route_uses_only_selected_reference_index(tmp_path, monkeypatch) -> None:
    channel = tmp_path / "channel"
    refs = _benchmark_refs(channel, "a.jpg", "b.jpg")
    provider = _RecordingProvider()

    code = _run_generate_image(
        monkeypatch,
        channel,
        provider,
        [
            "--prompt",
            "selected",
            "--output",
            str(tmp_path / "selected.png"),
            "--reference",
            str(refs[0]),
            "--reference",
            str(refs[1]),
            "--reference-index",
            "1",
            "--max-workers",
            "1",
            "--yes",
        ],
        max_attempts=2,
    )

    assert code == 0
    assert len(provider.requests) == 1
    assert provider.requests[0].references == [refs[1]]


def test_parallel_codex_prompt_renderer_executes_short_template() -> None:
    prompt = build_codex_prompt(
        {
            "image_generation": {
                "provider": "codex",
                "codex": {"default_prompt_template": "TTP {title}; keep the winning layout."},
            }
        },
        "MIDNIGHT JAZZ",
    )

    assert prompt == "TTP MIDNIGHT JAZZ; keep the winning layout."
    assert len(prompt) < 80


def test_sequential_provider_execution_routes_codex_and_gemini_differently(tmp_path, monkeypatch) -> None:
    channel = tmp_path / "channel"
    reference = _benchmark_refs(channel, "a.jpg")[0]
    provider = _RecordingProvider()

    assert (
        _run_generate_image(
            monkeypatch,
            channel,
            provider,
            [
                "--prompt",
                "api",
                "--output",
                str(tmp_path / "api.png"),
                "--reference",
                str(reference),
                "--yes",
            ],
        )
        == 0
    )
    codex = parse_image_generation_config({"image_generation": {"provider": "codex"}})
    with pytest.raises(ConfigError, match="codex-image.sh"):
        get_provider(codex)
    assert (tmp_path / "api.png").is_file()


def test_sequential_codex_prompt_renderer_uses_same_title_contract() -> None:
    config = {
        "image_generation": {
            "provider": "codex",
            "codex": {"default_prompt_template": "Thumbnail text: {title}"},
        }
    }

    first = build_codex_prompt(config, "FOCUS")
    second = build_codex_prompt(config, "RELAX")

    assert first == "Thumbnail text: FOCUS"
    assert second == "Thumbnail text: RELAX"


def test_collection_artifact_resolution_keeps_thumbnail_and_main_separate(tmp_path) -> None:
    paths = CollectionPaths(tmp_path / "collection")
    paths.assets_dir.mkdir(parents=True)
    (paths.assets_dir / "thumbnail.jpg").write_bytes(b"upload")
    (paths.assets_dir / "main.png").write_bytes(b"textless")

    assert paths.find_thumbnail() == paths.assets_dir / "thumbnail.jpg"
    assert paths.find_main_image() == paths.assets_dir / "main.png"
    assert paths.find_thumbnail().read_bytes() != paths.find_main_image().read_bytes()


def test_loop_video_disabled_executes_static_main_route(tmp_path) -> None:
    collection = _create_video_collection(tmp_path)
    assets = collection / "10-assets"
    (assets / "main.png").write_bytes(b"main")
    config_dir = tmp_path / "config" / "skills"
    config_dir.mkdir(parents=True)
    (config_dir / "loop-video.yaml").write_text("enabled: false\n", encoding="utf-8")

    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        collection=collection,
        stub_bin=_create_stub_bin(tmp_path),
    )

    commands = ffmpeg_log.read_text(encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert "disabled by config/skills/loop-video.yaml" in result.stdout
    assert "10-assets/main.png" in commands
    assert "10-assets/loop.mp4" not in commands


def test_loop_video_enabled_executes_loop_artifact_route(tmp_path) -> None:
    collection = _create_video_collection(tmp_path)

    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
        collection=collection,
        stub_bin=_create_stub_bin(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    assert "10-assets/loop.mp4" in ffmpeg_log.read_text(encoding="utf-8")
    assert "Video BG : loop.mp4" in result.stdout


def test_lyria_reference_image_resolves_textless_main_artifact(tmp_path) -> None:
    collection = tmp_path / "collection"
    main = collection / "10-assets" / "main.png"
    main.parent.mkdir(parents=True)
    main.write_bytes(b"visual")

    resolved = generate_lyria_master._resolve_reference_image("10-assets/main.png", collection)

    assert resolved == main.resolve()


def test_short_thumbnail_reference_uses_main_not_upload_thumbnail(tmp_path) -> None:
    paths = CollectionPaths(tmp_path / "collection")
    paths.assets_dir.mkdir(parents=True)
    (paths.assets_dir / "thumbnail.jpg").write_bytes(b"upload")
    (paths.assets_dir / "main.jpg").write_bytes(b"textless")

    assert paths.find_main_image() == paths.assets_dir / "main.jpg"
    assert paths.find_main_image() != paths.find_thumbnail()


def test_planning_preview_is_not_routed_to_main_background(tmp_path) -> None:
    paths = CollectionPaths(tmp_path / "collection")
    paths.assets_dir.mkdir(parents=True)
    preview = paths.assets_dir / "planning-preview.png"
    preview.write_bytes(b"preview")

    assert paths.find_main_image() is None
    assert paths.find_thumbnail() is None
    assert preview.read_bytes() == b"preview"


def test_cost_rejection_stops_before_provider_and_output(tmp_path, monkeypatch) -> None:
    channel = tmp_path / "channel"
    reference = _benchmark_refs(channel, "a.jpg")[0]
    provider = _RecordingProvider()
    output = tmp_path / "rejected.png"

    code = _run_generate_image(
        monkeypatch,
        channel,
        provider,
        [
            "--prompt",
            "paid candidate",
            "--output",
            str(output),
            "--reference",
            str(reference),
        ],
        confirm_cost=False,
    )

    assert code == 0
    assert provider.requests == []
    assert not output.exists()


def test_full_mode_failure_preserves_state_and_creates_no_thumbnail(tmp_path, monkeypatch, capsys) -> None:
    _setup_channel(tmp_path, monkeypatch, mode="full")
    collection = _setup_collection(tmp_path)
    state_path = collection / "workflow-state.json"
    state_path.write_text(json.dumps({"stage": "planning"}), encoding="utf-8")
    before = state_path.read_bytes()

    assert auto_select_thumbnail.main([str(collection), "--apply", "--json"]) == 1

    assert state_path.read_bytes() == before
    assert not (collection / "10-assets" / "thumbnail.jpg").exists()
    assert json.loads(capsys.readouterr().out)["status"] == "error"


def test_lifecycle_execution_discovers_distinct_final_thumbnail_and_main(tmp_path) -> None:
    paths = CollectionPaths(tmp_path / "collection")
    paths.assets_dir.mkdir(parents=True)
    main = paths.assets_dir / "main.png"
    thumbnail = paths.assets_dir / "thumbnail.jpg"
    candidate = paths.assets_dir / "thumbnail-v1.jpg"
    Image.new("RGB", (640, 360), "#223344").save(main)

    compose_thumbnail_text(
        background=main,
        output=candidate,
        channel_root=tmp_path,
        spec=_overlay_spec(),
        title_lines=["COMPLETE COLLECTION"],
    )
    shutil.copyfile(candidate, thumbnail)

    assert paths.find_main_image() == main
    assert paths.find_thumbnail() == thumbnail
    assert main.read_bytes() != thumbnail.read_bytes()
