"""yt-pinned-comment (scripts/pinned_comment.py) の単体テスト.

preflight skip 分岐・冪等性・video_id fallback chain を fake YouTube サービスで検証する
（実 API・OAuth には依存しない）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from googleapiclient.errors import HttpError

from youtube_automation.infrastructure.errors import ValidationError, YouTubeAPIError
from youtube_automation.scripts import pinned_comment
from youtube_automation.scripts.pinned_comment import (
    build_plan,
    fetch_video_status,
    fetch_video_title,
    load_history,
    render_template,
    resolve_targets_from_collection,
    save_history,
)

# ----- fake YouTube service ------------------------------------------------


class _FakeResp:
    def __init__(self, status: int):
        self.status = status
        self.reason = "error"


def _http_error(status: int) -> HttpError:
    return HttpError(resp=_FakeResp(status), content=b'{"error": {"message": "boom"}}')


class _FakeRequest:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error

    def execute(self):
        if self._error is not None:
            raise self._error
        return self._result


class _FakeVideos:
    def __init__(self, yt: "FakeYouTube"):
        self.yt = yt

    def list(self, part, id):
        ids = id.split(",")
        self.yt.status_calls.append(ids)
        items = []
        for vid in ids:
            if part == "status" and vid in self.yt.status_items:
                items.append({"id": vid, "status": self.yt.status_items[vid]})
            elif part == "snippet" and vid in self.yt.snippet_titles:
                items.append({"id": vid, "snippet": {"title": self.yt.snippet_titles[vid]}})
        return _FakeRequest({"items": items})


class _FakeCommentThreads:
    def __init__(self, yt: "FakeYouTube"):
        self.yt = yt

    def insert(self, part, body):
        vid = body["snippet"]["videoId"]
        text = body["snippet"]["topLevelComment"]["snippet"]["textOriginal"]
        if self.yt.insert_error is not None:
            return _FakeRequest(error=_http_error(self.yt.insert_error))
        self.yt.inserted.append((vid, text))
        return _FakeRequest({"snippet": {"topLevelComment": {"id": f"cid-{vid}"}}})


class FakeYouTube:
    def __init__(self, *, status_items=None, snippet_titles=None, insert_error=None):
        self.status_items = status_items or {}
        self.snippet_titles = snippet_titles or {}
        self.insert_error = insert_error
        self.inserted: list[tuple[str, str]] = []
        self.status_calls: list[list[str]] = []

    def videos(self):
        return _FakeVideos(self)

    def commentThreads(self):
        return _FakeCommentThreads(self)


def _empty_history() -> dict:
    return {"schema_version": 1, "posted": {}}


# ----- render_template -----------------------------------------------------


def test_render_template_expands_placeholders():
    out = render_template(
        "{scene_phrase} {scene_emoji} | {video_title} | {theme}",
        video_title="Night Rain",
        scene_phrase="Quiet drift",
        theme="rain",
        scene_emoji="🌙",
    )
    assert out == "Quiet drift 🌙 | Night Rain | rain"


def test_render_template_tolerates_missing_kwargs():
    # 一部プレースホルダのみ使うテンプレートでも全 4 キーを渡すので KeyError にならない
    assert render_template("just {scene_phrase}", scene_phrase="x") == "just x"


# ----- history load/save ---------------------------------------------------


def test_load_history_missing_returns_empty(tmp_path):
    h = load_history(tmp_path / "nope.json")
    assert h == {"schema_version": 1, "posted": {}}


def test_save_history_atomic_no_tmp_left(tmp_path):
    path = tmp_path / "sub" / "hist.json"
    save_history(path, {"schema_version": 1, "posted": {"v1": {"comment_id": "c"}}})
    assert path.exists()
    assert not path.with_suffix(".json.tmp").exists()
    reloaded = load_history(path)
    assert reloaded["posted"]["v1"]["comment_id"] == "c"


# ----- build_plan: preflight skip 分岐 -------------------------------------

_TEMPLATE = "{scene_phrase} {scene_emoji}"


def _state(scene_phrase="hello", emoji="🌙"):
    return {
        "scene_phrases": {"en": scene_phrase, "ja": scene_phrase},
        "planning": {"scene_emoji": emoji, "final_title_en": "Title"},
        "theme": "calm",
    }


def test_build_plan_skips_already_posted():
    history = {"schema_version": 1, "posted": {"v1": {"comment_id": "old"}}}
    plan = build_plan(
        [("v1", _state())],
        history=history,
        status_map={"v1": {"privacyStatus": "public"}},
        template=_TEMPLATE,
        lang="en",
        dry_run=True,
    )
    assert plan["planned"] == []
    assert plan["skipped"] == [{"video_id": "v1", "reason": "already_posted"}]


def test_build_plan_skips_video_not_found():
    plan = build_plan(
        [("gone", _state())],
        history=_empty_history(),
        status_map={"gone": None},  # YouTube 上に存在しない
        template=_TEMPLATE,
        lang="en",
        dry_run=True,
    )
    assert plan["skipped"] == [{"video_id": "gone", "reason": "video_not_found"}]


def test_build_plan_skips_video_private():
    plan = build_plan(
        [("priv", _state())],
        history=_empty_history(),
        status_map={"priv": {"privacyStatus": "private"}},
        template=_TEMPLATE,
        lang="en",
        dry_run=True,
    )
    assert plan["skipped"] == [{"video_id": "priv", "reason": "video_private"}]


def test_build_plan_passes_unlisted():
    plan = build_plan(
        [("unl", _state(scene_phrase="drift", emoji="✨"))],
        history=_empty_history(),
        status_map={"unl": {"privacyStatus": "unlisted"}},
        template=_TEMPLATE,
        lang="en",
        dry_run=True,
    )
    assert plan["skipped"] == []
    assert len(plan["planned"]) == 1
    assert plan["planned"][0]["text"] == "drift ✨"


# ----- build_plan: dry-run vs apply / 冪等性 --------------------------------


def test_build_plan_dry_run_does_not_post_or_write_history(tmp_path):
    history = _empty_history()
    history_path = tmp_path / "hist.json"
    yt = FakeYouTube(status_items={"v1": {"privacyStatus": "public"}})
    plan = build_plan(
        [("v1", _state())],
        history=history,
        status_map={"v1": {"privacyStatus": "public"}},
        template=_TEMPLATE,
        lang="en",
        dry_run=True,
        youtube=yt,
        history_path=history_path,
    )
    assert plan["posted"] == []
    assert yt.inserted == []
    assert history["posted"] == {}
    assert not history_path.exists()


def test_build_plan_apply_posts_records_and_is_idempotent(tmp_path):
    history = _empty_history()
    history_path = tmp_path / "hist.json"
    yt = FakeYouTube()

    plan = build_plan(
        [("v1", _state(scene_phrase="rainy", emoji="🌧️"))],
        history=history,
        status_map={"v1": {"privacyStatus": "public"}},
        template=_TEMPLATE,
        lang="en",
        dry_run=False,
        youtube=yt,
        history_path=history_path,
    )
    assert yt.inserted == [("v1", "rainy 🌧️")]
    assert len(plan["posted"]) == 1
    assert plan["posted"][0]["comment_id"] == "cid-v1"
    # history が atomic write で更新されている
    assert history_path.exists()
    assert "v1" in load_history(history_path)["posted"]

    # 再実行: 同じ history を渡すと already_posted で skip（冪等性）
    yt2 = FakeYouTube()
    plan2 = build_plan(
        [("v1", _state())],
        history=history,
        status_map={"v1": {"privacyStatus": "public"}},
        template=_TEMPLATE,
        lang="en",
        dry_run=False,
        youtube=yt2,
        history_path=history_path,
    )
    assert yt2.inserted == []
    assert plan2["skipped"] == [{"video_id": "v1", "reason": "already_posted"}]


def test_build_plan_apply_records_insert_error():
    yt = FakeYouTube(insert_error=403)
    plan = build_plan(
        [("v1", _state())],
        history=_empty_history(),
        status_map={"v1": {"privacyStatus": "public"}},
        template=_TEMPLATE,
        lang="en",
        dry_run=False,
        youtube=yt,
    )
    assert plan["posted"] == []
    assert len(plan["errors"]) == 1
    assert "status=403" in plan["errors"][0]["error"]


def test_build_plan_video_id_path_fetches_title():
    # state=None（--video-id 経路）では snippet タイトルを scene_phrase に使う
    yt = FakeYouTube(snippet_titles={"v9": "Fetched Title"})
    plan = build_plan(
        [("v9", None)],
        history=_empty_history(),
        status_map={"v9": {"privacyStatus": "public"}},
        template="{scene_phrase}",
        lang="en",
        dry_run=True,
        youtube=yt,
    )
    assert plan["planned"][0]["text"] == "Fetched Title"


# ----- fetch_video_status --------------------------------------------------


def test_fetch_video_status_marks_missing_as_none():
    yt = FakeYouTube(status_items={"a": {"privacyStatus": "public"}})
    result = fetch_video_status(yt, ["a", "b"])
    assert result["a"] == {"privacyStatus": "public"}
    assert result["b"] is None


def test_fetch_video_status_chunks_by_50():
    yt = FakeYouTube(status_items={f"v{i}": {"privacyStatus": "public"} for i in range(120)})
    fetch_video_status(yt, [f"v{i}" for i in range(120)])
    # 120 件 → 50/50/20 の 3 チャンク
    assert [len(c) for c in yt.status_calls] == [50, 50, 20]


def test_fetch_video_status_raises_on_http_error():
    class _Boom(FakeYouTube):
        def videos(self):
            class _V:
                def list(self, part, id):
                    return _FakeRequest(error=_http_error(500))

            return _V()

    with pytest.raises(YouTubeAPIError):
        fetch_video_status(_Boom(), ["a"])


# ----- resolve_targets_from_collection (video_id fallback chain) -----------


def _make_collection(tmp_path: Path, *, tracking=None, workflow=None) -> Path:
    col = tmp_path / "20260101-test-collection"
    (col / "20-documentation").mkdir(parents=True)
    if tracking is not None:
        (col / "20-documentation" / "upload_tracking.json").write_text(json.dumps(tracking), encoding="utf-8")
    if workflow is not None:
        (col / "workflow-state.json").write_text(json.dumps(workflow), encoding="utf-8")
    return col


def test_resolve_prefers_tracking_video_id(tmp_path):
    col = _make_collection(
        tmp_path,
        tracking={"complete_collection": {"video_id": "TRACK1"}},
        workflow={"upload": {"video_id": "WF1"}, "scene_phrases": {"en": "x"}},
    )
    targets = resolve_targets_from_collection(col)
    assert targets[0][0] == "TRACK1"
    assert targets[0][1]["upload"]["video_id"] == "WF1"  # state も返る


def test_resolve_falls_back_to_workflow_upload_video_id(tmp_path):
    col = _make_collection(tmp_path, workflow={"upload": {"video_id": "WF1"}})
    targets = resolve_targets_from_collection(col)
    assert targets[0][0] == "WF1"


def test_resolve_falls_back_to_toplevel_video_id(tmp_path):
    col = _make_collection(tmp_path, workflow={"video_id": "TOP1"})
    targets = resolve_targets_from_collection(col)
    assert targets[0][0] == "TOP1"


def test_resolve_raises_when_no_video_id(tmp_path):
    col = _make_collection(tmp_path, workflow={"scene_phrases": {"en": "x"}})
    with pytest.raises(ValidationError, match="video_id を解決できません"):
        resolve_targets_from_collection(col)


# ----- quota 記録の配線 (Issue #2061) ---------------------------------------


@pytest.fixture
def quota_calls(monkeypatch) -> list[dict]:
    """log_quota をレコーダに差し替え、配線（bucket / units / 回数）を検証する。"""
    calls: list[dict] = []

    def _record(service, bucket, units, *, metadata=None):
        entry = {"service": service, "bucket": bucket, "units": units, "metadata": dict(metadata or {})}
        calls.append(entry)
        return entry

    monkeypatch.setattr(pinned_comment, "log_quota", _record)
    return calls


def test_fetch_video_status_records_quota_per_request(quota_calls):
    """要件 1: videos.list の request（chunk）ごとに quota が 1 unit 記録される。"""
    yt = FakeYouTube(status_items={f"v{i}": {"privacyStatus": "public"} for i in range(120)})
    fetch_video_status(yt, [f"v{i}" for i in range(120)])
    # 120 件 → 50/50/20 の 3 リクエスト → 3 記録
    assert [(c["service"], c["bucket"], c["units"]) for c in quota_calls] == [
        ("youtube-data-api", "videos.list", 1)
    ] * 3
    assert [c["metadata"]["video_count"] for c in quota_calls] == [50, 50, 20]


def test_fetch_video_status_records_quota_on_http_error(quota_calls):
    """HttpError（API 処理済み = quota 消費済み）でも記録した上で例外変換される。"""

    class _Boom(FakeYouTube):
        def videos(self):
            class _V:
                def list(self, part, id):
                    return _FakeRequest(error=_http_error(500))

            return _V()

    with pytest.raises(YouTubeAPIError):
        fetch_video_status(_Boom(), ["a"])
    assert len(quota_calls) == 1
    assert quota_calls[0]["bucket"] == "videos.list"
    assert quota_calls[0]["metadata"]["error"] is True


def test_fetch_video_title_records_quota(quota_calls):
    """--video-id 経路のタイトル取得（videos.list）も記録される。"""
    yt = FakeYouTube(snippet_titles={"v9": "Fetched Title"})
    fetch_video_title(yt, "v9")
    assert [(c["bucket"], c["units"]) for c in quota_calls] == [("videos.list", 1)]
    assert quota_calls[0]["metadata"]["video_id"] == "v9"


def test_build_plan_apply_records_insert_quota_once(quota_calls):
    """要件 2: comment 作成 → commentThreads.insert quota が 1 回（50 units）記録される。"""
    yt = FakeYouTube()
    build_plan(
        [("v1", _state())],
        history=_empty_history(),
        status_map={"v1": {"privacyStatus": "public"}},
        template=_TEMPLATE,
        lang="en",
        dry_run=False,
        youtube=yt,
    )
    inserts = [c for c in quota_calls if c["bucket"] == "commentThreads.insert"]
    assert [(c["service"], c["units"]) for c in inserts] == [("youtube-data-api", 50)]
    assert inserts[0]["metadata"] == {"context": "pinned_comment.insert", "video_id": "v1"}


def test_build_plan_dry_run_records_no_insert_quota(quota_calls):
    """要件 3: dry-run では write（insert）quota は記録されない。"""
    yt = FakeYouTube()
    build_plan(
        [("v1", _state())],
        history=_empty_history(),
        status_map={"v1": {"privacyStatus": "public"}},
        template=_TEMPLATE,
        lang="en",
        dry_run=True,
        youtube=yt,
    )
    assert [c for c in quota_calls if c["bucket"] == "commentThreads.insert"] == []


def test_build_plan_skip_records_no_insert_quota(quota_calls):
    """要件 3: skip（already_posted / private / not_found）では insert quota は記録されない。"""
    yt = FakeYouTube()
    build_plan(
        [("done", _state()), ("priv", _state()), ("gone", _state())],
        history={"schema_version": 1, "posted": {"done": {"comment_id": "old"}}},
        status_map={"priv": {"privacyStatus": "private"}, "gone": None},
        template=_TEMPLATE,
        lang="en",
        dry_run=False,
        youtube=yt,
    )
    assert quota_calls == []


def test_build_plan_insert_failure_records_quota_and_keeps_error(quota_calls):
    """要件 4: insert failure でも quota 記録後に元のエラーハンドリングが維持される。"""
    yt = FakeYouTube(insert_error=403)
    plan = build_plan(
        [("v1", _state())],
        history=_empty_history(),
        status_map={"v1": {"privacyStatus": "public"}},
        template=_TEMPLATE,
        lang="en",
        dry_run=False,
        youtube=yt,
    )
    inserts = [c for c in quota_calls if c["bucket"] == "commentThreads.insert"]
    assert [(c["units"], c["metadata"]["error"]) for c in inserts] == [(50, True)]
    # 元例外の扱い（errors への記録）が維持されている
    assert plan["posted"] == []
    assert len(plan["errors"]) == 1
    assert "status=403" in plan["errors"][0]["error"]
