"""yt-thumbnail-auto-select (#1370) のテスト。

参照プールに近い候補の採点・dry-run/apply 分離・workflow-state 監査ログ・
失敗ケース (候補なし / 参照なし / 上書き不可 / 16:9 逸脱 / disabled) を確認する。
"""

import json
from pathlib import Path

import pytest
import yaml
from PIL import Image

import youtube_automation.scripts.auto_select_thumbnail as auto_select_thumbnail
from youtube_automation.scripts.auto_select_thumbnail import main
from youtube_automation.utils import skill_config
from youtube_automation.utils.exceptions import ValidationError
from youtube_automation.utils.thumbnail_features import feature_centroid, feature_distance

# テスト用の最小解像度 (フル HD だと純 Python の特徴量抽出が遅いため縮小)
_SIZE_16_9 = (160, 90)
_MIN_WIDTH, _MIN_HEIGHT = 160, 90

_REF_RELPATHS = (
    "data/thumbnail_compare/benchmark/SIDEEP/SIDEEP_ref-one.jpg",
    "data/thumbnail_compare/benchmark/SIDEEP/SIDEEP_ref-two.jpg",
)
_REF_COLORS = ((20, 30, 80), (25, 35, 85))
_NEAR_COLOR = (22, 32, 82)
_FAR_COLOR = (200, 40, 40)
_ARCHIVE_ENABLED = {"enabled": True}


@pytest.fixture(autouse=True)
def _reset_skill_config_cache():
    skill_config.reset()
    yield
    skill_config.reset()


def _solid_image(path, color, size=_SIZE_16_9):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


def _write_channel_config(channel_dir, *, enabled=True, refs=_REF_RELPATHS, archive_config=None):
    skills_dir = channel_dir / "config" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    cfg = {
        "archive": archive_config or {"enabled": False},
        "image_generation": {
            "auto_selection": {
                "enabled": enabled,
                "min_width": _MIN_WIDTH,
                "min_height": _MIN_HEIGHT,
                "aspect_tolerance": 0.02,
            },
            "gemini": {"reference_images": {"default": list(refs)}},
        },
    }
    (skills_dir / "thumbnail.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")


def _setup_channel(
    tmp_path, monkeypatch, *, enabled=True, refs=_REF_RELPATHS, ref_colors=_REF_COLORS, archive_config=None
):
    channel_dir = tmp_path / "channel"
    # refs は空タプルで渡されるケース（test_no_reference_images_errors）があり、
    # ref_colors とは意図的に非同長になり得るため strict=False（zip 既定 = 挙動保存）
    for relpath, color in zip(refs, ref_colors, strict=False):
        _solid_image(channel_dir / relpath, color)
    _write_channel_config(channel_dir, enabled=enabled, refs=refs, archive_config=archive_config)
    monkeypatch.setenv("CHANNEL_DIR", str(channel_dir))
    return channel_dir


def _setup_collection(tmp_path):
    collection = tmp_path / "collections" / "20260701-tst-sample"
    (collection / "10-assets").mkdir(parents=True)
    return collection


def _run_json(argv, capsys):
    code = main(argv)
    return code, capsys.readouterr()


def test_dry_run_selects_nearest_candidate_without_side_effects(tmp_path, monkeypatch, capsys):
    _setup_channel(tmp_path, monkeypatch)
    collection = _setup_collection(tmp_path)
    assets = collection / "10-assets"
    _solid_image(assets / "thumbnail-v1.jpg", _FAR_COLOR)
    _solid_image(assets / "thumbnail-v2.jpg", _NEAR_COLOR)

    code, captured = _run_json([str(collection), "--dry-run", "--json"], capsys)

    assert code == 0
    payload = json.loads(captured.out)
    assert payload["mode"] == "dry-run"
    assert payload["selected"]["candidate"] == "thumbnail-v2.jpg"
    ranking = [entry["candidate"] for entry in payload["ranking"]]
    assert ranking == ["thumbnail-v2.jpg", "thumbnail-v1.jpg"]
    assert payload["workflow_state_updated"] is None
    assert not (assets / "thumbnail.jpg").exists()


def test_apply_creates_thumbnail_and_records_workflow_state(tmp_path, monkeypatch, capsys):
    _setup_channel(tmp_path, monkeypatch)
    collection = _setup_collection(tmp_path)
    assets = collection / "10-assets"
    _solid_image(assets / "thumbnail-v1.jpg", _NEAR_COLOR)
    _solid_image(assets / "thumbnail-v2.jpg", _FAR_COLOR)
    ws_path = collection / "workflow-state.json"
    ws_path.write_text(json.dumps({"stage": "planning", "thumbnail": {"approved": False}}), encoding="utf-8")

    code, captured = _run_json([str(collection), "--apply", "--json"], capsys)

    assert code == 0
    payload = json.loads(captured.out)
    assert payload["mode"] == "apply"
    assert payload["selected"]["candidate"] == "thumbnail-v1.jpg"
    assert payload["workflow_state_updated"] is True

    target = assets / "thumbnail.jpg"
    assert target.exists()
    with Image.open(target) as img:
        assert img.format == "JPEG"

    state = json.loads(ws_path.read_text(encoding="utf-8"))
    assert state["stage"] == "planning"  # 既存キーを壊さない
    audit = state["thumbnail_auto_selection"]
    assert audit["selected"] == "thumbnail-v1.jpg"
    assert isinstance(audit["distance"], float)
    assert [entry["candidate"] for entry in audit["ranking"]] == ["thumbnail-v1.jpg", "thumbnail-v2.jpg"]
    assert audit["executed_at"]
    assert audit["reference_images"] == [str(p) for p in _REF_RELPATHS]


def test_apply_archives_before_recording_workflow_state(tmp_path, monkeypatch, capsys):
    channel_dir = _setup_channel(tmp_path, monkeypatch, archive_config=_ARCHIVE_ENABLED)
    collection = channel_dir / "collections" / "planning" / "20260701-tst-archive"
    assets = collection / "10-assets"
    assets.mkdir(parents=True)
    _solid_image(assets / "thumbnail-v1.jpg", _NEAR_COLOR)
    ws_path = collection / "workflow-state.json"
    ws_path.write_text(json.dumps({"stage": "planning"}), encoding="utf-8")
    archived = channel_dir / "assets" / "thumbnail-gallery" / "20260701-tst-archive.jpg"
    real_record_workflow_state = auto_select_thumbnail.record_workflow_state

    def assert_archive_exists_before_state(*args, **kwargs):
        assert archived.read_bytes() == (assets / "thumbnail.jpg").read_bytes()
        return real_record_workflow_state(*args, **kwargs)

    monkeypatch.setattr(auto_select_thumbnail, "record_workflow_state", assert_archive_exists_before_state)

    code = main([str(collection), "--apply"])

    assert code == 0
    assert archived.read_bytes() == (assets / "thumbnail.jpg").read_bytes()
    state = json.loads(ws_path.read_text(encoding="utf-8"))
    assert state["thumbnail_auto_selection"]["selected"] == "thumbnail-v1.jpg"
    _ = capsys.readouterr()


def test_apply_archive_failure_rolls_back_thumbnail_and_workflow_state(tmp_path, monkeypatch, capsys):
    _setup_channel(tmp_path, monkeypatch)
    collection = _setup_collection(tmp_path)
    assets = collection / "10-assets"
    _solid_image(assets / "thumbnail-v1.jpg", _NEAR_COLOR)
    ws_path = collection / "workflow-state.json"
    original_state = json.dumps({"stage": "planning"})
    ws_path.write_text(original_state, encoding="utf-8")

    def fail_archive(_collection):
        raise ValidationError("forced archive failure")

    monkeypatch.setattr(auto_select_thumbnail, "archive_approved_thumbnail_transaction", fail_archive)

    code, captured = _run_json([str(collection), "--apply"], capsys)

    assert code == 1
    assert "forced archive failure" in captured.err
    assert not (assets / "thumbnail.jpg").exists()
    assert ws_path.read_text(encoding="utf-8") == original_state


def test_apply_converts_png_candidate_to_jpeg(tmp_path, monkeypatch, capsys):
    _setup_channel(tmp_path, monkeypatch)
    collection = _setup_collection(tmp_path)
    assets = collection / "10-assets"
    _solid_image(assets / "thumbnail-codex-v1.png", _NEAR_COLOR)

    code = main([str(collection), "--apply"])

    assert code == 0
    target = assets / "thumbnail.jpg"
    assert target.exists()
    with Image.open(target) as img:
        assert img.format == "JPEG"
    _ = capsys.readouterr()


def test_apply_without_workflow_state_reports_not_updated(tmp_path, monkeypatch, capsys):
    _setup_channel(tmp_path, monkeypatch)
    collection = _setup_collection(tmp_path)
    _solid_image(collection / "10-assets" / "thumbnail-v1.jpg", _NEAR_COLOR)

    code, captured = _run_json([str(collection), "--apply", "--json"], capsys)

    assert code == 0
    payload = json.loads(captured.out)
    assert payload["workflow_state_updated"] is False


def test_disabled_channel_errors_with_exit_2(tmp_path, monkeypatch, capsys):
    _setup_channel(tmp_path, monkeypatch, enabled=False)
    collection = _setup_collection(tmp_path)
    _solid_image(collection / "10-assets" / "thumbnail-v1.jpg", _NEAR_COLOR)

    code, captured = _run_json([str(collection), "--apply"], capsys)

    assert code == 2
    assert "auto_selection.enabled" in captured.err
    assert not (collection / "10-assets" / "thumbnail.jpg").exists()


def test_missing_enabled_defaults_to_disabled_exit_2(tmp_path, monkeypatch, capsys):
    _setup_channel(tmp_path, monkeypatch)
    channel_dir = tmp_path / "channel"
    cfg_path = channel_dir / "config" / "skills" / "thumbnail.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    del cfg["image_generation"]["auto_selection"]["enabled"]
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    skill_config.reset()
    collection = _setup_collection(tmp_path)
    _solid_image(collection / "10-assets" / "thumbnail-v1.jpg", _NEAR_COLOR)

    code, captured = _run_json([str(collection), "--apply"], capsys)

    assert code == 2
    assert "auto_selection.enabled" in captured.err
    assert not (collection / "10-assets" / "thumbnail.jpg").exists()


def test_non_bool_enabled_errors_without_bool_coercion(tmp_path, monkeypatch, capsys):
    _setup_channel(tmp_path, monkeypatch, enabled="false")
    collection = _setup_collection(tmp_path)
    _solid_image(collection / "10-assets" / "thumbnail-v1.jpg", _NEAR_COLOR)

    code, captured = _run_json([str(collection), "--dry-run"], capsys)

    assert code == 1
    assert "auto_selection.enabled は boolean" in captured.err
    assert not (collection / "10-assets" / "thumbnail.jpg").exists()


def test_force_without_apply_is_input_error(tmp_path, monkeypatch, capsys):
    _setup_channel(tmp_path, monkeypatch)
    collection = _setup_collection(tmp_path)
    _solid_image(collection / "10-assets" / "thumbnail-v1.jpg", _NEAR_COLOR)

    code, captured = _run_json([str(collection), "--dry-run", "--force"], capsys)

    assert code == 2
    assert "--force" in captured.err
    assert not (collection / "10-assets" / "thumbnail.jpg").exists()


def test_missing_collection_dir_errors_with_exit_2(tmp_path, monkeypatch, capsys):
    _setup_channel(tmp_path, monkeypatch)

    code, captured = _run_json([str(tmp_path / "no-such-collection"), "--dry-run"], capsys)

    assert code == 2
    assert "10-assets" in captured.err


def test_no_candidates_errors(tmp_path, monkeypatch, capsys):
    _setup_channel(tmp_path, monkeypatch)
    collection = _setup_collection(tmp_path)

    code, captured = _run_json([str(collection), "--dry-run"], capsys)

    assert code == 1
    assert "候補が見つかりません" in captured.err


def test_no_reference_images_errors(tmp_path, monkeypatch, capsys):
    _setup_channel(tmp_path, monkeypatch, refs=())
    collection = _setup_collection(tmp_path)
    _solid_image(collection / "10-assets" / "thumbnail-v1.jpg", _NEAR_COLOR)

    code, captured = _run_json([str(collection), "--dry-run"], capsys)

    assert code == 1
    assert "参照画像" in captured.err


def test_broken_reference_image_errors_without_traceback(tmp_path, monkeypatch, capsys):
    _setup_channel(tmp_path, monkeypatch)
    collection = _setup_collection(tmp_path)
    _solid_image(collection / "10-assets" / "thumbnail-v1.jpg", _NEAR_COLOR)
    (tmp_path / "channel" / _REF_RELPATHS[0]).write_bytes(b"not an image")

    code, captured = _run_json([str(collection), "--dry-run"], capsys)

    assert code == 1
    output = captured.out + captured.err
    assert "参照画像を読み込めません" in output
    assert "Traceback" not in output


def test_broken_candidate_image_errors_without_traceback(tmp_path, monkeypatch, capsys):
    _setup_channel(tmp_path, monkeypatch)
    collection = _setup_collection(tmp_path)
    (collection / "10-assets" / "thumbnail-v1.jpg").write_bytes(b"not an image")

    code, captured = _run_json([str(collection), "--dry-run"], capsys)

    assert code == 1
    output = captured.out + captured.err
    assert "thumbnail 候補画像を読み込めません" in output
    assert "Traceback" not in output


def test_existing_thumbnail_requires_force(tmp_path, monkeypatch, capsys):
    _setup_channel(tmp_path, monkeypatch)
    collection = _setup_collection(tmp_path)
    assets = collection / "10-assets"
    _solid_image(assets / "thumbnail-v1.jpg", _NEAR_COLOR)
    _solid_image(assets / "thumbnail.jpg", (0, 0, 0))

    code, captured = _run_json([str(collection), "--apply"], capsys)
    assert code == 1
    assert "--force" in captured.err

    code = main([str(collection), "--apply", "--force"])
    assert code == 0
    _ = capsys.readouterr()
    with Image.open(assets / "thumbnail.jpg") as img:
        # 上書き後は選択候補 (NEAR_COLOR) の内容になっている
        assert img.getpixel((0, 0))[2] > 50


def test_existing_thumbnail_symlink_is_rejected(tmp_path, monkeypatch, capsys):
    _setup_channel(tmp_path, monkeypatch)
    collection = _setup_collection(tmp_path)
    assets = collection / "10-assets"
    _solid_image(assets / "thumbnail-v1.jpg", _NEAR_COLOR)
    outside = tmp_path / "outside-thumbnail.jpg"
    outside.write_bytes(b"outside")
    try:
        (assets / "thumbnail.jpg").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    code, captured = _run_json([str(collection), "--apply", "--force"], capsys)

    assert code == 1
    assert "シンボリックリンク" in captured.err
    assert outside.read_bytes() == b"outside"


def test_workflow_state_symlink_is_rejected_before_copy(tmp_path, monkeypatch, capsys):
    _setup_channel(tmp_path, monkeypatch)
    collection = _setup_collection(tmp_path)
    _solid_image(collection / "10-assets" / "thumbnail-v1.jpg", _NEAR_COLOR)
    outside = tmp_path / "outside-state.json"
    outside.write_text("{}", encoding="utf-8")
    try:
        (collection / "workflow-state.json").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    code, captured = _run_json([str(collection), "--apply"], capsys)

    assert code == 1
    assert "workflow-state.json" in captured.err
    assert "シンボリックリンク" in captured.err
    assert not (collection / "10-assets" / "thumbnail.jpg").exists()


def test_ineligible_candidates_are_excluded(tmp_path, monkeypatch, capsys):
    _setup_channel(tmp_path, monkeypatch)
    collection = _setup_collection(tmp_path)
    assets = collection / "10-assets"
    # 参照プールに最も近いが 16:9 逸脱 + 解像度不足 → 除外され、遠い適格候補が勝つ
    _solid_image(assets / "thumbnail-v1.jpg", _NEAR_COLOR, size=(100, 100))
    _solid_image(assets / "thumbnail-v2.jpg", _FAR_COLOR)

    code, captured = _run_json([str(collection), "--dry-run", "--json"], capsys)

    assert code == 0
    payload = json.loads(captured.out)
    assert payload["selected"]["candidate"] == "thumbnail-v2.jpg"
    excluded = next(entry for entry in payload["ranking"] if entry["candidate"] == "thumbnail-v1.jpg")
    assert excluded["eligible"] is False
    assert any("16:9" in reason for reason in excluded["reasons"])
    assert any("解像度不足" in reason for reason in excluded["reasons"])


def test_all_candidates_ineligible_errors(tmp_path, monkeypatch, capsys):
    _setup_channel(tmp_path, monkeypatch)
    collection = _setup_collection(tmp_path)
    _solid_image(collection / "10-assets" / "thumbnail-v1.jpg", _NEAR_COLOR, size=(100, 100))

    code, captured = _run_json([str(collection), "--apply"], capsys)

    assert code == 1
    assert "適格候補がありません" in captured.err
    assert not (collection / "10-assets" / "thumbnail.jpg").exists()


def test_broken_workflow_state_fails_before_copy(tmp_path, monkeypatch, capsys):
    _setup_channel(tmp_path, monkeypatch)
    collection = _setup_collection(tmp_path)
    _solid_image(collection / "10-assets" / "thumbnail-v1.jpg", _NEAR_COLOR)
    (collection / "workflow-state.json").write_text("{not json", encoding="utf-8")

    code, captured = _run_json([str(collection), "--apply"], capsys)

    assert code == 1
    assert "workflow-state.json" in captured.err
    # 副作用前に検出するので thumbnail.jpg は作られない
    assert not (collection / "10-assets" / "thumbnail.jpg").exists()


def test_non_object_workflow_state_fails_before_copy(tmp_path, monkeypatch, capsys):
    _setup_channel(tmp_path, monkeypatch)
    collection = _setup_collection(tmp_path)
    _solid_image(collection / "10-assets" / "thumbnail-v1.jpg", _NEAR_COLOR)
    (collection / "workflow-state.json").write_text("[]", encoding="utf-8")

    code, captured = _run_json([str(collection), "--apply"], capsys)

    assert code == 1
    assert "root は object" in captured.err
    assert not (collection / "10-assets" / "thumbnail.jpg").exists()


def test_state_record_failure_rolls_back_thumbnail(tmp_path, monkeypatch, capsys):
    _setup_channel(tmp_path, monkeypatch)
    collection = _setup_collection(tmp_path)
    assets = collection / "10-assets"
    _solid_image(assets / "thumbnail-v1.jpg", _NEAR_COLOR)
    (collection / "workflow-state.json").write_text(json.dumps({"stage": "planning"}), encoding="utf-8")

    def fail_record(*args, **kwargs):
        raise ValidationError("forced state write failure")

    monkeypatch.setattr(auto_select_thumbnail, "record_workflow_state", fail_record)

    code, captured = _run_json([str(collection), "--apply"], capsys)

    assert code == 1
    assert "forced state write failure" in captured.err
    assert not (assets / "thumbnail.jpg").exists()


def test_state_record_failure_with_archive_restores_thumbnail_gallery_and_state(tmp_path, monkeypatch, capsys):
    channel_dir = _setup_channel(tmp_path, monkeypatch, archive_config=_ARCHIVE_ENABLED)
    collection = channel_dir / "collections" / "planning" / "20260701-tst-state-rollback"
    assets = collection / "10-assets"
    assets.mkdir(parents=True)
    _solid_image(assets / "thumbnail-v1.jpg", _NEAR_COLOR)
    _solid_image(assets / "thumbnail.png", _FAR_COLOR)
    original_thumbnail = (assets / "thumbnail.png").read_bytes()
    ws_path = collection / "workflow-state.json"
    original_state = json.dumps({"stage": "planning"})
    ws_path.write_text(original_state, encoding="utf-8")
    auto_select_thumbnail.archive_approved_thumbnail_transaction(collection)
    archived = channel_dir / "assets" / "thumbnail-gallery" / f"{collection.name}.png"
    original_archive = archived.read_bytes()

    def fail_record(*args, **kwargs):
        raise ValidationError("forced state write failure")

    monkeypatch.setattr(auto_select_thumbnail, "record_workflow_state", fail_record)

    code, captured = _run_json([str(collection), "--apply", "--force"], capsys)

    assert code == 1
    assert "forced state write failure" in captured.err
    assert (assets / "thumbnail.png").read_bytes() == original_thumbnail
    assert not (assets / "thumbnail.jpg").exists()
    assert archived.read_bytes() == original_archive
    assert not archived.with_suffix(".jpg").exists()
    assert ws_path.read_text(encoding="utf-8") == original_state


def test_state_record_failure_preserves_preexisting_empty_channel_assets(tmp_path, monkeypatch, capsys):
    channel_dir = _setup_channel(tmp_path, monkeypatch, archive_config=_ARCHIVE_ENABLED)
    channel_assets = channel_dir / "assets"
    channel_assets.mkdir()
    collection = channel_dir / "collections" / "planning" / "20260701-tst-assets-rollback"
    assets = collection / "10-assets"
    assets.mkdir(parents=True)
    _solid_image(assets / "thumbnail-v1.jpg", _NEAR_COLOR)
    ws_path = collection / "workflow-state.json"
    original_state = json.dumps({"stage": "planning"})
    ws_path.write_text(original_state, encoding="utf-8")

    def fail_record(*args, **kwargs):
        raise ValidationError("forced state write failure")

    monkeypatch.setattr(auto_select_thumbnail, "record_workflow_state", fail_record)

    code, captured = _run_json([str(collection), "--apply"], capsys)

    assert code == 1
    assert "forced state write failure" in captured.err
    assert channel_assets.is_dir()
    assert list(channel_assets.iterdir()) == []
    assert not (assets / "thumbnail.jpg").exists()
    assert ws_path.read_text(encoding="utf-8") == original_state


def test_thumbnail_rollback_failure_still_restores_gallery_and_state(tmp_path, monkeypatch, capsys):
    channel_dir = _setup_channel(tmp_path, monkeypatch, archive_config=_ARCHIVE_ENABLED)
    collection = channel_dir / "collections" / "planning" / "20260701-tst-partial-rollback"
    assets = collection / "10-assets"
    assets.mkdir(parents=True)
    _solid_image(assets / "thumbnail-v1.jpg", _NEAR_COLOR)
    _solid_image(assets / "thumbnail.jpg", _FAR_COLOR)
    ws_path = collection / "workflow-state.json"
    original_state = json.dumps({"stage": "planning"})
    ws_path.write_text(original_state, encoding="utf-8")
    auto_select_thumbnail.archive_approved_thumbnail_transaction(collection)
    archived = channel_dir / "assets" / "thumbnail-gallery" / f"{collection.name}.jpg"
    original_archive = archived.read_bytes()
    real_write_bytes = Path.write_bytes

    def fail_record(*args, **kwargs):
        raise ValidationError("forced state write failure")

    def fail_thumbnail_restore(path, content):
        if path == assets / "thumbnail.jpg":
            raise OSError("forced thumbnail rollback failure")
        return real_write_bytes(path, content)

    monkeypatch.setattr(auto_select_thumbnail, "record_workflow_state", fail_record)
    monkeypatch.setattr(Path, "write_bytes", fail_thumbnail_restore)

    code, captured = _run_json([str(collection), "--apply", "--force"], capsys)

    assert code == 1
    assert "forced thumbnail rollback failure" in captured.err
    assert "Traceback" not in captured.err
    assert archived.read_bytes() == original_archive
    assert ws_path.read_text(encoding="utf-8") == original_state


def test_gallery_rollback_failure_still_restores_old_archive_thumbnail_and_state(tmp_path, monkeypatch, capsys):
    channel_dir = _setup_channel(tmp_path, monkeypatch, archive_config=_ARCHIVE_ENABLED)
    collection = channel_dir / "collections" / "planning" / "20260701-tst-gallery-partial-rollback"
    assets = collection / "10-assets"
    assets.mkdir(parents=True)
    _solid_image(assets / "thumbnail-v1.jpg", _NEAR_COLOR)
    _solid_image(assets / "thumbnail.png", _FAR_COLOR)
    original_thumbnail = (assets / "thumbnail.png").read_bytes()
    ws_path = collection / "workflow-state.json"
    original_state = json.dumps({"stage": "planning"})
    ws_path.write_text(original_state, encoding="utf-8")
    auto_select_thumbnail.archive_approved_thumbnail_transaction(collection)
    old_archive = channel_dir / "assets" / "thumbnail-gallery" / f"{collection.name}.png"
    new_archive = old_archive.with_suffix(".jpg")
    original_archive = old_archive.read_bytes()
    real_unlink = Path.unlink

    def fail_record(*args, **kwargs):
        raise ValidationError("forced state write failure")

    def fail_new_archive_unlink(path, **kwargs):
        if path == new_archive:
            raise OSError("forced first gallery rollback failure")
        return real_unlink(path, **kwargs)

    monkeypatch.setattr(auto_select_thumbnail, "record_workflow_state", fail_record)
    monkeypatch.setattr(Path, "unlink", fail_new_archive_unlink)

    code, captured = _run_json([str(collection), "--apply", "--force"], capsys)

    assert code == 1
    assert "forced first gallery rollback failure" in captured.err
    assert "Traceback" not in captured.err
    assert old_archive.read_bytes() == original_archive
    assert new_archive.exists()
    assert (assets / "thumbnail.png").read_bytes() == original_thumbnail
    assert not (assets / "thumbnail.jpg").exists()
    assert ws_path.read_text(encoding="utf-8") == original_state


def test_state_temp_cleanup_failure_is_domain_error_and_restores_all_states(tmp_path, monkeypatch, capsys):
    channel_dir = _setup_channel(tmp_path, monkeypatch, archive_config=_ARCHIVE_ENABLED)
    collection = channel_dir / "collections" / "planning" / "20260701-tst-state-temp-cleanup"
    assets = collection / "10-assets"
    assets.mkdir(parents=True)
    _solid_image(assets / "thumbnail-v1.jpg", _NEAR_COLOR)
    _solid_image(assets / "thumbnail.png", _FAR_COLOR)
    original_thumbnail = (assets / "thumbnail.png").read_bytes()
    ws_path = collection / "workflow-state.json"
    original_state = json.dumps({"stage": "planning"})
    ws_path.write_text(original_state, encoding="utf-8")
    auto_select_thumbnail.archive_approved_thumbnail_transaction(collection)
    old_archive = channel_dir / "assets" / "thumbnail-gallery" / f"{collection.name}.png"
    original_archive = old_archive.read_bytes()
    real_replace = auto_select_thumbnail.os.replace
    real_unlink = Path.unlink
    state_temporary = None

    def fail_state_replace(source, destination):
        if Path(destination) == ws_path:
            raise OSError("forced state replace failure")
        return real_replace(source, destination)

    def fail_state_temporary_unlink(path, **kwargs):
        nonlocal state_temporary
        if path.name.startswith(".workflow-state-"):
            state_temporary = path
            raise OSError("forced state temporary cleanup failure")
        return real_unlink(path, **kwargs)

    monkeypatch.setattr(auto_select_thumbnail.os, "replace", fail_state_replace)
    monkeypatch.setattr(Path, "unlink", fail_state_temporary_unlink)

    code, captured = _run_json([str(collection), "--apply", "--force"], capsys)

    assert code == 1
    assert "forced state replace failure" in captured.err
    assert "forced state temporary cleanup failure" in captured.err
    assert "Traceback" not in captured.err
    assert old_archive.read_bytes() == original_archive
    assert not old_archive.with_suffix(".jpg").exists()
    assert (assets / "thumbnail.png").read_bytes() == original_thumbnail
    assert not (assets / "thumbnail.jpg").exists()
    assert ws_path.read_text(encoding="utf-8") == original_state
    assert state_temporary is not None
    real_unlink(state_temporary)


def test_feature_centroid_handles_circular_hue():
    base = {"brightness": 100.0, "contrast": 10.0, "saturation": 100.0, "colorfulness": 10.0}
    centroid = feature_centroid(
        [
            {**base, "dominant_hue": 250.0},
            {**base, "dominant_hue": 6.0},
        ]
    )
    # 250 と 6 の循環平均は 0 付近 (算術平均の 128 ではない)
    assert centroid["dominant_hue"] < 10 or centroid["dominant_hue"] > 246

    near = {**base, "dominant_hue": 2.0}
    far = {**base, "dominant_hue": 128.0}
    assert feature_distance(near, centroid) < feature_distance(far, centroid)
