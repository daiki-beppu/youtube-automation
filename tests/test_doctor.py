"""yt-doctor の単体テスト"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from youtube_automation.cli import doctor


def _assert_no_bare_yt_channel_status(value: object) -> None:
    text = json.dumps(value, ensure_ascii=False)
    for match in re.finditer("yt-channel-status", text):
        prefix = text[max(0, match.start() - len("uv run ")) : match.start()]
        assert prefix == "uv run "


# ---------------------------------------------------------------------------
# テストヘルパー
# ---------------------------------------------------------------------------


def _write_minimal_config(base: Path) -> None:
    """検証に必要な最小限の config/channel/*.json を base に書き出す.

    load_config() が成功するための必須キーのみを含む。
    localizations.json は省略可能（exists=False として扱われる）。
    """
    config_dir = base / "config" / "channel"
    config_dir.mkdir(parents=True, exist_ok=True)

    (config_dir / "meta.json").write_text(
        json.dumps(
            {
                "channel": {
                    "name": "TestCh",
                    "short": "TC",
                    "youtube_handle": "@testch",
                    "url": "https://youtube.com/@testch",
                }
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "content.json").write_text(
        json.dumps(
            {
                "genre": {"primary": "bgm", "style": "ambient", "context": "study"},
                "tags": {"base": ["bgm"], "themes": {}},
                "descriptions": {
                    "opening": "Relaxing {style}.",
                    "perfect_for": ["Study"],
                    "hashtags": ["#bgm"],
                },
                "title": {"template": "{theme} bgm"},
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "youtube.json").write_text(
        json.dumps(
            {
                "youtube": {
                    "category_id": "10",
                    "privacy_status": "public",
                    "language": "ja",
                }
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def stub_run(monkeypatch):
    """`doctor._run` を順次差し替えるヘルパー"""
    calls: list[list[str]] = []

    def make(*results: tuple[int, str, str]):
        it = iter(results)

        def fake_run(cmd, timeout=30):
            calls.append(cmd)
            try:
                return next(it)
            except StopIteration:
                return (0, "", "")

        monkeypatch.setattr(doctor, "_run", fake_run)
        return calls

    return make


class TestCheckGcloud:
    def test_ok(self, stub_run):
        stub_run((0, "Google Cloud SDK 552.0.0\n", ""))
        r = doctor.check_gcloud()
        assert r.status == "ok"
        assert "552.0.0" in r.message

    def test_not_found(self, stub_run):
        stub_run((127, "", "command not found: gcloud"))
        r = doctor.check_gcloud()
        assert r.status == "fail"
        assert r.next_action is not None


class TestCheckGcloudAccount:
    def test_active(self, stub_run):
        stub_run((0, json.dumps([{"account": "user@example.com"}]), ""))
        r = doctor.check_gcloud_account()
        assert r.status == "ok"
        assert "user@example.com" in r.message

    def test_none_active(self, stub_run):
        stub_run((0, "[]", ""))
        r = doctor.check_gcloud_account()
        assert r.status == "fail"
        assert r.next_action["kind"] == "human"

    def test_command_error(self, stub_run):
        stub_run((1, "", "boom"))
        r = doctor.check_gcloud_account()
        assert r.status == "unknown"


class TestEnvFile:
    def test_missing(self, tmp_path):
        r = doctor.check_env_file(tmp_path)
        assert r.status == "fail"

    def test_all_keys(self, tmp_path):
        (tmp_path / ".env").write_text(
            "GOOGLE_CLOUD_LOCATION=us-central1\nGOOGLE_GENAI_USE_VERTEXAI=true\n",
            encoding="utf-8",
        )
        r = doctor.check_env_file(tmp_path)
        assert r.status == "ok"

    def test_partial(self, tmp_path):
        (tmp_path / ".env").write_text("GOOGLE_CLOUD_LOCATION=us-central1\n", encoding="utf-8")
        r = doctor.check_env_file(tmp_path)
        assert r.status == "warn"

    def test_project_alone_is_not_required(self, tmp_path):
        """`GOOGLE_CLOUD_PROJECT` は必須ではない (ADC fallback で解決可能)"""
        (tmp_path / ".env").write_text(
            "GOOGLE_CLOUD_LOCATION=us-central1\nGOOGLE_GENAI_USE_VERTEXAI=true\n",
            encoding="utf-8",
        )
        r = doctor.check_env_file(tmp_path)
        assert r.status == "ok"


class TestProjectIdResolution:
    def test_env_file_takes_precedence(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        monkeypatch.setattr(doctor, "_adc_quota_project", lambda: "adc-proj")
        (tmp_path / ".env").write_text("GOOGLE_CLOUD_PROJECT=env-file-proj\n", encoding="utf-8")
        assert doctor._project_id_for(tmp_path) == "env-file-proj"

    def test_env_var_used_when_env_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "env-var-proj")
        monkeypatch.setattr(doctor, "_adc_quota_project", lambda: "adc-proj")
        assert doctor._project_id_for(tmp_path) == "env-var-proj"

    def test_falls_back_to_adc_quota_project(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        monkeypatch.setattr(doctor, "_adc_quota_project", lambda: "adc-proj")
        assert doctor._project_id_for(tmp_path) == "adc-proj"

    def test_none_when_nothing_available(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        monkeypatch.setattr(doctor, "_adc_quota_project", lambda: None)
        assert doctor._project_id_for(tmp_path) is None


class TestClientSecrets:
    def test_missing_without_project(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        r = doctor.check_client_secrets(tmp_path)
        assert r.status == "fail"
        assert r.next_action["kind"] == "human"
        assert "credentials" in r.next_action["url"]

    def test_missing_with_project(self, tmp_path):
        (tmp_path / ".env").write_text("GOOGLE_CLOUD_PROJECT=foo-proj\n", encoding="utf-8")
        r = doctor.check_client_secrets(tmp_path)
        assert r.status == "fail"
        assert "foo-proj" in r.next_action["url"]

    def test_valid(self, tmp_path):
        auth = tmp_path / "auth"
        auth.mkdir()
        (auth / "client_secrets.json").write_text(
            json.dumps(
                {
                    "installed": {
                        "client_id": "x",
                        "client_secret": "y",
                        "redirect_uris": ["http://localhost"],
                    }
                }
            ),
            encoding="utf-8",
        )
        r = doctor.check_client_secrets(tmp_path)
        assert r.status == "ok"

    def test_missing_keys(self, tmp_path):
        auth = tmp_path / "auth"
        auth.mkdir()
        (auth / "client_secrets.json").write_text(json.dumps({"installed": {"client_id": "x"}}), encoding="utf-8")
        r = doctor.check_client_secrets(tmp_path)
        assert r.status == "fail"


class TestOAuthToken:
    def test_missing(self, tmp_path):
        r = doctor.check_oauth_token(tmp_path)
        assert r.status == "fail"
        assert r.next_action["kind"] == "ai-exec"
        assert "uv run yt-channel-status" in r.next_action["cmd"]
        _assert_no_bare_yt_channel_status(r.next_action)

    def test_valid(self, tmp_path):
        auth = tmp_path / "auth"
        auth.mkdir()
        (auth / "token.json").write_text(json.dumps({"scopes": ["a", "b"]}), encoding="utf-8")
        r = doctor.check_oauth_token(tmp_path)
        assert r.status == "ok"


class TestSummarize:
    def test_next_check_id(self):
        results = [
            doctor.CheckResult(id="a", status="ok", message=""),
            doctor.CheckResult(id="b", status="fail", message=""),
            doctor.CheckResult(id="c", status="fail", message=""),
        ]
        s = doctor.summarize(results)
        assert s["next_check_id"] == "b"
        assert s["ok"] == 1
        assert s["fail"] == 2

    def test_all_ok(self):
        results = [doctor.CheckResult(id="a", status="ok", message="")]
        s = doctor.summarize(results)
        assert s["next_check_id"] is None


class TestResolveChannelDir:
    def test_target_explicit(self, tmp_path):
        r = doctor.resolve_channel_dir(str(tmp_path))
        assert r == tmp_path.resolve()

    def test_env_fallback(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))
        r = doctor.resolve_channel_dir(None)
        assert r == tmp_path.resolve()

    def test_cwd_fallback(self, monkeypatch, tmp_path):
        monkeypatch.delenv("CHANNEL_DIR", raising=False)
        monkeypatch.chdir(tmp_path)
        r = doctor.resolve_channel_dir(None)
        assert r == tmp_path.resolve()


class TestMain:
    def test_json_output(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(doctor, "_run", lambda *a, **kw: (127, "", "missing"))
        monkeypatch.setattr(doctor, "resolve_channel_dir", lambda t: tmp_path)
        code = doctor.main(["--json"])
        assert code == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["channel_dir"] == str(tmp_path)
        assert "summary" in payload
        # 6 bootstrap + 11 api + 1 channel + 1 upload = 19
        assert len(payload["checks"]) == 19
        for c in payload["checks"]:
            assert c["status"] in ("ok", "warn", "fail", "unknown")
            # category フィールドが JSON に含まれていること
            assert "category" in c
            assert c["category"] in ("bootstrap", "api", "channel", "upload")

    def test_human_output(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(doctor, "_run", lambda *a, **kw: (127, "", "missing"))
        monkeypatch.setattr(doctor, "resolve_channel_dir", lambda t: tmp_path)
        code = doctor.main([])
        assert code == 0
        out = capsys.readouterr().out
        assert "summary:" in out
        assert "channel_dir:" in out


# ---------------------------------------------------------------------------
# CheckResult.category フィールド
# ---------------------------------------------------------------------------


class TestCheckResultCategory:
    def test_default_category_is_api(self):
        """category 省略時のデフォルト値は "api"."""
        r = doctor.CheckResult(id="x", status="ok", message="m")
        assert r.category == "api"

    def test_category_can_be_set(self):
        """category に任意のカテゴリ値を設定できる."""
        r = doctor.CheckResult(id="x", status="ok", message="m", category="channel")
        assert r.category == "channel"

    def test_positional_three_args_backward_compat(self):
        """既存の位置引数 3 つ構築が壊れていない (TestSummarize 互換)."""
        r = doctor.CheckResult("x", "ok", "m")
        assert r.id == "x"
        assert r.status == "ok"
        assert r.message == "m"
        assert r.category == "api"

    def test_existing_api_checks_have_api_category(self, stub_run):
        """既存の api チェック (gcloud 等) が category="api" を持つ."""
        stub_run((0, "Google Cloud SDK 552.0.0\n", ""))
        r = doctor.check_gcloud()
        assert r.category == "api"


# ---------------------------------------------------------------------------
# check_channel_config
# ---------------------------------------------------------------------------


class TestCheckChannelConfig:
    def test_id_and_category(self, tmp_path):
        """id="channel_config", category="channel" であること."""
        r = doctor.check_channel_config(tmp_path)
        assert r.id == "channel_config"
        assert r.category == "channel"

    def test_config_dir_absent_is_fail_with_channel_new(self, tmp_path):
        """config/channel/ ディレクトリが存在しない場合: fail + /channel-new 案内."""
        r = doctor.check_channel_config(tmp_path)
        assert r.status == "fail"
        assert r.next_action is not None
        action_str = json.dumps(r.next_action)
        assert "/channel-new" in action_str

    def test_config_dir_exists_but_invalid_json_is_fail_with_channel_import(self, tmp_path):
        """config/channel/ 存在・JSON 破損: fail + /channel-import 案内 (既存チャンネル)."""
        config_dir = tmp_path / "config" / "channel"
        config_dir.mkdir(parents=True)
        (config_dir / "meta.json").write_text("{broken json", encoding="utf-8")
        r = doctor.check_channel_config(tmp_path)
        assert r.status == "fail"
        assert r.next_action is not None
        action_str = json.dumps(r.next_action)
        assert "/channel-import" in action_str

    def test_config_dir_exists_but_missing_required_keys_is_fail_with_channel_import(self, tmp_path):
        """config/channel/ 存在・必須キー不足: fail + /channel-import 案内."""
        config_dir = tmp_path / "config" / "channel"
        config_dir.mkdir(parents=True)
        # meta.json のみ（必須キーも不足）
        (config_dir / "meta.json").write_text(json.dumps({"channel": {}}), encoding="utf-8")
        r = doctor.check_channel_config(tmp_path)
        assert r.status == "fail"
        action_str = json.dumps(r.next_action)
        assert "/channel-import" in action_str

    def test_valid_config_is_ok(self, tmp_path):
        """load_config() が成功する設定: ok."""
        _write_minimal_config(tmp_path)
        r = doctor.check_channel_config(tmp_path)
        assert r.status == "ok"

    def test_channel_dir_env_restored_after_call(self, tmp_path, monkeypatch):
        """check_channel_config 呼び出し後、CHANNEL_DIR 環境変数が元に戻っている."""
        original = str(tmp_path / "original")
        monkeypatch.setenv("CHANNEL_DIR", original)

        other = tmp_path / "other"
        _write_minimal_config(other)
        doctor.check_channel_config(other)

        assert os.environ.get("CHANNEL_DIR") == original

    def test_channel_dir_env_deleted_when_originally_absent(self, tmp_path, monkeypatch):
        """元々 CHANNEL_DIR 未設定の場合、呼び出し後も未設定のまま."""
        monkeypatch.delenv("CHANNEL_DIR", raising=False)

        doctor.check_channel_config(tmp_path)

        assert "CHANNEL_DIR" not in os.environ


# ---------------------------------------------------------------------------
# bootstrap checks
# ---------------------------------------------------------------------------


class TestBootstrapChecks:
    def test_check_uv_ok(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda cmd: "/usr/local/bin/uv" if cmd == "uv" else None)
        r = doctor.check_uv()
        assert r.status == "ok"
        assert r.category == "bootstrap"

    def test_check_uv_missing_is_fail(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda cmd: None)
        r = doctor.check_uv()
        assert r.status == "fail"
        assert r.category == "bootstrap"
        assert r.next_action["kind"] == "human"

    def test_uv_project_missing_is_fail_with_uv_init(self, tmp_path):
        r = doctor.check_uv_project(tmp_path)
        assert r.status == "fail"
        assert r.category == "bootstrap"
        assert r.next_action["cmd"] == "uv init"

    def test_uv_project_not_a_file_is_fail(self, tmp_path):
        (tmp_path / "pyproject.toml").mkdir()
        r = doctor.check_uv_project(tmp_path)
        assert r.status == "fail"
        assert r.category == "bootstrap"
        assert "ファイルではない" in r.message

    def test_uv_project_present_is_ok(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
        r = doctor.check_uv_project(tmp_path)
        assert r.status == "ok"
        assert r.category == "bootstrap"

    def test_automation_package_missing_pyproject_is_fail_with_uv_init(self, tmp_path):
        r = doctor.check_automation_package(tmp_path)
        assert r.status == "fail"
        assert r.category == "bootstrap"
        assert r.next_action["cmd"] == "uv init"

    def test_automation_package_missing_dependency_is_fail_with_uv_add(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\ndependencies = ["requests>=2"]\n',
            encoding="utf-8",
        )
        r = doctor.check_automation_package(tmp_path)
        assert r.status == "fail"
        assert r.category == "bootstrap"
        assert "uv add" in r.next_action["cmd"]

    def test_automation_package_dependency_name_is_ok(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\ndependencies = ["youtube-channels-automation>=5"]\n',
            encoding="utf-8",
        )
        r = doctor.check_automation_package(tmp_path)
        assert r.status == "ok"
        assert r.category == "bootstrap"

    def test_automation_package_similar_name_is_fail(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\ndependencies = ["youtube-channels-automation-extra>=1"]\n',
            encoding="utf-8",
        )
        r = doctor.check_automation_package(tmp_path)
        assert r.status == "fail"
        assert r.category == "bootstrap"
        assert "uv add" in r.next_action["cmd"]

    def test_automation_package_git_dependency_is_ok(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\ndependencies = ["youtube-channels-automation @ git+https://github.com/daiki-beppu/youtube-automation.git"]\n',
            encoding="utf-8",
        )
        r = doctor.check_automation_package(tmp_path)
        assert r.status == "ok"

    def test_automation_package_self_project_is_ok(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "youtube-channels-automation"\ndependencies = []\n',
            encoding="utf-8",
        )
        r = doctor.check_automation_package(tmp_path)
        assert r.status == "ok"
        assert r.category == "bootstrap"

    def test_automation_package_invalid_toml_is_fail(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project\n", encoding="utf-8")
        r = doctor.check_automation_package(tmp_path)
        assert r.status == "fail"
        assert r.category == "bootstrap"

    def test_skills_synced_missing_is_fail_with_yt_skills_sync(self, tmp_path):
        r = doctor.check_skills_synced(tmp_path)
        assert r.status == "fail"
        assert r.category == "bootstrap"
        assert r.next_action["cmd"] == "uv run yt-skills sync --asset skills --force"

    def test_skills_synced_requires_all_bundled_skills(self, tmp_path, monkeypatch):
        monkeypatch.setattr(doctor, "bundled_skill_names", lambda: ["channel-new", "setup"])
        setup_dir = tmp_path / ".claude" / "skills" / "setup"
        setup_dir.mkdir(parents=True)
        (setup_dir / "SKILL.md").write_text("# setup", encoding="utf-8")
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir()
        (agents_dir / "skills").symlink_to(Path("..") / ".claude" / "skills")

        r = doctor.check_skills_synced(tmp_path)
        assert r.status == "fail"
        assert r.category == "bootstrap"
        assert ".claude/skills/channel-new/SKILL.md" in r.message
        assert r.next_action["cmd"] == "uv run yt-skills sync --asset skills --force"

    def test_skills_synced_present_is_ok(self, tmp_path, monkeypatch):
        monkeypatch.setattr(doctor, "bundled_skill_names", lambda: ["channel-new", "setup"])
        for skill_name in ["channel-new", "setup"]:
            skill_dir = tmp_path / ".claude" / "skills" / skill_name
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(f"# {skill_name}", encoding="utf-8")
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir()
        (agents_dir / "skills").symlink_to(Path("..") / ".claude" / "skills")
        r = doctor.check_skills_synced(tmp_path)
        assert r.status == "ok"
        assert r.category == "bootstrap"

    def test_skills_synced_legacy_onboard_orphan_is_fail_with_prune(self, tmp_path, monkeypatch):
        monkeypatch.setattr(doctor, "bundled_skill_names", lambda: ["setup"])
        for skill_name in ["setup", "onboard"]:
            skill_dir = tmp_path / ".claude" / "skills" / skill_name
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(f"# {skill_name}", encoding="utf-8")
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir()
        (agents_dir / "skills").symlink_to(Path("..") / ".claude" / "skills")

        r = doctor.check_skills_synced(tmp_path)
        assert r.status == "fail"
        assert r.category == "bootstrap"
        assert "旧 onboard skill が残存" in r.message
        assert r.next_action["cmd"] == "uv run yt-skills sync --asset skills --force --prune --yes"

    def test_skills_synced_reports_missing_bundled_skill(self, tmp_path, monkeypatch):
        monkeypatch.setattr(doctor, "bundled_skill_names", lambda: ["setup"])
        skill_dir = tmp_path / ".claude" / "skills" / "wf-new"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# wf-new", encoding="utf-8")
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir()
        (agents_dir / "skills").symlink_to(Path("..") / ".claude" / "skills")

        r = doctor.check_skills_synced(tmp_path)
        assert r.status == "fail"
        assert r.category == "bootstrap"
        assert ".claude/skills/setup/SKILL.md" in r.message
        assert r.next_action["cmd"] == "uv run yt-skills sync --asset skills --force"

    def test_skills_synced_missing_agents_link_is_warn(self, tmp_path, monkeypatch):
        monkeypatch.setattr(doctor, "bundled_skill_names", lambda: ["setup"])
        skill_dir = tmp_path / ".claude" / "skills" / "setup"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# setup", encoding="utf-8")
        r = doctor.check_skills_synced(tmp_path)
        assert r.status == "warn"
        assert r.category == "bootstrap"
        assert r.next_action["kind"] == "human"

    def test_skills_synced_wrong_agents_link_is_warn(self, tmp_path, monkeypatch):
        monkeypatch.setattr(doctor, "bundled_skill_names", lambda: ["setup"])
        skill_dir = tmp_path / ".claude" / "skills" / "setup"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# setup", encoding="utf-8")
        wrong_target = tmp_path / "wrong-skills"
        wrong_target.mkdir()
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir()
        (agents_dir / "skills").symlink_to(wrong_target)
        r = doctor.check_skills_synced(tmp_path)
        assert r.status == "warn"
        assert r.category == "bootstrap"
        assert r.next_action["kind"] == "human"


# ---------------------------------------------------------------------------
# check_upload_ready
# ---------------------------------------------------------------------------

_SCOPE_YOUTUBE = "https://www.googleapis.com/auth/youtube"
_SCOPE_FORCE_SSL = "https://www.googleapis.com/auth/youtube.force-ssl"
_SCOPE_ANALYTICS_RO = "https://www.googleapis.com/auth/yt-analytics.readonly"
_FULL_SCOPES = [_SCOPE_YOUTUBE, _SCOPE_FORCE_SSL, _SCOPE_ANALYTICS_RO]
_CHANNEL_ID = "UCxxxxxxxxxxxxxxxxxxxxxxxx"


def _write_token(base: Path, scopes: list[str]) -> None:
    auth = base / "auth"
    auth.mkdir(exist_ok=True)
    (auth / "token.json").write_text(json.dumps({"scopes": scopes}), encoding="utf-8")


def _write_meta_channel_id(base: Path, channel_id: str | None) -> None:
    meta_dir = base / "config" / "channel"
    meta_dir.mkdir(parents=True, exist_ok=True)
    ch: dict = {}
    if channel_id is not None:
        ch["channel_id"] = channel_id
    (meta_dir / "meta.json").write_text(json.dumps({"channel": ch}), encoding="utf-8")


class TestCheckUploadReady:
    def test_id_and_category(self, tmp_path):
        """id="upload_ready", category="upload" であること."""
        r = doctor.check_upload_ready(tmp_path)
        assert r.id == "upload_ready"
        assert r.category == "upload"

    def test_token_missing_is_fail_with_ai_exec(self, tmp_path):
        """token.json が存在しない: fail + ai-exec (最優先事由)."""
        r = doctor.check_upload_ready(tmp_path)
        assert r.status == "fail"
        assert r.next_action is not None
        assert r.next_action["kind"] == "ai-exec"
        assert "uv run yt-channel-status" in r.next_action["cmd"]
        _assert_no_bare_yt_channel_status(r.next_action)

    def test_token_parse_error_is_fail(self, tmp_path):
        """token.json が JSON として不正: fail."""
        auth = tmp_path / "auth"
        auth.mkdir()
        (auth / "token.json").write_text("{broken json", encoding="utf-8")
        r = doctor.check_upload_ready(tmp_path)
        assert r.status == "fail"

    def test_all_conditions_met_is_ok(self, tmp_path):
        """必須 scope 充足 + channel_id 設定済み: ok."""
        _write_token(tmp_path, _FULL_SCOPES)
        _write_meta_channel_id(tmp_path, _CHANNEL_ID)
        r = doctor.check_upload_ready(tmp_path)
        assert r.status == "ok"

    def test_missing_youtube_scope_is_fail(self, tmp_path):
        """youtube scope (フル URL) が欠けている: fail."""
        # force-ssl のみで youtube がない
        _write_token(tmp_path, [_SCOPE_FORCE_SSL, _SCOPE_ANALYTICS_RO])
        _write_meta_channel_id(tmp_path, _CHANNEL_ID)
        r = doctor.check_upload_ready(tmp_path)
        assert r.status == "fail"

    def test_missing_force_ssl_scope_is_fail(self, tmp_path):
        """youtube.force-ssl scope が欠けている: fail."""
        # youtube のみで force-ssl がない
        _write_token(tmp_path, [_SCOPE_YOUTUBE, _SCOPE_ANALYTICS_RO])
        _write_meta_channel_id(tmp_path, _CHANNEL_ID)
        r = doctor.check_upload_ready(tmp_path)
        assert r.status == "fail"

    def test_youtube_readonly_does_not_satisfy_youtube_scope(self, tmp_path):
        """youtube.readonly は youtube scope の代替にならない (部分一致禁止)."""
        readonly_scope = "https://www.googleapis.com/auth/youtube.readonly"
        _write_token(tmp_path, [readonly_scope, _SCOPE_FORCE_SSL])
        _write_meta_channel_id(tmp_path, _CHANNEL_ID)
        r = doctor.check_upload_ready(tmp_path)
        assert r.status == "fail"

    def test_empty_scopes_is_fail(self, tmp_path):
        """scopes リストが空: fail."""
        _write_token(tmp_path, [])
        _write_meta_channel_id(tmp_path, _CHANNEL_ID)
        r = doctor.check_upload_ready(tmp_path)
        assert r.status == "fail"

    def test_scope_fail_next_action_is_human(self, tmp_path):
        """scope 不足時の next_action は human (再認証案内)."""
        _write_token(tmp_path, [])
        _write_meta_channel_id(tmp_path, _CHANNEL_ID)
        r = doctor.check_upload_ready(tmp_path)
        assert r.next_action is not None
        assert r.next_action["kind"] == "human"
        assert "uv run yt-channel-status" in r.next_action["instructions"]
        _assert_no_bare_yt_channel_status(r.next_action)

    def test_channel_id_missing_key_is_fail(self, tmp_path):
        """meta.json に channel.channel_id キーがない: fail."""
        _write_token(tmp_path, _FULL_SCOPES)
        _write_meta_channel_id(tmp_path, None)  # channel_id キー自体なし
        r = doctor.check_upload_ready(tmp_path)
        assert r.status == "fail"

    def test_channel_id_empty_string_is_fail(self, tmp_path):
        """channel.channel_id が空文字: fail."""
        _write_token(tmp_path, _FULL_SCOPES)
        _write_meta_channel_id(tmp_path, "")
        r = doctor.check_upload_ready(tmp_path)
        assert r.status == "fail"

    def test_meta_json_absent_is_fail(self, tmp_path):
        """config/channel/meta.json が存在しない: fail."""
        _write_token(tmp_path, _FULL_SCOPES)
        # meta.json を書かない
        r = doctor.check_upload_ready(tmp_path)
        assert r.status == "fail"
        assert r.message == "config/channel/meta.json が存在しない"
        assert r.next_action is not None
        assert r.next_action["kind"] == "human"

    def test_channel_id_fail_next_action_is_human(self, tmp_path):
        """channel_id 未設定時の next_action は human (取得コマンド案内)."""
        _write_token(tmp_path, _FULL_SCOPES)
        _write_meta_channel_id(tmp_path, "")
        r = doctor.check_upload_ready(tmp_path)
        assert r.next_action is not None
        assert r.next_action["kind"] == "human"
        assert "uv run yt-channel-status" in r.next_action["instructions"]
        _assert_no_bare_yt_channel_status(r.next_action)

    def test_message_contains_all_issues_when_multiple(self, tmp_path):
        """scope 不足と channel_id 未設定が同時の場合、message に両方の事由が含まれる."""
        _write_token(tmp_path, [])
        _write_meta_channel_id(tmp_path, "")
        r = doctor.check_upload_ready(tmp_path)
        assert r.status == "fail"
        # 複数事由が message に記載されること
        assert r.message  # 空でない

    def test_channel_null_in_meta_is_fail_not_crash(self, tmp_path):
        """meta.json が {"channel": null} の場合、クラッシュせず fail を返す.

        .get("channel", {}) は null を返し None.get() で AttributeError になるバグの回帰テスト。
        (or {} 規約で null-safe に処理されること)
        """
        _write_token(tmp_path, _FULL_SCOPES)
        meta_dir = tmp_path / "config" / "channel"
        meta_dir.mkdir(parents=True, exist_ok=True)
        (meta_dir / "meta.json").write_text(json.dumps({"channel": None}), encoding="utf-8")
        # AttributeError ではなく CheckResult が返ること
        r = doctor.check_upload_ready(tmp_path)
        assert r.status == "fail"
        assert r.id == "upload_ready"

    def test_meta_toplevel_non_dict_is_fail_not_crash(self, tmp_path):
        """meta.json がトップレベル非 dict（null / [] / "str"）でも fail を返す."""
        _write_token(tmp_path, _FULL_SCOPES)
        meta_dir = tmp_path / "config" / "channel"
        meta_dir.mkdir(parents=True, exist_ok=True)
        for invalid_content in ["null", "[]", '"string"']:
            (meta_dir / "meta.json").write_text(invalid_content, encoding="utf-8")
            r = doctor.check_upload_ready(tmp_path)
            assert r.status == "fail", f"expected fail for meta.json={invalid_content}"
            assert r.id == "upload_ready"


# ---------------------------------------------------------------------------
# UPLOAD_REQUIRED_SCOPES 定数
# ---------------------------------------------------------------------------


class TestUploadRequiredScopes:
    def test_contains_youtube_full_url(self):
        """youtube フル URL が含まれている."""
        assert _SCOPE_YOUTUBE in doctor.UPLOAD_REQUIRED_SCOPES

    def test_contains_force_ssl_full_url(self):
        """youtube.force-ssl フル URL が含まれている."""
        assert _SCOPE_FORCE_SSL in doctor.UPLOAD_REQUIRED_SCOPES

    def test_scopes_are_full_https_urls(self):
        """全スコープがフル HTTPS URL 形式 (部分文字列でない)."""
        for scope in doctor.UPLOAD_REQUIRED_SCOPES:
            assert scope.startswith("https://www.googleapis.com/auth/")

    def test_does_not_include_readonly_scopes(self):
        """readonly 系 scope は含まない."""
        for scope in doctor.UPLOAD_REQUIRED_SCOPES:
            assert "readonly" not in scope

    def test_exactly_two_scopes(self):
        """必須 scope は youtube + youtube.force-ssl の 2 件."""
        assert len(doctor.UPLOAD_REQUIRED_SCOPES) == 2


# ---------------------------------------------------------------------------
# run_all_checks の拡張
# ---------------------------------------------------------------------------


class TestRunAllChecksExtended:
    def test_returns_19_checks(self, monkeypatch, tmp_path):
        """6 bootstrap + 11 api + 1 channel + 1 upload = 計 19 件."""
        monkeypatch.setattr(doctor, "_run", lambda *a, **kw: (127, "", "missing"))
        results = doctor.run_all_checks(tmp_path)
        assert len(results) == 19

    def test_existing_11_api_checks_present(self, monkeypatch, tmp_path):
        """既存 11 check が全て api カテゴリで含まれている."""
        monkeypatch.setattr(doctor, "_run", lambda *a, **kw: (127, "", "missing"))
        results = doctor.run_all_checks(tmp_path)
        api_results = [r for r in results if r.category == "api"]
        assert len(api_results) == 11

    def test_new_check_ids_present(self, monkeypatch, tmp_path):
        """bootstrap / channel / upload の check が含まれる."""
        monkeypatch.setattr(doctor, "_run", lambda *a, **kw: (127, "", "missing"))
        results = doctor.run_all_checks(tmp_path)
        ids = {r.id for r in results}
        assert "uv" in ids
        assert "uv_project" in ids
        assert "automation_package" in ids
        assert "skills_synced" in ids
        assert "channel_config" in ids
        assert "upload_ready" in ids

    def test_category_order_bootstrap_then_api_then_channel_then_upload(self, monkeypatch, tmp_path):
        """runway 順序: bootstrap → api → channel → upload."""
        monkeypatch.setattr(doctor, "_run", lambda *a, **kw: (127, "", "missing"))
        results = doctor.run_all_checks(tmp_path)
        categories = [r.category for r in results]

        last_bootstrap = max(i for i, c in enumerate(categories) if c == "bootstrap")
        first_api = next(i for i, c in enumerate(categories) if c == "api")
        last_api = max(i for i, c in enumerate(categories) if c == "api")
        first_channel = next(i for i, c in enumerate(categories) if c == "channel")
        first_upload = next(i for i, c in enumerate(categories) if c == "upload")

        assert last_bootstrap < first_api
        assert last_api < first_channel
        assert first_channel < first_upload

    def test_channel_config_is_only_channel_check(self, monkeypatch, tmp_path):
        """channel カテゴリは channel_config の 1 件のみ."""
        monkeypatch.setattr(doctor, "_run", lambda *a, **kw: (127, "", "missing"))
        results = doctor.run_all_checks(tmp_path)
        channel_results = [r for r in results if r.category == "channel"]
        assert len(channel_results) == 1
        assert channel_results[0].id == "channel_config"

    def test_bootstrap_checks_are_tool_setup_checks(self, monkeypatch, tmp_path):
        """bootstrap カテゴリはツール・automation 導入系 check のみ."""
        monkeypatch.setattr(doctor, "_run", lambda *a, **kw: (127, "", "missing"))
        results = doctor.run_all_checks(tmp_path)
        bootstrap_ids = {r.id for r in results if r.category == "bootstrap"}
        assert bootstrap_ids == {"ffmpeg", "ffprobe", "uv", "uv_project", "automation_package", "skills_synced"}

    def test_upload_ready_is_only_upload_check(self, monkeypatch, tmp_path):
        """upload カテゴリは upload_ready の 1 件のみ."""
        monkeypatch.setattr(doctor, "_run", lambda *a, **kw: (127, "", "missing"))
        results = doctor.run_all_checks(tmp_path)
        upload_results = [r for r in results if r.category == "upload"]
        assert len(upload_results) == 1
        assert upload_results[0].id == "upload_ready"


# ---------------------------------------------------------------------------
# render_table のカテゴリ別段階表示
# ---------------------------------------------------------------------------


class TestRenderTableCategories:
    def test_all_four_category_labels_in_output(self, monkeypatch, tmp_path):
        """render_table 出力に bootstrap / api / channel / upload のカテゴリラベルが含まれる."""
        monkeypatch.setattr(doctor, "_run", lambda *a, **kw: (127, "", "missing"))
        results = doctor.run_all_checks(tmp_path)
        summary = doctor.summarize(results)
        output = doctor.render_table(results, summary, tmp_path)
        lower = output.lower()
        assert "bootstrap" in lower
        assert "api" in lower
        assert "channel" in lower
        assert "upload" in lower

    def test_new_check_ids_appear_in_output(self, monkeypatch, tmp_path):
        """render_table に bootstrap / channel / upload の check id が含まれる."""
        monkeypatch.setattr(doctor, "_run", lambda *a, **kw: (127, "", "missing"))
        results = doctor.run_all_checks(tmp_path)
        summary = doctor.summarize(results)
        output = doctor.render_table(results, summary, tmp_path)
        assert "uv" in output
        assert "uv_project" in output
        assert "automation_package" in output
        assert "skills_synced" in output
        assert "channel_config" in output
        assert "upload_ready" in output

    def test_category_sections_ordered_in_output(self, monkeypatch, tmp_path):
        """出力内でのカテゴリ出現順: bootstrap → api → channel → upload."""
        monkeypatch.setattr(doctor, "_run", lambda *a, **kw: (127, "", "missing"))
        results = doctor.run_all_checks(tmp_path)
        summary = doctor.summarize(results)
        output = doctor.render_table(results, summary, tmp_path)

        # 各 check id の出現位置で順序を確認する（category label の形式に依存しない）
        pos_ffmpeg = output.find("ffmpeg")
        pos_gcloud = output.find("gcloud")
        pos_channel_config = output.find("channel_config")
        pos_upload_ready = output.find("upload_ready")

        assert pos_ffmpeg < pos_gcloud
        assert pos_gcloud < pos_channel_config
        assert pos_channel_config < pos_upload_ready
