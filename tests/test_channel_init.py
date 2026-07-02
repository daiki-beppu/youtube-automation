"""yt-channel-init CLI のユニット / 結合テスト (tmp_path ベース).

設計参考: `tests/test_config_migrate.py` のスタイルを踏襲する。
- `_auto_reset` autouse fixture で `CHANNEL_DIR` を外し、新 loader シングルトンをリセット。
- `main(argv)` 直接呼び出し → 戻り値 `rc` と stdout/stderr を assert。
- 期待 JSON は読み戻して scalar 値と必須キー存在を中心に検証 (DRY)。
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
import yaml

from youtube_automation.cli.channel_init import (
    _resolve_target_dir,
    main,
)
from youtube_automation.utils.channel_settings import build_update_body
from youtube_automation.utils.config import load_config
from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.metadata_generator import validate_scene_phrases

# ----------------------- Fixtures / constants -----------------------


CHANNEL_DIR_FILES: tuple[str, ...] = (
    "meta.json",
    "content.json",
    "youtube.json",
    "analytics.json",
    "playlists.json",
    "workflow.json",
    "audio.json",
)

GITKEEP_DIRS: tuple[str, ...] = (
    "auth",
    "branding",
    "collections",
    "data",
    "docs/channel/personas",
    "docs/benchmarks",
    "research",
)

PACKAGE_FILES: tuple[str, ...] = (
    ".env",
    ".gitignore",
    "auth/client_secrets.template.json",
    "config/localizations.json",
    "config/schedule_config.json",
    "config/skills/suno.yaml",
    "config/skills/thumbnail.yaml",
)


@pytest.fixture(autouse=True)
def _auto_reset(monkeypatch):
    """conftest が向ける `CHANNEL_DIR` を毎テスト前後にクリア + 新 loader シングルトンをリセット."""
    monkeypatch.delenv("CHANNEL_DIR", raising=False)
    from youtube_automation.utils.config import reset as reset_config

    reset_config()
    yield
    reset_config()


# ----------------------- Helpers -----------------------


def _required_args(
    target: Path,
    *,
    short: str = "DEMO",
    name: str = "Demo Channel",
    extra: list[str] | None = None,
) -> list[str]:
    """必須引数を組み立てた argv リストを返す."""
    argv = ["--target", str(target), "--short", short, "--name", name]
    if extra:
        argv.extend(extra)
    return argv


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _channel_dir(target: Path) -> Path:
    return target / "config" / "channel"


# ===================== Case 1: 7 config ファイル全件生成 =====================


def test_main_creates_all_config_files_when_target_is_empty(tmp_path):
    # Given: 空のターゲットディレクトリ
    # When: 必須引数のみで main を実行
    rc = main(_required_args(tmp_path))

    # Then: rc=0 で 7 ファイル全てが生成される
    assert rc == 0
    channel_dir = _channel_dir(tmp_path)
    for name in CHANNEL_DIR_FILES:
        assert (channel_dir / name).is_file(), f"missing config file: {name}"


# ===================== Case 2: setup-owned ディレクトリは生成しない =====================


def test_main_does_not_create_setup_owned_directories_when_target_is_empty(tmp_path):
    # Given: 空のターゲットディレクトリ
    # When: main を実行
    rc = main(_required_args(tmp_path))

    # Then: /setup が所有する空ディレクトリは生成しない
    assert rc == 0
    assert not (tmp_path / "collections").exists()
    assert not (tmp_path / "data").exists()
    assert not (tmp_path / "docs").exists()
    assert not (tmp_path / "research").exists()
    assert not (tmp_path / "auth" / ".gitkeep").exists()


# ===================== Case 3: --short / --name が meta.json に反映 =====================


def test_meta_json_reflects_short_and_name_args(tmp_path):
    # Given: --short / --name を指定
    # When: main を実行
    rc = main(_required_args(tmp_path, short="ABC", name="Awesome BGM"))

    # Then: meta.json の channel.name / channel.short に反映される
    assert rc == 0
    meta = _read_json(_channel_dir(tmp_path) / "meta.json")
    assert meta["channel"]["name"] == "Awesome BGM"
    assert meta["channel"]["short"] == "ABC"
    assert meta["channel"]["channel_id"] == ""


# ===================== Case 4: --genre / --style / --context が content.json に反映 =====================


def test_content_json_reflects_genre_style_context_args(tmp_path):
    # Given: --genre / --style / --context を明示指定
    extra = ["--genre", "chiptune", "--style", "8-bit", "--context", "RPG"]

    # When: main を実行
    rc = main(_required_args(tmp_path, extra=extra))

    # Then: content.json の genre セクションに反映
    assert rc == 0
    content = _read_json(_channel_dir(tmp_path) / "content.json")
    assert content["genre"]["primary"] == "chiptune"
    assert content["genre"]["style"] == "8-bit"
    assert content["genre"]["context"] == "RPG"


# ===================== Case 5: genre/style/context のデフォルト "TBD" =====================


def test_content_json_uses_tbd_defaults_when_genre_style_context_omitted(tmp_path):
    # Given: --genre / --style / --context を省略
    # When: main を実行
    rc = main(_required_args(tmp_path))

    # Then: 3 つとも "TBD" が入る
    assert rc == 0
    content = _read_json(_channel_dir(tmp_path) / "content.json")
    assert content["genre"]["primary"] == "TBD"
    assert content["genre"]["style"] == "TBD"
    assert content["genre"]["context"] == "TBD"


# ===================== Case 6: youtube.json 既定値 =====================


def test_youtube_json_has_expected_defaults(tmp_path):
    # Given/When: 通常実行
    rc = main(_required_args(tmp_path))

    # Then: SKILL.md Step 4 と同等の固定値
    assert rc == 0
    youtube = _read_json(_channel_dir(tmp_path) / "youtube.json")
    assert youtube["youtube"]["category_id"] == "10"
    assert youtube["youtube"]["privacy_status"] == "public"
    assert youtube["youtube"]["language"] == "en"
    assert youtube["music_engine"] == "suno"


def test_music_engine_arg_is_written_to_youtube_json(tmp_path):
    # Given: TTP ヒアリングで Lyria をデフォルト音楽エンジンに決めた
    extra = ["--music-engine", "lyria"]

    # When: main を実行
    rc = main(_required_args(tmp_path, extra=extra))

    # Then: youtube.json の music_engine に反映される
    assert rc == 0
    youtube = _read_json(_channel_dir(tmp_path) / "youtube.json")
    assert youtube["music_engine"] == "lyria"


# ===================== Case 7: analytics.json benchmark セクションの既定 =====================


def test_analytics_json_has_default_benchmark_parameters(tmp_path):
    # Given/When: 通常実行
    rc = main(_required_args(tmp_path))

    # Then: benchmark セクションに SKILL.md Step 4 と同等のキーが揃う
    assert rc == 0
    analytics = _read_json(_channel_dir(tmp_path) / "analytics.json")
    bm = analytics["benchmark"]
    assert bm["channels"] == []
    assert "scan_recent" in bm
    assert "min_views" in bm
    assert "freshness_days" in bm
    assert "gemini_thumbnail_analysis" in bm


# ===================== Case 8: playlists / workflow / audio は空テンプレ =====================


def test_empty_template_files_are_generated_as_valid_json(tmp_path):
    # Given/When: 通常実行
    rc = main(_required_args(tmp_path))

    # Then: 3 ファイルとも json.loads 可能
    assert rc == 0
    for name in ("playlists.json", "workflow.json", "audio.json"):
        path = _channel_dir(tmp_path) / name
        assert path.is_file()
        data = _read_json(path)
        assert isinstance(data, dict)


def test_main_creates_full_package_files_when_target_is_empty(tmp_path):
    # Given: 空のターゲットディレクトリ
    # When: main を実行
    rc = main(_required_args(tmp_path))

    # Then: config/channel 以外の初期運用ファイルも生成される
    assert rc == 0
    for rel in PACKAGE_FILES:
        assert (tmp_path / rel).is_file(), f"missing package file: {rel}"
    assert not (tmp_path / "config" / "upload_settings.json").exists()

    schedule = _read_json(tmp_path / "config" / "schedule_config.json")
    assert schedule["upload_settings"]["category_id"] == "10"
    assert schedule["upload_settings"]["privacy_status"] == "private"


def test_main_does_not_generate_distrokid_json_by_default(tmp_path, monkeypatch):
    # Given: DistroKid 配信を opt-in しない新チャンネル
    # When: main を実行
    rc = main(_required_args(tmp_path))

    # Then: distrokid.json は生成せず、loader の未配置 default で disabled として扱われる
    assert rc == 0
    assert not (_channel_dir(tmp_path) / "distrokid.json").exists()

    monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))
    config = load_config()
    assert config.distrokid.enabled is False


def test_distrokid_enabled_args_generate_distrokid_json(tmp_path, monkeypatch):
    # Given: channel-new ヒアリングで DistroKid 配信を行うと決めた
    extra = [
        "--distrokid-enabled",
        "--distrokid-artist",
        "Demo Artist",
        "--distrokid-language",
        "ja",
        "--distrokid-main-genre",
        "Electronic",
        "--distrokid-sub-genre",
        "House",
        "--distrokid-songwriter-first",
        "Jane",
        "--distrokid-songwriter-last",
        "Doe",
    ]

    # When: main を実行
    rc = main(_required_args(tmp_path, extra=extra))

    # Then: 既存 utils.config.distrokid と同じ nested schema で生成される
    assert rc == 0
    distrokid = _read_json(_channel_dir(tmp_path) / "distrokid.json")["distrokid"]
    assert distrokid == {
        "enabled": True,
        "profile": {
            "artist": "Demo Artist",
            "language": "ja",
            "main_genre": "Electronic",
            "sub_genre": "House",
            "songwriter": {"first": "Jane", "last": "Doe"},
        },
    }

    monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))
    config = load_config()
    assert config.distrokid.enabled is True
    assert config.distrokid.profile.artist == "Demo Artist"
    assert config.distrokid.profile.language == "ja"
    assert config.distrokid.profile.main_genre == "Electronic"
    assert config.distrokid.profile.sub_genre == "House"
    assert config.distrokid.profile.songwriter is not None
    assert config.distrokid.profile.songwriter.first == "Jane"
    assert config.distrokid.profile.songwriter.last == "Doe"


def test_distrokid_enabled_accepts_minimal_profile(tmp_path, monkeypatch):
    # Given: DistroKid 配信に必要な最小 profile だけを指定
    extra = [
        "--distrokid-enabled",
        "--distrokid-artist",
        "Demo Artist",
        "--distrokid-language",
        "ja",
        "--distrokid-main-genre",
        "Electronic",
    ]

    # When: main を実行
    rc = main(_required_args(tmp_path, extra=extra))

    # Then: optional profile を推測で埋めず、指定値だけで生成される
    assert rc == 0
    distrokid = _read_json(_channel_dir(tmp_path) / "distrokid.json")["distrokid"]
    assert distrokid == {
        "enabled": True,
        "profile": {"artist": "Demo Artist", "language": "ja", "main_genre": "Electronic"},
    }

    monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))
    config = load_config()
    assert config.distrokid.enabled is True
    assert config.distrokid.profile.artist == "Demo Artist"
    assert config.distrokid.profile.language == "ja"
    assert config.distrokid.profile.main_genre == "Electronic"
    assert config.distrokid.profile.sub_genre is None
    assert config.distrokid.profile.songwriter is None


def test_distrokid_enabled_requires_artist_language_and_main_genre(tmp_path, capsys):
    # Given: DistroKid 配信を opt-in するが必須 profile を省略
    argv = _required_args(tmp_path, extra=["--distrokid-enabled"])

    # When/Then: 推測 default で埋めず argparse がエラー終了し、scaffold は作成されない
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2
    assert "--distrokid-artist, --distrokid-language, --distrokid-main-genre" in capsys.readouterr().err
    assert not (tmp_path / "config").exists()


def test_distrokid_profile_args_require_enabled_flag(tmp_path, capsys):
    # Given: DistroKid を opt-in せずに profile 引数だけ指定
    argv = _required_args(tmp_path, extra=["--distrokid-artist", "Demo Artist"])

    # When/Then: argparse がエラー終了し、scaffold は作成されない
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2
    assert "--distrokid-enabled が必要です" in capsys.readouterr().err
    assert not (tmp_path / "config").exists()


def test_distrokid_songwriter_first_and_last_must_be_set_together(tmp_path, capsys):
    # Given: songwriter の片方だけを指定
    argv = _required_args(
        tmp_path,
        extra=[
            "--distrokid-enabled",
            "--distrokid-artist",
            "Demo Artist",
            "--distrokid-language",
            "ja",
            "--distrokid-main-genre",
            "Electronic",
            "--distrokid-songwriter-first",
            "Jane",
        ],
    )

    # When/Then: argparse がエラー終了し、scaffold は作成されない
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2
    assert "--distrokid-songwriter-first と --distrokid-songwriter-last" in capsys.readouterr().err
    assert not (tmp_path / "config").exists()


def test_distrokid_profile_args_reject_blank_values(tmp_path):
    # Given: DistroKid 必須 profile に空白だけの値を指定
    argv = _required_args(
        tmp_path,
        extra=[
            "--distrokid-enabled",
            "--distrokid-artist",
            "Demo Artist",
            "--distrokid-language",
            "ja",
            "--distrokid-main-genre",
            "   ",
        ],
    )

    # When/Then: parser type が拒否し、scaffold は作成されない
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2
    assert not (tmp_path / "config").exists()


def test_benchmark_channel_args_are_written_to_analytics_json(tmp_path):
    # Given: TTP ベンチマーク対象を 2 件指定
    extra = [
        "--benchmark-channel",
        "UC111|alpha|Alpha Channel|title structure",
        "--benchmark-channel",
        "UC222|beta|Beta Channel|thumbnail composition",
    ]

    # When: main を実行
    rc = main(_required_args(tmp_path, extra=extra))

    # Then: analytics.json の benchmark.channels に順序通り反映される
    assert rc == 0
    analytics = _read_json(_channel_dir(tmp_path) / "analytics.json")
    assert analytics["benchmark"]["channels"] == [
        {
            "id": "UC111",
            "slug": "alpha",
            "name": "Alpha Channel",
            "relationship": "title structure",
        },
        {
            "id": "UC222",
            "slug": "beta",
            "name": "Beta Channel",
            "relationship": "thumbnail composition",
        },
    ]


def test_benchmark_channel_second_run_without_force_keeps_existing_analytics_json(tmp_path, capsys):
    # Given: 初回生成済みで analytics.json の benchmark.channels は空
    assert main(_required_args(tmp_path)) == 0
    capsys.readouterr()

    # When: --force なしで benchmark だけを追加指定して再実行
    rc = main(
        _required_args(
            tmp_path,
            extra=["--benchmark-channel", "UC111|alpha|Alpha Channel|title structure"],
        )
    )
    captured = capsys.readouterr()

    # Then: 既存 analytics.json は保持され、差分だけが提示される
    assert rc == 0
    analytics = _read_json(_channel_dir(tmp_path) / "analytics.json")
    assert analytics["benchmark"]["channels"] == []
    assert "config/channel/analytics.json (existing)" in captured.err


def test_branding_args_are_written_to_meta_json(tmp_path):
    # Given: YouTube branding 初期値を指定
    extra = [
        "--branding-description",
        "A channel description copied from TTP structure.",
        "--channel-keyword",
        "focus music",
        "--channel-keyword",
        "ambient bgm",
        "--country",
        "JP",
        "--default-language",
        "en",
    ]

    # When: main を実行
    rc = main(_required_args(tmp_path, extra=extra))

    # Then: meta.json の youtube_channel セクションに反映される
    assert rc == 0
    meta = _read_json(_channel_dir(tmp_path) / "meta.json")
    branding = meta["youtube_channel"]
    assert branding["description"] == "A channel description copied from TTP structure."
    assert branding["keywords"] == ["focus music", "ambient bgm"]
    assert branding["country"] == "JP"
    assert branding["default_language"] == "en"


# ===================== Case: --core-message が meta.json に反映 =====================


def test_core_message_arg_is_written_to_meta_json(tmp_path):
    # Given: --core-message を明示指定
    extra = ["--core-message", "Your daily dose of ambient focus"]

    # When: main を実行
    rc = main(_required_args(tmp_path, extra=extra))

    # Then: meta.json の channel.core_message / channel.tagline に反映される
    assert rc == 0
    meta = _read_json(_channel_dir(tmp_path) / "meta.json")
    assert meta["channel"]["core_message"] == "Your daily dose of ambient focus"
    assert meta["channel"]["tagline"] == "Your daily dose of ambient focus"
    # cta_subscribe は genre から導出される（--genre 省略時は "TBD"）
    assert "TBD" in meta["channel"]["cta_subscribe"]


def test_audio_duration_args_are_written_to_audio_json(tmp_path, monkeypatch):
    # Given: 動画尺の初期値（分）を指定
    extra = ["--target-duration-min", "90", "--target-duration-max", "180"]

    # When: main を実行
    rc = main(_required_args(tmp_path, extra=extra))

    # Then: audio.json の audio セクションに分単位で反映される
    assert rc == 0
    audio = _read_json(_channel_dir(tmp_path) / "audio.json")
    assert audio["audio"]["target_duration_min"] == 90.0
    assert audio["audio"]["target_duration_max"] == 180.0

    monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))
    config = load_config()
    assert config.audio.target_duration_min == 90.0
    assert config.audio.target_duration_max == 180.0


@pytest.mark.parametrize(
    ("extra", "expected_message"),
    (
        (["--target-duration-min", "0"], "--target-duration-min は 1 以上を指定してください"),
        (["--target-duration-max", "0"], "--target-duration-max は 1 以上を指定してください"),
        (
            ["--target-duration-min", "180", "--target-duration-max", "90"],
            "--target-duration-min は --target-duration-max 以下を指定してください",
        ),
    ),
)
def test_invalid_audio_duration_args_exit_before_writing_files(tmp_path, capsys, extra, expected_message):
    # Given: audio.target_duration_min/max として不正な値
    argv = _required_args(tmp_path, extra=extra)

    # When/Then: argparse がエラー終了し、scaffold は作成されない
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2
    assert expected_message in capsys.readouterr().err
    assert not (tmp_path / "config").exists()


def test_localizations_and_skill_configs_reflect_channel_init_args(tmp_path):
    # Given: フルパッケージ生成に使う TTP 初期値を指定
    extra = [
        "--genre",
        "ambient",
        "--style",
        "warm lo-fi",
        "--context",
        "late-night study",
        "--benchmark-channel",
        "UC111|alpha|Alpha Channel|title structure",
        "--default-language",
        "ja",
    ]

    # When: main を実行
    rc = main(_required_args(tmp_path, name="Focus Atlas", extra=extra))

    # Then: localizations と skill config に同じ初期値が反映される
    assert rc == 0
    localizations = _read_json(tmp_path / "config" / "localizations.json")
    assert localizations["default_language"] == "ja"
    assert localizations["supported_languages"] == ["ja", "en", "de"]
    assert "warm lo-fi ambient music." in localizations["languages"]["en"]["description_opening"]
    assert localizations["en"]["title"] == "Focus Atlas"

    youtube = _read_json(_channel_dir(tmp_path) / "youtube.json")
    assert youtube["content_model"]["languages"] == localizations["supported_languages"]

    meta = _read_json(_channel_dir(tmp_path) / "meta.json")
    body = build_update_body(meta["youtube_channel"], localizations, channel_id="UCabc")
    assert body["localizations"]["en_US"]["title"] == "Focus Atlas"

    suno = yaml.safe_load((tmp_path / "config" / "skills" / "suno.yaml").read_text(encoding="utf-8"))
    assert suno["workspace_name"] == "Focus Atlas"
    assert suno["genre_line"] == "warm lo-fi ambient music for late-night study"

    thumbnail = yaml.safe_load((tmp_path / "config" / "skills" / "thumbnail.yaml").read_text(encoding="utf-8"))
    reference_images = thumbnail["image_generation"]["gemini"]["reference_images"]
    assert (
        reference_images["notes"]
        == "TTP benchmarks: 1 channel(s); channel branding references are reference-only, not reusable assets"
    )
    assert reference_images["channel_branding"] == {
        "snapshot": "docs/channel/competitor-branding-snapshot.json",
        "icon_references": [],
        "banner_references": [],
        "output_icon": "branding/icon.png",
        "output_banner": "branding/banner.png",
    }
    assert thumbnail["image_generation"]["gemini"]["composition_rules"]["channel_branding"] == "Focus Atlas"


def test_channel_init_does_not_generate_legacy_upload_settings_file(tmp_path):
    """#1310: channel init は旧 root upload settings で main.* 探索契約を配らない。"""
    rc = main(_required_args(tmp_path))

    assert rc == 0
    assert not (tmp_path / "config" / "upload_settings.json").exists()


def test_channel_setup_legacy_upload_settings_template_is_removed() -> None:
    """#1310: sync で配布する旧 upload settings template を復活させない。"""
    template_path = (
        Path(__file__).resolve().parents[1]
        / ".claude"
        / "skills"
        / "channel-setup"
        / "references"
        / "upload-settings-template.json"
    )

    assert not template_path.exists()


def test_supported_language_args_are_written_to_youtube_and_localizations(tmp_path):
    # Given: TTP 対象が en-only のため localizations を 1 言語に絞る
    extra = [
        "--default-language",
        "en",
        "--supported-language",
        "en",
    ]

    # When: main を実行
    rc = main(_required_args(tmp_path, name="English Only BGM", extra=extra))

    # Then: supported languages を参照する生成物が同じ en-only セットになる
    assert rc == 0
    localizations = _read_json(tmp_path / "config" / "localizations.json")
    assert localizations["supported_languages"] == ["en"]
    assert localizations["default_language"] == "en"
    assert set(localizations["languages"].keys()) == {"en"}
    assert "en" in localizations
    assert "ja" not in localizations
    assert "de" not in localizations

    youtube = _read_json(_channel_dir(tmp_path) / "youtube.json")
    assert youtube["content_model"]["languages"] == ["en"]

    meta = _read_json(_channel_dir(tmp_path) / "meta.json")
    body = build_update_body(meta["youtube_channel"], localizations, channel_id="UCabc")
    assert set(body["localizations"].keys()) == {"en_US"}


def test_generated_localization_title_templates_match_metadata_contract(tmp_path, monkeypatch):
    # Given: channel-new 初期化と同じ経路で localizations.json を生成する
    assert main(_required_args(tmp_path, extra=["--genre", "ambient {focus}"])) == 0

    # When: scaffold 生成物を loader 経由で読み込み、metadata の事前検証を実行する
    monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))
    config = load_config()
    scene_phrases = {lang: f"{lang} quiet study room" for lang in config.localizations.supported_languages}
    violations = validate_scene_phrases(scene_phrases, config)

    # Then: localizations の title_template は scene_phrase 契約で format できる
    assert violations == []


def test_invalid_benchmark_channel_arg_exits_before_writing_files(tmp_path):
    # Given: separator 要素が足りない TTP ベンチマーク対象
    argv = _required_args(tmp_path, extra=["--benchmark-channel", "UC111|alpha|Alpha Channel"])

    # When/Then: argparse がエラー終了し、scaffold は作成されない
    with pytest.raises(SystemExit):
        main(argv)
    assert not (tmp_path / "config").exists()


# ===================== Case 9: stdout サマリーに created ラベル =====================


def test_stdout_summary_lists_created_files_only(tmp_path, capsys):
    # Given: 空のターゲット
    # When: main 実行
    rc = main(_required_args(tmp_path))
    out = capsys.readouterr().out

    # Then: サマリーに各ファイル名 + created ラベル
    assert rc == 0
    assert "created" in out
    # 代表的なファイル名が出力され、setup-owned directory は出力されない
    assert "meta.json" in out
    assert "analytics.json" in out
    assert "auth/client_secrets.template.json" in out
    assert "docs/benchmarks" not in out


# ===================== Case 10: 冪等性（2 回実行で skip） =====================


def test_main_is_idempotent_and_skips_existing_files_on_second_run(tmp_path, capsys):
    # Given: 1 回目で全て作成済み
    assert main(_required_args(tmp_path)) == 0
    capsys.readouterr()  # clear

    # When: 同じ引数で 2 回目を実行
    rc = main(_required_args(tmp_path))
    out = capsys.readouterr().out

    # Then: rc=0、サマリーは skip 主体
    assert rc == 0
    assert "skip" in out
    # 既存ファイルは内容が壊れていない
    meta = _read_json(_channel_dir(tmp_path) / "meta.json")
    assert meta["channel"]["name"] == "Demo Channel"


# ===================== Case 11: --force で既存ファイルを上書き =====================


def test_force_flag_overwrites_existing_files_with_new_values(tmp_path):
    # Given: 1 回目で "Old Name" 生成
    assert main(_required_args(tmp_path, name="Old Name")) == 0
    meta1 = _read_json(_channel_dir(tmp_path) / "meta.json")
    assert meta1["channel"]["name"] == "Old Name"

    # When: --force 付きで "New Name" を指定
    rc = main(_required_args(tmp_path, name="New Name", extra=["--force"]))

    # Then: rc=0、meta.json が上書きされる
    assert rc == 0
    meta2 = _read_json(_channel_dir(tmp_path) / "meta.json")
    assert meta2["channel"]["name"] == "New Name"


# ===================== Case 12: 日本語 --name が UTF-8 raw 出力 =====================


def test_japanese_name_is_written_as_raw_utf8(tmp_path):
    # Given: 日本語の --name
    name = "テストチャンネル"

    # When: main 実行
    rc = main(_required_args(tmp_path, name=name))

    # Then: ファイルテキストに raw UTF-8、末尾改行付き、json.loads 可
    assert rc == 0
    path = _channel_dir(tmp_path) / "meta.json"
    text = path.read_text(encoding="utf-8")
    assert name in text  # raw UTF-8（\uXXXX エスケープではない）
    assert text.endswith("\n"), "末尾改行が必要"
    data = json.loads(text)
    assert data["channel"]["name"] == name


# ===================== Case 13: CHANNEL_DIR 環境変数からターゲット解決 =====================


def test_target_resolves_from_channel_dir_env_var(tmp_path, monkeypatch):
    # Given: CHANNEL_DIR 環境変数を tmp_path に設定、--target は省略
    monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))

    # When: --target なしで main 実行
    rc = main(["--short", "DEMO", "--name", "Demo Channel"])

    # Then: tmp_path 配下に生成される
    assert rc == 0
    assert (_channel_dir(tmp_path) / "meta.json").is_file()


# ===================== Case 14: CWD からターゲット解決 =====================


def test_target_resolves_from_cwd_when_target_and_env_omitted(tmp_path, monkeypatch):
    # Given: CWD を tmp_path に変更、--target / CHANNEL_DIR とも省略
    monkeypatch.delenv("CHANNEL_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    # When: --target なしで main 実行
    rc = main(["--short", "DEMO", "--name", "Demo Channel"])

    # Then: CWD 配下 (tmp_path) に生成
    assert rc == 0
    assert (_channel_dir(tmp_path) / "meta.json").is_file()


# ===================== Case 15: pyproject.toml entry point 登録 =====================


def test_pyproject_registers_yt_channel_init_entry_point():
    # Given: リポジトリルートの pyproject.toml
    root = Path(__file__).resolve().parent.parent
    pyproject = root / "pyproject.toml"

    # When: [project.scripts] を読む
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)
    scripts = data["project"]["scripts"]

    # Then: yt-channel-init エントリが登録されている
    assert "yt-channel-init" in scripts
    assert scripts["yt-channel-init"] == "youtube_automation.cli_entrypoints:yt_channel_init"


# ===================== Case 16: setup 済みディレクトリの再利用 =====================


def test_main_does_not_add_gitkeep_when_setup_directory_exists_without_it(tmp_path):
    # Given: auth/ ディレクトリのみ手動作成（.gitkeep なし）
    (tmp_path / "auth").mkdir()

    # When: main 実行
    rc = main(_required_args(tmp_path))

    # Then: .gitkeep は /setup の責務なので追加せず、ディレクトリ自体は保持
    assert rc == 0
    assert (tmp_path / "auth").is_dir()
    assert not (tmp_path / "auth" / ".gitkeep").exists()


def test_main_rejects_directory_at_gitkeep_path_without_partial_generation(tmp_path, capsys):
    # Given: .gitkeep として生成すべき path がディレクトリになっている
    (tmp_path / "auth" / ".gitkeep").mkdir(parents=True)

    # When: main 実行
    rc = main(_required_args(tmp_path))
    err = capsys.readouterr().err

    # Then: plan 段階で停止し、config も他ディレクトリも部分生成しない
    assert rc == 1
    assert "auth/.gitkeep は通常ファイルである必要があります" in err
    assert not (tmp_path / "config").exists()
    assert not (tmp_path / "collections").exists()


@pytest.mark.parametrize("target_exists", [True, False])
def test_main_rejects_gitkeep_symlink_without_partial_generation(tmp_path, capsys, target_exists):
    # Given: .gitkeep が symlink / broken symlink になっている
    outside = tmp_path / "outside-gitkeep"
    if target_exists:
        outside.write_text("external\n", encoding="utf-8")
    (tmp_path / "auth").mkdir()
    (tmp_path / "auth" / ".gitkeep").symlink_to(outside)

    # When: main 実行
    rc = main(_required_args(tmp_path))
    err = capsys.readouterr().err

    # Then: symlink 先への touch も config 部分生成も行わない
    assert rc == 1
    assert "auth/.gitkeep は通常ファイルである必要があります" in err
    if target_exists:
        assert outside.read_text(encoding="utf-8") == "external\n"
    else:
        assert not outside.exists()
    assert not (tmp_path / "config").exists()


def test_main_rejects_setup_directory_symlink_without_partial_generation(tmp_path, capsys):
    # Given: setup directory が target 外への symlink になっている
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "auth").symlink_to(outside, target_is_directory=True)

    # When: main 実行
    rc = main(_required_args(tmp_path))
    err = capsys.readouterr().err

    # Then: target 外への .gitkeep 作成も config 部分生成も行わない
    assert rc == 1
    assert "auth は symlink ではなくディレクトリである必要があります" in err
    assert not (outside / ".gitkeep").exists()
    assert not (tmp_path / "config").exists()


def test_main_is_safe_after_setup_dirs_precreated_directories(tmp_path):
    # Given: /setup が先に最小ディレクトリだけを作成済み
    from youtube_automation.cli.setup_dirs import main as setup_dirs_main

    assert setup_dirs_main(["--target", str(tmp_path)]) == 0
    assert not (tmp_path / "config" / "channel").exists()

    # When: /channel-new が後続で yt-channel-init を実行
    rc = main(_required_args(tmp_path))

    # Then: config 生成と既存ディレクトリの .gitkeep 維持が両立する
    assert rc == 0
    assert (_channel_dir(tmp_path) / "meta.json").is_file()
    for rel in GITKEEP_DIRS:
        assert (tmp_path / rel / ".gitkeep").is_file()


# ===================== Case 17: 一部 config 既存・残りのみ新規 =====================


def test_main_preserves_existing_files_and_creates_only_missing_ones(tmp_path):
    # Given: meta.json のみカスタム内容で既存
    channel_dir = _channel_dir(tmp_path)
    channel_dir.mkdir(parents=True)
    existing_meta = {"channel": {"name": "Existing", "short": "EX"}}
    (channel_dir / "meta.json").write_text(
        json.dumps(existing_meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # When: main 実行（--force なし）
    rc = main(_required_args(tmp_path))

    # Then: meta.json は保持、他のファイルは新規生成
    assert rc == 0
    meta = _read_json(channel_dir / "meta.json")
    assert meta == existing_meta
    for name in CHANNEL_DIR_FILES:
        if name == "meta.json":
            continue
        assert (channel_dir / name).is_file()


# ===================== Case 18: 差分あり + --force なし → diff 出力 + 変更なし =====================


def test_existing_file_with_diff_outputs_unified_diff_to_stderr_and_keeps_file(tmp_path, capsys):
    # Given: meta.json に異なる内容を仕込む
    channel_dir = _channel_dir(tmp_path)
    channel_dir.mkdir(parents=True)
    original_text = json.dumps({"channel": {"name": "Other", "short": "OT"}}, indent=2, ensure_ascii=False) + "\n"
    (channel_dir / "meta.json").write_text(original_text, encoding="utf-8")

    # When: 異なる --name で --force なし実行
    rc = main(_required_args(tmp_path, name="Demo Channel", short="DEMO"))
    err = capsys.readouterr().err

    # Then: rc=0、unified diff が stderr に、ファイル内容は変わらない
    assert rc == 0
    assert "---" in err and "+++" in err
    assert (channel_dir / "meta.json").read_text(encoding="utf-8") == original_text


# ===================== Case 19: 内容一致時は silent skip（diff 出力なし） =====================


def test_existing_file_with_same_content_is_silently_skipped(tmp_path, capsys):
    # Given: 1 回目で生成し、stderr を clear
    assert main(_required_args(tmp_path)) == 0
    capsys.readouterr()

    # When: 同じ引数で 2 回目実行
    rc = main(_required_args(tmp_path))
    err = capsys.readouterr().err

    # Then: rc=0、stderr に unified diff マーカーが出ない
    assert rc == 0
    assert "---" not in err
    assert "+++" not in err


# ===================== Case 20: --force 経路では diff を stderr に流さない =====================


def test_force_overwrite_does_not_emit_unified_diff(tmp_path, capsys):
    # Given: 異なる内容で meta.json を仕込む
    channel_dir = _channel_dir(tmp_path)
    channel_dir.mkdir(parents=True)
    (channel_dir / "meta.json").write_text(
        json.dumps({"channel": {"name": "Old", "short": "OT"}}, indent=2) + "\n",
        encoding="utf-8",
    )

    # When: --force で上書き
    rc = main(_required_args(tmp_path, extra=["--force"]))
    err = capsys.readouterr().err

    # Then: rc=0、stderr に unified diff マーカーが出ない（overwrite ログのみ）
    assert rc == 0
    assert "---" not in err
    assert "+++" not in err


def test_existing_env_with_diff_does_not_emit_secret_diff(tmp_path, capsys):
    # Given: 既存 .env に secret を含む異なる内容がある
    secret_text = "SECRET_TOKEN=should-not-print\nGOOGLE_CLOUD_PROJECT=private-project\n"
    (tmp_path / ".env").write_text(secret_text, encoding="utf-8")

    # When: --force なしで scaffold を実行
    rc = main(_required_args(tmp_path))
    err = capsys.readouterr().err

    # Then: .env は保持され、stderr に secret や .env diff は出ない
    assert rc == 0
    assert (tmp_path / ".env").read_text(encoding="utf-8") == secret_text
    assert "SECRET_TOKEN" not in err
    assert "should-not-print" not in err
    assert ".env (existing)" not in err


def test_existing_env_with_force_is_preserved_without_secret_diff(tmp_path, capsys):
    # Given: 既存 .env に secret を含む異なる内容がある
    secret_text = "SECRET_TOKEN=should-not-print\nGOOGLE_CLOUD_PROJECT=private-project\n"
    (tmp_path / ".env").write_text(secret_text, encoding="utf-8")

    # When: --force 付きで scaffold を実行
    rc = main(_required_args(tmp_path, extra=["--force"]))
    err = capsys.readouterr().err

    # Then: .env は --force でも保持され、stderr に secret や .env diff は出ない
    assert rc == 0
    assert (tmp_path / ".env").read_text(encoding="utf-8") == secret_text
    assert "SECRET_TOKEN" not in err
    assert "should-not-print" not in err
    assert ".env (existing)" not in err


# ===================== Case 21: --short にハイフン・数字混じり =====================


def test_short_arg_accepts_hyphen_and_digit_opaque_string(tmp_path):
    # Given: ハイフン・数字混じりの --short
    # When: main 実行
    rc = main(_required_args(tmp_path, short="BGM-01"))

    # Then: そのまま meta.json に反映される（バリデーション過剰なし）
    assert rc == 0
    meta = _read_json(_channel_dir(tmp_path) / "meta.json")
    assert meta["channel"]["short"] == "BGM-01"


# ===================== Case 22: setup-owned nested directory は生成しない =====================


def test_nested_setup_owned_directory_is_not_created_from_missing_parent(tmp_path):
    # Given: docs/ も存在しない空ターゲット
    assert not (tmp_path / "docs").exists()

    # When: main 実行
    rc = main(_required_args(tmp_path))

    # Then: docs/benchmarks は /setup の責務なので生成しない
    assert rc == 0
    assert not (tmp_path / "docs" / "benchmarks").exists()


def test_scaffold_gitignore_contains_secret_and_python_patterns(tmp_path):
    # Given/When: main を実行
    rc = main(_required_args(tmp_path))

    # Then: channel repo の機密・ローカル成果物を ignore する .gitignore が生成される
    assert rc == 0
    lines = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in lines
    assert "auth/client_secrets.json" in lines
    assert "auth/token*.json" in lines
    assert ".venv/" in lines
    assert "__pycache__/" in lines


def test_existing_directory_at_file_path_returns_domain_error(tmp_path, capsys):
    # Given: .env として生成すべき path がディレクトリになっている
    (tmp_path / ".env").mkdir()

    # When: main を実行
    rc = main(_required_args(tmp_path))
    err = capsys.readouterr().err

    # Then: IsADirectoryError ではなく domain-level error として停止する
    assert rc == 1
    assert ".env は通常ファイルである必要があります" in err


def test_existing_file_at_directory_path_returns_domain_error(tmp_path, capsys):
    # Given: auth/ として生成すべき path が通常ファイルになっている
    (tmp_path / "auth").write_text("not a directory\n", encoding="utf-8")

    # When: main を実行
    rc = main(_required_args(tmp_path))
    err = capsys.readouterr().err

    # Then: FileExistsError ではなく domain-level error として停止する
    assert rc == 1
    assert "auth はディレクトリである必要があります" in err


@pytest.mark.parametrize(
    ("conflict_rel", "expected_parent"),
    (
        ("config", "config"),
        ("config/channel", "config/channel"),
        ("config/skills", "config/skills"),
        ("docs", "docs"),
    ),
)
def test_existing_file_at_generated_parent_path_returns_domain_error_without_partial_generation(
    tmp_path,
    capsys,
    conflict_rel,
    expected_parent,
):
    # Given: 生成対象の ancestor が通常ファイルになっている
    conflict_path = tmp_path / conflict_rel
    conflict_path.parent.mkdir(parents=True, exist_ok=True)
    conflict_path.write_text("not a directory\n", encoding="utf-8")

    # When: main を実行
    rc = main(_required_args(tmp_path))
    err = capsys.readouterr().err

    # Then: mkdir の未処理例外ではなく domain-level error として停止し、部分生成もしない
    assert rc == 1
    assert f"親ディレクトリ {expected_parent} はディレクトリである必要があります" in err
    assert not (_channel_dir(tmp_path) / "meta.json").exists()
    assert not (tmp_path / ".env").exists()
    assert not (tmp_path / "auth" / "client_secrets.template.json").exists()


def test_supported_language_rejects_duplicates_after_locale_canonicalization(tmp_path, capsys):
    # Given: en と en_US は YouTube API 送信時に同じ en_US へ潰れる
    argv = _required_args(
        tmp_path,
        extra=[
            "--default-language",
            "en",
            "--supported-language",
            "en",
            "--supported-language",
            "en_US",
        ],
    )

    # When/Then: CLI 境界で重複として拒否し、ファイル生成しない
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2
    assert "--supported-language に重複した言語コード" in capsys.readouterr().err
    assert not (tmp_path / "config").exists()


def test_default_language_and_supported_languages_are_canonicalized_together(tmp_path):
    # Given: default は API 形式、supported は短縮形
    extra = ["--default-language", "en_US", "--supported-language", "en"]

    # When: main を実行
    rc = main(_required_args(tmp_path, extra=extra))

    # Then: 生成物は既存 channel settings と同じ短縮形へ揃う
    assert rc == 0
    meta = _read_json(_channel_dir(tmp_path) / "meta.json")
    localizations = _read_json(tmp_path / "config" / "localizations.json")
    youtube = _read_json(_channel_dir(tmp_path) / "youtube.json")
    assert meta["youtube_channel"]["default_language"] == "en"
    assert localizations["default_language"] == "en"
    assert localizations["supported_languages"] == ["en"]
    assert youtube["content_model"]["languages"] == ["en"]


# ===================== Case 23: scaffold 出力 → load_config() が成功する (Integration) =====================


def test_scaffold_output_is_loadable_by_new_config_loader(tmp_path, monkeypatch):
    """3 モジュール横断 Integration: cli → loader → dataclass."""
    # Given: scaffold を実行して 7 config を生成
    assert main(_required_args(tmp_path, short="DEMO", name="Demo Channel")) == 0

    # When: CHANNEL_DIR を scaffold ターゲットに向けて load_config()
    monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))
    from youtube_automation.utils.config import load_config, reset

    reset()
    config = load_config()

    # Then: ConfigError を出さず、scaffold で渡した値が読み取れる
    assert config.meta.channel_name == "Demo Channel"
    assert config.meta.channel_short == "DEMO"
    assert config.youtube.api.category_id == "10"
    assert config.youtube.api.privacy_status == "public"
    assert config.youtube.api.language == "en"


# ===================== Case 24: --short 欠落で SystemExit =====================


def test_main_exits_when_short_is_missing(tmp_path, capsys):
    # Given/When: --short を省略
    with pytest.raises(SystemExit):
        main(["--target", str(tmp_path), "--name", "Demo Channel"])

    # Then: stderr に該当引数名が出る
    err = capsys.readouterr().err
    assert "--short" in err or "short" in err


# ===================== Case 25: --name 欠落で SystemExit =====================


def test_main_exits_when_name_is_missing(tmp_path, capsys):
    # Given/When: --name を省略
    with pytest.raises(SystemExit):
        main(["--target", str(tmp_path), "--short", "DEMO"])

    # Then: stderr に該当引数名が出る
    err = capsys.readouterr().err
    assert "--name" in err or "name" in err


# ===================== Case 26: --target 不在パスで rc=1 =====================


def test_main_returns_error_when_target_path_does_not_exist(tmp_path, capsys):
    # Given: 存在しないターゲットパス
    missing = tmp_path / "does-not-exist"

    # When: main 実行
    rc = main(_required_args(missing))
    err = capsys.readouterr().err

    # Then: rc=1, stderr にエラーメッセージ, ファイル未生成
    assert rc == 1
    assert err.strip() != ""
    assert not (missing / "config").exists()


# ===================== Case 27: CHANNEL_DIR が存在しないパスで ConfigError =====================


def test_resolve_target_dir_raises_when_channel_dir_env_missing(tmp_path, monkeypatch):
    # Given: CHANNEL_DIR が存在しないパスを指す
    missing = tmp_path / "no-such-dir"
    monkeypatch.setenv("CHANNEL_DIR", str(missing))

    # When/Then: _resolve_target_dir(None) で ConfigError
    with pytest.raises(ConfigError):
        _resolve_target_dir(None)
