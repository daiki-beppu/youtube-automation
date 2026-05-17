"""yt-doctor の単体テスト"""

from __future__ import annotations

import json

import pytest

from youtube_automation.cli import doctor


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
            "GOOGLE_CLOUD_PROJECT=foo\n"
            "GOOGLE_CLOUD_LOCATION=us-central1\n"
            "GOOGLE_GENAI_USE_VERTEXAI=true\n",
            encoding="utf-8",
        )
        r = doctor.check_env_file(tmp_path)
        assert r.status == "ok"

    def test_partial(self, tmp_path):
        (tmp_path / ".env").write_text(
            "GOOGLE_CLOUD_PROJECT=foo\n", encoding="utf-8"
        )
        r = doctor.check_env_file(tmp_path)
        assert r.status == "warn"


class TestClientSecrets:
    def test_missing_without_project(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        r = doctor.check_client_secrets(tmp_path)
        assert r.status == "fail"
        assert r.next_action["kind"] == "human"
        assert "credentials" in r.next_action["url"]

    def test_missing_with_project(self, tmp_path):
        (tmp_path / ".env").write_text(
            "GOOGLE_CLOUD_PROJECT=foo-proj\n", encoding="utf-8"
        )
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
        (auth / "client_secrets.json").write_text(
            json.dumps({"installed": {"client_id": "x"}}), encoding="utf-8"
        )
        r = doctor.check_client_secrets(tmp_path)
        assert r.status == "fail"


class TestOAuthToken:
    def test_missing(self, tmp_path):
        r = doctor.check_oauth_token(tmp_path)
        assert r.status == "fail"
        assert r.next_action["kind"] == "ai-exec"

    def test_valid(self, tmp_path):
        auth = tmp_path / "auth"
        auth.mkdir()
        (auth / "token.json").write_text(
            json.dumps({"scopes": ["a", "b"]}), encoding="utf-8"
        )
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
        assert len(payload["checks"]) == 11
        for c in payload["checks"]:
            assert c["status"] in ("ok", "warn", "fail", "unknown")

    def test_human_output(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(doctor, "_run", lambda *a, **kw: (127, "", "missing"))
        monkeypatch.setattr(doctor, "resolve_channel_dir", lambda t: tmp_path)
        code = doctor.main([])
        assert code == 0
        out = capsys.readouterr().out
        assert "summary:" in out
        assert "channel_dir:" in out
