import logging
import os
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _assert_appears_before(text: str, earlier: str, later: str) -> None:
    earlier_idx = text.find(earlier)
    later_idx = text.find(later)
    assert earlier_idx >= 0, f"{earlier!r} not found"
    assert later_idx >= 0, f"{later!r} not found"
    assert earlier_idx < later_idx


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


def _isolated_git_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_CONFIG_")}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main", *args],
        cwd=repo,
        env=_isolated_git_env(),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


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


def test_wf_new_theme_scenes_fallback_uses_agent_generated_en_phrase() -> None:
    wf_new = _read(".claude/skills/wf-new/SKILL.md")

    assert "theme_scenes[<theme>] が未定義の場合" in wf_new
    assert '--en "<Agent-generated English scene phrase>"' in wf_new
    assert "--translations-file /tmp/scene-phrases.json" in wf_new


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


def test_setup_directory_generation_contract_is_separate_from_channel_config() -> None:
    setup = _read(".claude/skills/setup/SKILL.md")
    channel_new = _read(".claude/skills/channel-new/SKILL.md")
    setup_dirs = _read("src/youtube_automation/cli/setup_dirs.py")
    channel_init = _read("src/youtube_automation/cli/channel_init.py")
    setup_directory_contract = _read("src/youtube_automation/cli/setup_directory_contract.py")
    pyproject = _read("pyproject.toml")

    assert "uv run yt-setup-dirs" in setup
    assert "`/setup` では `config/channel/*.json` を生成しない" in setup
    assert "`/setup` が作成済みのディレクトリはそのまま再利用する" in channel_new
    assert "setup_directory_contract" in setup_dirs
    assert "setup_directory_contract" in channel_init
    assert "SETUP_DIRECTORIES" in setup_directory_contract
    assert 'yt-setup-dirs = "youtube_automation.cli_entrypoints:yt_setup_dirs"' in pyproject


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
    assert "TTP 完了条件" in channel_new
    assert "relationship（何を転写するか）" in channel_new
    assert "ttp_wf_new_readiness" in channel_new
    assert "`warn` の場合は成功案内を出さない" in channel_new
    assert "ユーザー承認済み例外" in channel_new

    assert 'CHANNELS_PART = "snippet,brandingSettings,localizations"' in branding_snapshot_script
    assert '"untrusted_data": True' in branding_snapshot_script


def test_channel_new_frontmatter_keeps_import_dispatch_keywords() -> None:
    frontmatter = _frontmatter(".claude/skills/channel-new/SKILL.md")
    assert frontmatter["name"] == "channel-new"
    description = frontmatter["description"]
    for keyword in ("既存チャンネル", "チャンネル取り込み", "config 生成", "channel-import"):
        assert keyword in description


def test_channel_new_import_mode_contract_is_separate_from_ttp_completion() -> None:
    channel_new = _read(".claude/skills/channel-new/SKILL.md")
    config_rules = _read(".claude/skills/channel-setup/references/config-generation-rules.md")

    assert "TTP 完了条件（新規開設モード）" in channel_new
    assert "既存チャンネル取り込みモードにはこの TTP 完了条件を適用しない" in channel_new
    assert "取り込み Step 8: 次ステップ案内" in channel_new
    assert "`music_engine` に入れる値は `suno` / `lyria` のどちらか" in channel_new
    assert "both` は config 契約外" in channel_new
    assert "audio.target_duration_min" in channel_new
    assert "audio.target_duration_max" in channel_new
    assert "meta / content / youtube / analytics / audio" in channel_new
    assert "channel-setup/references/config-template/audio.json" in channel_new
    assert "責務別 5 ファイル" in channel_new
    assert (ROOT / ".claude/skills/channel-setup/references/config-template/audio.json").is_file()
    assert (
        "`config/channel/meta.json::channel.channel_id` が未設定の場合は、認証済みチャンネル ID を必ず取得"
        in channel_new
    )
    assert "`channel_id` の `config/channel/meta.json::channel.channel_id` 保存" in channel_new
    assert "channel_id` 取得またはユーザー承認済み" not in channel_new
    assert "ユーザー承認済みの未完了項目明記" not in channel_new
    assert (
        "benchmark.channels`、`ttp-seed-confirmation.md`、branding snapshot、"
        "`ttp_wf_new_readiness` は取り込みモードの必須完了条件ではない"
    ) in channel_new
    assert "config-template.json" not in config_rules
    assert "config-template/*.json" in config_rules


def test_channel_new_requires_initial_save_before_followup_update() -> None:
    channel_new = _read(".claude/skills/channel-new/SKILL.md")
    automation_update = _read(".claude/skills/automation-update/SKILL.md")

    assert "初回保存と automation-update 前の整理" in channel_new
    assert "git status --porcelain" in channel_new
    assert "後続の `/automation-update` は dirty worktree で停止する" in channel_new
    assert "git add -A" in channel_new
    assert "`git add -A` 後の guard を唯一の安全境界にする" in channel_new
    assert "bash .claude/skills/channel-new/references/initial_save_guard.sh || exit 1" in channel_new
    assert 'git commit -m "chore: 初回チャンネル設定を保存"' in channel_new
    assert "secret-like file staged; unstaged before commit" in channel_new
    assert "staged secret を自動で外して停止" in channel_new
    assert "未コミット変更が残っています。/automation-update の前に以下を完了してください" in channel_new
    assert "保存未完了として終了した場合は、以下の成功案内は出さない" in channel_new
    assert "初回保存も完了しているため" in channel_new

    assert "`git status --porcelain` が **非空** の場合" in automation_update
    assert "/channel-new 直後の初回保存が未完了なら" in automation_update


def test_channel_new_pre_wf_new_checks_include_analytics_reporting_and_live_streaming() -> None:
    channel_new = _read(".claude/skills/channel-new/SKILL.md")
    step9 = channel_new.split("### Step 9: wf-new 接続前チェック", 1)[1].split(
        "### Step 10: 初回保存と automation-update 前の整理",
        1,
    )[0]
    success_message = channel_new.split("保存未完了として終了した場合は、以下の成功案内は出さない", 1)[1].split(
        "## 障害時ガイダンス",
        1,
    )[0]

    assert "Analytics / Reporting レポート取得設定が未確認" in step9
    assert "YouTube Analytics / Reporting API" in step9
    assert "Reporting API job 作成状態" in step9
    assert "`/analytics-collect`" in step9
    assert "`/setup`" in step9
    assert "初回制作は止めず" in step9

    assert "ライブ配信を使う可能性がある" in step9
    assert "YouTube Studio で Live streaming を早めに有効化" in step9
    assert "初回配信可能になるまで最大 24 時間" in step9
    assert "`/streaming`" in step9

    assert "公開後の分析は /analytics-collect" in success_message
    assert "Live streaming 有効化" in success_message
    assert "/streaming の準備確認" in success_message


def test_analytics_collect_documents_reporting_api_preflight() -> None:
    analytics_collect = _read(".claude/skills/analytics-collect/SKILL.md")

    assert "`/analytics-collect reporting`" in analytics_collect
    assert "uv run yt-analytics --reporting-dry-run" in analytics_collect
    assert "uv run yt-analytics --reporting-create-job" in analytics_collect
    assert "uv run yt-analytics --include-reporting" in analytics_collect
    assert "最大 48 時間" in analytics_collect
    assert "youtubereporting.googleapis.com" in analytics_collect


@pytest.mark.parametrize(
    "secret_path",
    [".env", "auth/client_secrets.json", "auth/token.json", "auth/token_streaming.json"],
)
def test_channel_new_initial_save_guard_blocks_staged_secrets(tmp_path: Path, secret_path: str) -> None:
    repo = tmp_path / "channel"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("initial\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")

    secret_file = repo / secret_path
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    secret_file.write_text("SECRET=value\n", encoding="utf-8")
    (repo / "config").mkdir()
    (repo / "config" / "channel.json").write_text("{}\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "add", "-f", secret_path)

    guard = ROOT / ".claude/skills/channel-new/references/initial_save_guard.sh"
    result = subprocess.run(
        [
            "bash",
            "-lc",
            f'bash {shlex.quote(str(guard))} || exit 1\ngit commit -m "chore: 初回チャンネル設定を保存"',
        ],
        cwd=repo,
        env=_isolated_git_env(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode != 0
    assert "secret-like file staged; unstaged before commit" in result.stderr
    assert secret_path in result.stderr
    assert _git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "1"
    assert secret_path not in _git(repo, "diff", "--cached", "--name-only").stdout.splitlines()


def test_channel_new_initial_save_plain_add_then_guard_blocks_oauth_secret(tmp_path: Path) -> None:
    repo = tmp_path / "channel"
    repo.mkdir()
    _git(repo, "init")
    auth_dir = repo / "auth"
    auth_dir.mkdir()
    (auth_dir / "token_streaming.json").write_text("{}\n", encoding="utf-8")
    (repo / "config").mkdir()
    (repo / "config" / "channel.json").write_text("{}\n", encoding="utf-8")

    _git(repo, "add", "-A")
    staged = set(_git(repo, "diff", "--cached", "--name-only").stdout.splitlines())
    assert "config/channel.json" in staged
    assert "auth/token_streaming.json" in staged

    guard = ROOT / ".claude/skills/channel-new/references/initial_save_guard.sh"
    result = subprocess.run(
        ["bash", str(guard)],
        cwd=repo,
        env=_isolated_git_env(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode != 0
    assert "auth/token_streaming.json" in result.stderr
    staged_after_guard = set(_git(repo, "diff", "--cached", "--name-only").stdout.splitlines())
    assert "config/channel.json" in staged_after_guard
    assert "auth/token_streaming.json" not in staged_after_guard


def test_channel_new_initial_save_guard_allows_non_secret_staged_files(tmp_path: Path) -> None:
    repo = tmp_path / "channel"
    repo.mkdir()
    _git(repo, "init")
    (repo / "config").mkdir()
    (repo / "config" / "channel.json").write_text("{}\n", encoding="utf-8")
    _git(repo, "add", "-A")

    guard = ROOT / ".claude/skills/channel-new/references/initial_save_guard.sh"
    result = subprocess.run(
        ["bash", str(guard)],
        cwd=repo,
        env=_isolated_git_env(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""


def test_channel_new_initial_save_success_path_commits_and_cleans_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "channel"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / ".gitignore").write_text(
        ".env\nauth/client_secrets.json\nauth/token*.json\n",
        encoding="utf-8",
    )
    (repo / ".env").write_text("SECRET=value\n", encoding="utf-8")
    auth_dir = repo / "auth"
    auth_dir.mkdir()
    (auth_dir / "client_secrets.json").write_text("{}\n", encoding="utf-8")
    (auth_dir / "token_streaming.json").write_text("{}\n", encoding="utf-8")
    (repo / "config").mkdir()
    (repo / "config" / "channel.json").write_text("{}\n", encoding="utf-8")

    guard = ROOT / ".claude/skills/channel-new/references/initial_save_guard.sh"
    _git(repo, "add", "-A")
    guard_result = subprocess.run(
        ["bash", str(guard)],
        cwd=repo,
        env=_isolated_git_env(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert guard_result.returncode == 0

    _git(repo, "commit", "-m", "chore: 初回チャンネル設定を保存")
    assert _git(repo, "status", "--porcelain").stdout == ""
    assert _git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "1"


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


def test_upload_schedule_plan_must_precede_publish_guidance() -> None:
    video_upload = _read(".claude/skills/video-upload/SKILL.md")
    wf_next = _read(".claude/skills/wf-next/SKILL.md")
    posting_checklist = _read(".claude/skills/video-upload/references/posting-checklist.md")
    scheduled_publish = _read(".claude/skills/video-upload/references/scheduled-publish.md")

    for text in (video_upload, wf_next, posting_checklist, scheduled_publish):
        assert "uv run yt-upload-collection --plan" in text
        assert "📅 公開設定: 即時公開 (public)" in text
        assert "📅 公開予定" in text

    for text in (video_upload, posting_checklist, scheduled_publish):
        assert "アップロード API は叩かない" in text
        assert "YouTube read API を呼ぶ場合がある" in text
        assert "実 API は叩かない" not in text
        assert "API 非消費" not in text

    collection_flow = video_upload[
        video_upload.index("### collection アップロードフロー") : video_upload.index(
            "### single_release アップロードフロー"
        )
    ]
    _assert_appears_before(collection_flow, "uv run yt-upload-collection --plan", "Complete Collection アップロード")

    single_release_flow = video_upload[
        video_upload.index("### single_release アップロードフロー") : video_upload.index("### コマンドリファレンス")
    ]
    assert "yt-upload-auto" in single_release_flow
    assert "yt-upload-collection --plan" in single_release_flow
    assert "この分岐では実行しない" in single_release_flow
    assert "collection 用 plan 結果を流用しない" in single_release_flow

    _assert_appears_before(
        posting_checklist,
        "uv run yt-upload-collection --plan",
        "uv run yt-upload-collection [-c NAME]",
    )

    wf_next_gate = wf_next[wf_next.index("approval_gates.upload = true") :]
    _assert_appears_before(wf_next_gate, "uv run yt-upload-collection --plan", "AskUserQuestion")
    _assert_appears_before(wf_next_gate, "uv run yt-upload-collection --plan", "/video-upload")


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
    assert "投稿本文・Studio URL の実データには使わない" in text
    assert "fallback や merge 元にしない" in text


def test_community_draft_documents_skill_config_merge_before_channel_json() -> None:
    text = _read(".claude/skills/community-draft/SKILL.md")

    assert 'load_skill_config("community-draft")' in text
    assert ".claude/skills/community-draft/config.default.yaml" in text
    assert "config/skills/community-draft.yaml" in text
    assert "config/channel/community-draft.json" in text
    assert (
        "config.default.yaml` < `config/skills/community-draft.yaml` < `config/channel/community-draft.json"
    ) in text


def test_skill_config_defaults_have_read_gate_in_skill_docs() -> None:
    skill_dirs = sorted(path.parent for path in (ROOT / ".claude" / "skills").glob("*/config.default.yaml"))
    assert skill_dirs

    for skill_dir in skill_dirs:
        skill = skill_dir.name
        rel_skill_md = f".claude/skills/{skill}/SKILL.md"
        text = _read(rel_skill_md)

        assert "## 設定読み込みゲート" in text, f"{skill} missing config read gate"
        assert f".claude/skills/{skill}/config.default.yaml" in text
        assert f"config/skills/{skill}.yaml" in text
        assert f'load_skill_config("{skill}")' in text
        assert "SKILL.md の説明や記憶から設定値を推測しない" in text
        assert "必ず Read" in text
        assert "存在する場合" in text
        assert "勝手に作成しない" in text

        if skill == "community-post":
            assert "default と任意 override を確認する" in text
            assert "gate で Read" in text
        else:
            assert "deep-merge 前提" in text
            assert "チャンネル上書きを優先" in text

        gate_pos = text.index("## 設定読み込みゲート")
        operational_markers = [
            marker
            for marker in (
                "## Instructions",
                "## 実行フロー",
                "## Workflow",
                "## Scripts",
                "## Quick Reference",
                "## Inputs",
                "## 前提",
                "## 制約・前提",
                "### モード判定",
                "### スタイルバリアント",
                "### Step 1",
                "### 前提条件チェック",
                "### 対象コレクション",
            )
            if marker in text
        ]
        if operational_markers:
            assert gate_pos < min(text.index(marker) for marker in operational_markers), (
                f"{skill} config read gate must appear before operational steps"
            )


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


def test_channel_setup_documents_ttp_wf_new_readiness_gate() -> None:
    channel_setup = _read(".claude/skills/channel-setup/SKILL.md")
    rules = _read(".claude/skills/channel-setup/references/config-generation-rules.md")

    for text in (channel_setup, rules):
        assert "uv run yt-doctor --json" in text
        assert "ttp_wf_new_readiness" in text
        assert "/channel-setup benchmark 反映未完了" in text
        assert "data/benchmark_*.json" in text
        assert "docs/benchmarks/*.md" in text
        assert "data/thumbnail_compare/benchmark/" in text
        assert "config/skills/thumbnail.yaml::reference_images.default" in text
        assert "config/skills/thumbnail.yaml::reference_images.channel_branding" in text


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
