"""yt-doctor bootstrap カテゴリ (ffmpeg/ffprobe) の単体テスト"""

from __future__ import annotations

import json

from youtube_automation.cli import doctor

# ---------------------------------------------------------------------------
# check_ffmpeg
# ---------------------------------------------------------------------------


class TestCheckFfmpeg:
    def test_ok_when_installed(self, monkeypatch):
        """ffmpeg がインストール済みの場合: ok."""
        monkeypatch.setattr("shutil.which", lambda cmd: f"/usr/local/bin/{cmd}" if cmd == "ffmpeg" else None)
        r = doctor.check_ffmpeg()
        assert r.status == "ok"
        assert r.category == "bootstrap"
        assert r.id == "ffmpeg"
        assert "/usr/local/bin/ffmpeg" in r.message

    def test_fail_when_missing(self, monkeypatch):
        """ffmpeg が見つからない場合: fail + インストール手順."""
        monkeypatch.setattr("shutil.which", lambda cmd: None)
        r = doctor.check_ffmpeg()
        assert r.status == "fail"
        assert r.category == "bootstrap"
        assert r.id == "ffmpeg"
        assert r.next_action is not None
        assert r.next_action["kind"] == "human"
        assert "brew install ffmpeg" in r.next_action["instructions"]
        assert "apt-get" in r.next_action["instructions"]


# ---------------------------------------------------------------------------
# check_ffprobe
# ---------------------------------------------------------------------------


class TestCheckFfprobe:
    def test_ok_when_installed(self, monkeypatch):
        """ffprobe がインストール済みの場合: ok."""
        monkeypatch.setattr("shutil.which", lambda cmd: f"/usr/local/bin/{cmd}" if cmd == "ffprobe" else None)
        r = doctor.check_ffprobe()
        assert r.status == "ok"
        assert r.category == "bootstrap"
        assert r.id == "ffprobe"
        assert "/usr/local/bin/ffprobe" in r.message

    def test_fail_when_missing(self, monkeypatch):
        """ffprobe が見つからない場合: fail + インストール手順."""
        monkeypatch.setattr("shutil.which", lambda cmd: None)
        r = doctor.check_ffprobe()
        assert r.status == "fail"
        assert r.category == "bootstrap"
        assert r.id == "ffprobe"
        assert r.next_action is not None
        assert r.next_action["kind"] == "human"
        assert "brew install ffmpeg" in r.next_action["instructions"]


# ---------------------------------------------------------------------------
# 4 パターン組み合わせテスト
# ---------------------------------------------------------------------------


class TestSystemChecksCombinations:
    """shutil.which を monkey patch して 4 パターンを検証する."""

    def _make_which(self, *, ffmpeg: bool, ffprobe: bool):
        """ffmpeg/ffprobe の有無を制御する shutil.which の stub."""

        def fake_which(cmd):
            if cmd == "ffmpeg" and ffmpeg:
                return "/usr/local/bin/ffmpeg"
            if cmd == "ffprobe" and ffprobe:
                return "/usr/local/bin/ffprobe"
            return None

        return fake_which

    def test_both_installed(self, monkeypatch):
        """(a) 両方インストール済み: 両方 ok."""
        monkeypatch.setattr("shutil.which", self._make_which(ffmpeg=True, ffprobe=True))
        assert doctor.check_ffmpeg().status == "ok"
        assert doctor.check_ffprobe().status == "ok"

    def test_ffmpeg_only_missing(self, monkeypatch):
        """(b) ffmpeg のみ欠落: ffmpeg=fail, ffprobe=ok."""
        monkeypatch.setattr("shutil.which", self._make_which(ffmpeg=False, ffprobe=True))
        assert doctor.check_ffmpeg().status == "fail"
        assert doctor.check_ffprobe().status == "ok"

    def test_ffprobe_only_missing(self, monkeypatch):
        """(c) ffprobe のみ欠落: ffmpeg=ok, ffprobe=fail."""
        monkeypatch.setattr("shutil.which", self._make_which(ffmpeg=True, ffprobe=False))
        assert doctor.check_ffmpeg().status == "ok"
        assert doctor.check_ffprobe().status == "fail"

    def test_both_missing(self, monkeypatch):
        """(d) 両方欠落: 両方 fail."""
        monkeypatch.setattr("shutil.which", self._make_which(ffmpeg=False, ffprobe=False))
        assert doctor.check_ffmpeg().status == "fail"
        assert doctor.check_ffprobe().status == "fail"


# ---------------------------------------------------------------------------
# run_all_checks に bootstrap カテゴリが含まれること
# ---------------------------------------------------------------------------


class TestRunAllChecksWithBootstrap:
    def test_bootstrap_checks_present(self, monkeypatch, tmp_path):
        """run_all_checks に ffmpeg / ffprobe が含まれる."""
        monkeypatch.setattr(doctor, "_run", lambda *a, **kw: (127, "", "missing"))
        results = doctor.run_all_checks(tmp_path)
        ids = {r.id for r in results}
        assert "ffmpeg" in ids
        assert "ffprobe" in ids

    def test_bootstrap_checks_count(self, monkeypatch, tmp_path):
        """bootstrap は ffmpeg + ffprobe + uv + uv project + automation + skills + numbered duplicates の 7 件."""
        monkeypatch.setattr(doctor, "_run", lambda *a, **kw: (127, "", "missing"))
        results = doctor.run_all_checks(tmp_path)
        bootstrap_results = [r for r in results if r.category == "bootstrap"]
        assert len(bootstrap_results) == 7

    def test_total_checks_is_26(self, monkeypatch, tmp_path):
        """7 bootstrap + 11 api + 3 channel + 4 data + 1 upload = 計 26 件."""
        monkeypatch.setattr(doctor, "_run", lambda *a, **kw: (127, "", "missing"))
        results = doctor.run_all_checks(tmp_path)
        assert len(results) == 26

    def test_bootstrap_before_api(self, monkeypatch, tmp_path):
        """bootstrap カテゴリは api カテゴリより前に配置される."""
        monkeypatch.setattr(doctor, "_run", lambda *a, **kw: (127, "", "missing"))
        results = doctor.run_all_checks(tmp_path)
        categories = [r.category for r in results]

        last_bootstrap = max(i for i, c in enumerate(categories) if c == "bootstrap")
        first_api = next(i for i, c in enumerate(categories) if c == "api")
        assert last_bootstrap < first_api


# ---------------------------------------------------------------------------
# render_table / JSON 出力に bootstrap が含まれること
# ---------------------------------------------------------------------------


class TestBootstrapInOutput:
    def test_bootstrap_category_in_table(self, monkeypatch, tmp_path):
        """render_table 出力に bootstrap カテゴリラベルが含まれる."""
        monkeypatch.setattr(doctor, "_run", lambda *a, **kw: (127, "", "missing"))
        results = doctor.run_all_checks(tmp_path)
        summary = doctor.summarize(results)
        output = doctor.render_table(results, summary, tmp_path)
        assert "bootstrap" in output.lower()
        assert "ffmpeg" in output
        assert "ffprobe" in output

    def test_bootstrap_category_in_json(self, monkeypatch, tmp_path, capsys):
        """--json 出力に bootstrap カテゴリが含まれる."""
        monkeypatch.setattr(doctor, "_run", lambda *a, **kw: (127, "", "missing"))
        monkeypatch.setattr(doctor, "resolve_channel_dir", lambda t: tmp_path)
        doctor.main(["--json"])
        out = capsys.readouterr().out
        payload = json.loads(out)
        categories = {c["category"] for c in payload["checks"]}
        assert "bootstrap" in categories

    def test_bootstrap_appears_first_in_table(self, monkeypatch, tmp_path):
        """render_table で bootstrap が api より先に出現する."""
        monkeypatch.setattr(doctor, "_run", lambda *a, **kw: (127, "", "missing"))
        results = doctor.run_all_checks(tmp_path)
        summary = doctor.summarize(results)
        output = doctor.render_table(results, summary, tmp_path)
        pos_ffmpeg = output.find("ffmpeg")
        pos_gcloud = output.find("gcloud")
        assert pos_ffmpeg < pos_gcloud
