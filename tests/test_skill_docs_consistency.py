import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _frontmatter(path: str) -> dict:
    text = _read(path)
    if not text.startswith("---\n"):
        raise AssertionError(f"{path} does not start with frontmatter")
    end = text.find("\n---", 4)
    if end == -1:
        raise AssertionError(f"{path} frontmatter is not closed")
    parsed = yaml.safe_load(text[4:end])
    assert isinstance(parsed, dict)
    return parsed


def test_workflow_schema_references_existing_skill_schema() -> None:
    schema_path = ".claude/skills/wf-new/references/schema.md"
    assert (ROOT / schema_path).exists()

    for path in (".claude/skills/wf-next/SKILL.md", ".claude/skills/wf-status/SKILL.md"):
        text = _read(path)
        assert ".claude/references/workflow/schema.md" not in text
        assert schema_path in text


def test_theme_compare_docs_and_error_use_content_tags_themes() -> None:
    for path in (
        ".claude/skills/analytics-analyze/SKILL.md",
        "src/youtube_automation/scripts/theme_compare.py",
    ):
        text = _read(path)
        assert "channel_config.tags.themes" not in text
        assert "config/channel/content.json::tags.themes" in text

    assert "load_config().content.tags.themes" in _read(".claude/skills/analytics-analyze/SKILL.md")


def test_localizations_docs_use_root_localizations_file() -> None:
    for path in (
        ".claude/skills/wf-new/references/scene_phrases.md",
        "src/youtube_automation/scripts/populate_scene_phrases.py",
    ):
        text = _read(path)
        assert "config/channel/localizations.json::supported_languages" not in text
        assert "config/localizations.json::supported_languages" in text


def test_upload_settings_contract_is_nested_in_schedule_config() -> None:
    channel_new = _read(".claude/skills/channel-new/SKILL.md")
    channel_setup = _read(".claude/skills/channel-setup/SKILL.md")
    channel_init = _read("src/youtube_automation/cli/channel_init_templates.py")
    channel_init_test = _read("tests/test_channel_init.py")
    schedule_template = _read(".claude/skills/channel-setup/references/schedule-template.json")

    for text in (channel_new, channel_setup, channel_init, channel_init_test):
        assert "config/upload_settings.json" not in text

    assert "`config/schedule_config.json`（`upload_settings` を含む）" in channel_new
    assert "投稿頻度と `upload_settings`" in channel_setup
    assert '"upload_settings": {' in schedule_template


def test_channel_new_ttp_confirmation_contract_is_documented() -> None:
    channel_new = _read(".claude/skills/channel-new/SKILL.md")
    branding_snapshot_script = _read(".claude/skills/channel-new/references/fetch_branding_snapshot.py")

    forbidden = (
        "--benchmark-channel",
        "uv run yt-discover-competitors",
        "uv run yt-benchmark-collect",
        "uv run yt-benchmark-comments",
        "data/benchmark_YYYYMMDD.json",
        "data/comments_YYYYMMDD.json",
        "/channel-new  → TTP hearing + benchmark",
        "TTP ベンチマーク収集",
    )
    for text in forbidden:
        assert text not in channel_new

    assert "TTP seed fetch と承認済み対象反映" in channel_new
    assert "承認前に `benchmark.channels` へ書き込まない" in channel_new
    assert "追加調査は後続スキルへ委譲" in channel_new
    assert "docs/channel/ttp-seed-confirmation.md" in channel_new
    assert "docs/channel/competitor-branding-snapshot.json" in channel_new
    assert ".claude/skills/channel-new/references/fetch_branding_snapshot.py" in channel_new
    assert "`description` / `keywords` / `localizations` / `brandingSettings` は含まない" in channel_new
    assert "untrusted data" in channel_new
    assert "承認済み TTP 対象が 0 件の場合は Step 7 以降へ進まない" in channel_new

    assert 'CHANNELS_PART = "snippet,brandingSettings,localizations"' in branding_snapshot_script
    assert '"untrusted_data": True' in branding_snapshot_script


def test_channel_new_followup_skill_routing_uses_new_contract() -> None:
    discover = _read(".claude/skills/discover-competitors/SKILL.md")
    research = _read(".claude/skills/channel-research/SKILL.md")
    viewer_voice = _read(".claude/skills/viewer-voice/SKILL.md")
    setup = _read(".claude/skills/setup/SKILL.md")
    channel_setup = _read(".claude/skills/channel-setup/SKILL.md")
    channel_direction = _read(".claude/skills/channel-direction/SKILL.md")
    onboarding = _read("ONBOARDING.md")
    features = _read("docs/features.md")

    assert "/channel-new Step 5 の前段" not in discover
    assert "`/channel-new` の標準フローでは実行しない" in discover
    assert "ユーザー承認と relationship メモを必ず残す" in discover
    assert "genre_keywords" not in discover
    assert "target_scene" not in discover
    assert "config/channel/content.json::genre.{primary,style,context}" in discover

    assert "`/channel-new` で収集したベンチマークデータ + コメントデータ" not in research
    assert "/benchmark` と `/viewer-voice` で収集した" in research
    assert "TTP 対象確認 / 初回 config / persona / branding" in research
    assert "/viewer-voice` → 前提" in research

    assert "チャンネル立ち上げ・方向性見直し時に必ず使用" not in viewer_voice
    assert "`/channel-new` の標準フローでは実行せず" in viewer_voice
    assert "任意後続スキル" in viewer_voice

    for path_text in (setup, channel_setup, channel_direction, onboarding):
        assert "TTP benchmark" not in path_text
        assert "TTP ベンチマーク収集" not in path_text

    assert "TTP 対象確認、config 生成、ペルソナ、branding" in setup
    assert "TTP 対象確認 / seed fetch / 承認済み benchmark.channels 反映" in channel_setup
    assert "docs/channel/ttp-seed-confirmation.md" in channel_direction
    assert "docs/channel/competitor-branding-snapshot.json" in channel_direction
    assert "untrusted data" in channel_direction
    assert "動画尺 / 投稿頻度 / コメント語彙は収集済みデータがある場合だけ使う" in channel_direction

    assert "ビジョン共有 + 競合発掘" not in onboarding
    assert "yt-discover-competitors` で 5-10 件" not in onboarding
    assert "ベンチマークデータ + コメント収集まで実行" not in onboarding
    assert "docs/channel/ttp-seed-confirmation.md" in onboarding
    assert "docs/channel/competitor-branding-snapshot.json" in onboarding
    assert "untrusted data" in onboarding

    assert "新規チャンネル開設 → 競合発掘 → 方向性決定 → セットアップ" not in features
    assert "`/setup` → `/channel-new` → `/wf-new`" in features


def test_thumbnail_search_order_is_documented() -> None:
    expected_order = "`10-assets/thumbnail.jpg` → `10-assets/thumbnail.png`"
    for path in (
        ".claude/skills/video-upload/SKILL.md",
        ".claude/skills/video-upload/references/posting-checklist.md",
    ):
        text = _read(path)
        assert expected_order in text
        assert "→ `10-assets/main.jpg` → `10-assets/main.png`" not in text
        assert "textless 動画背景" in text


def test_first_post_playlist_initialization_contract_is_documented() -> None:
    playlist = _read(".claude/skills/playlist/SKILL.md")
    video_upload = _read(".claude/skills/video-upload/SKILL.md")
    wf_next = _read(".claude/skills/wf-next/SKILL.md")
    channel_new = _read(".claude/skills/channel-new/SKILL.md")
    checklist = _read(".claude/skills/video-upload/references/posting-checklist.md")

    description = _frontmatter(".claude/skills/playlist/SKILL.md")["description"]
    for trigger in ("初投稿", "初回投稿", "初回公開前にプレイリスト初期化"):
        assert trigger in description

    for command in (
        "uv run yt-playlist-status",
        "uv run yt-playlist-manager --init --dry-run",
        "uv run yt-playlist-manager --init",
    ):
        assert command in video_upload
        assert command in wf_next
        assert command in checklist

    assert "/playlist" in channel_new
    assert "`yt-playlist-status` → `yt-playlist-manager --init --dry-run` → `--init`" in channel_new

    for text in (playlist, video_upload, wf_next, channel_new, checklist):
        assert "playlist_id" in text
        assert "自動 assign" in text

    assert "`collection` 型では `collection_uploader` 内部の `assign_video()`" in video_upload
    assert "プレイリストへの動画追加は後続のアップロード経路が担う" in video_upload
    assert "`approval_gates.upload` とは別の playlist 作成ゲート" in wf_next
    assert "`approval_gates.upload = false` でも" in wf_next
    assert "確認を省略しない" in wf_next
    assert "ユーザーが playlist 初期化を却下した場合" in wf_next
    assert "`/video-upload` を実行せず停止" in wf_next
    assert "`config/channel/playlists.json` が無い" in wf_next
    assert "全 playlist に `playlist_id` がある場合はスキップ" in wf_next
    assert "初投稿プレイリスト初期化ゲート" in wf_next
    assert "`upload.video_id = null`" in wf_next
    assert "初回動画の追加は `/video-upload` 内部の自動 assign に任せる" in checklist


def test_common_docs_list_optional_channel_config_files() -> None:
    required = ("shorts.json", "comments.json", "pinned-comment.json", "distrokid.json")

    for path in ("README.md", "AGENTS.md", "CLAUDE.md", "ONBOARDING.md"):
        text = _read(path)
        for name in required:
            assert name in text, f"{path} missing {name}"


def test_distrokid_skill_uses_helper_name() -> None:
    skill_path = ROOT / ".claude" / "skills" / "distrokid-helper" / "SKILL.md"
    assert skill_path.exists()

    frontmatter = _frontmatter(".claude/skills/distrokid-helper/SKILL.md")
    assert frontmatter["name"] == "distrokid-helper"
    assert (skill_path.parent / "references" / "distrokid_prepare.py").is_file()
    assert (skill_path.parent / "references" / "spec-example.json").is_file()

    features = _read("docs/features.md")
    assert "/distrokid-helper" in features
    assert "サーバー起動まで実行" in features
    assert "distrokid-prep" not in features


def test_community_post_declares_raw_json_loader_exception() -> None:
    text = _read(".claude/skills/community-post/SKILL.md")

    assert "skill-local raw JSON 例外" in text
    assert "utils.config.load_config()" in text
    assert "`community` section を持たない" in text


def test_collection_lifecycle_uses_mp3_as_public_audio_contract() -> None:
    text = _read(".claude/skills/collection-ideate/references/collection-lifecycle.md")

    assert "01-master/           # マスター音声・動画（*.mp3, *.mp4）" in text
    assert "02-Individual-music/ # 個別音声ファイル（*.mp3）" in text
    assert "WAV は中間成果物" in text


def test_collection_localization_docs_use_root_localizations_contract() -> None:
    for path in (
        ".claude/skills/video-upload/SKILL.md",
        ".claude/skills/channel-setup/SKILL.md",
        ".claude/skills/channel-setup/references/config-generation-rules.md",
    ):
        text = _read(path)
        assert "localization.supported_languages" not in text
        assert "config/localizations.json" in text

    rules = _read(".claude/skills/channel-setup/references/config-generation-rules.md")
    required_sections = rules.split("以下は **すべて `config/channel/*.json` に含める**:", 1)[1].split(
        "## ルート設定ファイル",
        1,
    )[0]
    assert "`localizations`" not in required_sections
    assert "`config/localizations.json`" in rules


def test_channel_setup_does_not_recopy_youtube_json_after_config_completion() -> None:
    channel_setup = _read(".claude/skills/channel-setup/SKILL.md")

    assert "`config/channel/youtube.json::youtube.{category_id,privacy_status}`" in channel_setup

    step5 = channel_setup.split("### Step 5: 残りファイル生成", 1)[1].split("### Step 6:", 1)[0]
    assert "`config/channel/youtube.json`" not in step5


def test_theme_compare_missing_themes_error_uses_current_config_path(monkeypatch, caplog) -> None:
    from youtube_automation.scripts import theme_compare

    config = SimpleNamespace(content=SimpleNamespace(tags=SimpleNamespace(themes={})))

    caplog.set_level(logging.ERROR, logger="youtube_automation.scripts.theme_compare")
    monkeypatch.setattr(sys, "argv", ["yt-theme-compare"])
    monkeypatch.setattr(theme_compare, "_channel_dir", lambda: ROOT)
    monkeypatch.setattr(theme_compare, "load_config", lambda: config)
    monkeypatch.setattr(theme_compare, "load_latest_daily_snapshot", lambda _path: {"daily": []})
    monkeypatch.setattr(theme_compare, "_load_video_meta", lambda _channel_dir: {"video": {"title": "x"}})
    monkeypatch.setattr(
        theme_compare,
        "build_launch_curve_frame",
        lambda **_kwargs: pd.DataFrame([{"video_id": "video", "days_since_publish": 0}]),
    )

    assert theme_compare.main() == 2
    assert "config/channel/content.json::tags.themes" in caplog.text
