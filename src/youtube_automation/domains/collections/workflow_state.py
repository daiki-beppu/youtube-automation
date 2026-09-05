"""workflow-state.json の document object と安全な永続化境界。"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Iterator, Mapping, MutableMapping
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Literal, TypedDict, cast

from youtube_automation.core.errors import ValidationError, WorkflowStateError, WorkflowStateSectionTypeError
from youtube_automation.domains.media_store import MediaKey
from youtube_automation.infrastructure.filesystem import JSONValue, file_lock

Phase = Literal["planning", "prepared", "cloud_owned", "mastered", "publishing", "complete"]
Stage = Literal["planning", "live"]
MusicEngine = Literal["suno", "lyria", "minimax"]
HandoffPoint = Literal["suno_download"]
ExecutionOwner = Literal["local", "cloud"]
WorkflowStateUpdater = Callable[["WorkflowState"], "WorkflowState | None"]
AssetKey = Literal[
    "thumbnail",
    "loop_video",
    "music_prompts",
    "music_downloaded",
    "raw_master",
    "master_audio",
    "master_video",
    "description",
]
PlanningKey = Literal["generated", "final_title", "target_persona", "publish_target_at", "music", "playlists"]


class MusicPlanningDocument(TypedDict, total=False):
    engine: MusicEngine
    mood: list[str]
    atmosphere: str
    tempo: Literal["very slow", "slow", "gentle", "moderate", "lively"]
    instruments: list[str]
    exclude: list[str]
    suno_playlist_url: str | None


class PlanningDocument(TypedDict, total=False):
    music: MusicPlanningDocument
    activities: str
    target_persona: str
    final_title: str
    generated: bool
    playlists: list[str]


class AssetsDocument(TypedDict, total=False):
    thumbnail: bool
    loop_video: bool | Literal["failed"]
    music_prompts: bool
    music_downloaded: bool
    raw_master: str | None
    master_audio: str | None
    master_video: str | None
    description: bool


class HandoffDocument(TypedDict, total=False):
    point: HandoffPoint
    owner: ExecutionOwner
    manifest_key: str
    root_sha256: str


class HumanTaskCompletionDocument(TypedDict, total=False):
    completed_at: str


class HumanTasksDocument(TypedDict, total=False):
    distrokid_submission: HumanTaskCompletionDocument


class MusicPairSelectionExceptionDocument(TypedDict, total=False):
    prompt_index: int
    variant: str | None
    title: str
    source: str
    duration_sec: float
    max_song_sec: float
    reason: str


class MusicPairSelectionDocument(TypedDict, total=False):
    updated_at: str
    exceptions_over_limit_count: int
    exceptions_over_limit: list[MusicPairSelectionExceptionDocument]


class UploadDocument(TypedDict, total=False):
    video_id: str | None
    video_url: str | None
    publish_at: str | None


class PostUploadShortDocument(TypedDict, total=False):
    short_num: int | None
    video_id: str
    uploaded_at: str
    publish_at: str | None
    resume_session_uri: str


class PostUploadDocument(TypedDict, total=False):
    shorts: list[PostUploadShortDocument]


class ThumbnailRankingDocument(TypedDict, total=False):
    candidate: str
    distance: float
    width: int
    height: int
    eligible: bool
    reasons: list[str]


class ThumbnailReferenceDiagnosticDocument(TypedDict, total=False):
    reference_image: str
    distance: float
    outlier: bool


class ThumbnailReferenceDiagnosticsDocument(TypedDict, total=False):
    max_reference_distance: float
    references: list[ThumbnailReferenceDiagnosticDocument]


class ThumbnailAutoSelectionDocument(TypedDict, total=False):
    schema_version: int
    mode: Literal["selection_only", "full"]
    selected: str
    distance: float
    ranking: list[ThumbnailRankingDocument]
    reference_images: list[str]
    reference_diagnostics: ThumbnailReferenceDiagnosticsDocument
    executed_at: str


class TitleTemplateCheckDocument(TypedDict, total=False):
    allow_volume_patterns: bool


class WorkflowStateDocument(TypedDict, total=False):
    """workflow-state.json の schema 正本。未知キーは document object が保持する。"""

    collection_name: str
    theme: str
    created_at: str
    updated_at: str
    stage: Stage
    phase: Phase
    selected_plan: Literal["A", "B", "C", "D", "E"]
    track_count: int
    planning: PlanningDocument
    scene_phrases: dict[str, str]
    title_template_check: TitleTemplateCheckDocument
    assets: AssetsDocument
    handoff: HandoffDocument
    human_tasks: HumanTasksDocument
    music_prompt_approved_digest: str
    music_pair_selection: MusicPairSelectionDocument
    upload: UploadDocument
    post_upload: PostUploadDocument
    track_display_names: dict[str, str]
    title_activity: str
    thumbnail_auto_selection: ThumbnailAutoSelectionDocument


_PHASES = frozenset({"planning", "prepared", "cloud_owned", "mastered", "publishing", "complete"})
_STAGES = frozenset({"planning", "live"})
_MUSIC_ENGINES = frozenset({"suno", "lyria", "minimax"})
_MUSIC_TEMPOS = frozenset({"very slow", "slow", "gentle", "moderate", "lively"})


class _UnsetType:
    pass


_UNSET = _UnsetType()
_KNOWN_OBJECT_SECTIONS = frozenset(
    {
        "assets",
        "description",
        "handoff",
        "human_tasks",
        "music_pair_selection",
        "planning",
        "post_upload",
        "scene_phrases",
        "thumbnail",
        "thumbnail_auto_selection",
        "title_template_check",
        "upload",
    }
)


def _optional_string(data: Mapping[str, JSONValue], key: str, label: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise WorkflowStateError(f"{label} must be a string or null")
    return value


def _optional_bool(data: Mapping[str, JSONValue], key: str, label: str) -> bool | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise WorkflowStateError(f"{label} must be a boolean or null")
    return value


class _ObjectSection(MutableMapping[str, JSONValue]):
    def __init__(self, data: dict[str, JSONValue]) -> None:
        self._data = data

    def __getitem__(self, key: str) -> JSONValue:
        return deepcopy(self._data[key])

    def __setitem__(self, key: str, value: JSONValue) -> None:
        self._data[key] = deepcopy(value)

    def __delitem__(self, key: str) -> None:
        del self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


class AssetsState(_ObjectSection):
    """生成済み collection assets の型付き view。"""

    @property
    def thumbnail(self) -> bool | None:
        if "thumbnail" not in self._data:
            return None
        value = self._data["thumbnail"]
        if isinstance(value, bool):
            return value
        raise WorkflowStateError("workflow-state.json::assets.thumbnail must be a boolean")

    @thumbnail.setter
    def thumbnail(self, value: bool) -> None:
        if not isinstance(value, bool):
            raise WorkflowStateError("workflow-state.json::assets.thumbnail must be a boolean")
        self._data["thumbnail"] = value

    @property
    def description(self) -> bool | None:
        return _optional_bool(self._data, "description", "workflow-state.json::assets.description")

    @description.setter
    def description(self, value: bool) -> None:
        self._data["description"] = value

    @property
    def music_downloaded(self) -> bool | None:
        return _optional_bool(self._data, "music_downloaded", "workflow-state.json::assets.music_downloaded")

    @property
    def raw_master(self) -> str | None:
        return _optional_string(self._data, "raw_master", "workflow-state.json::assets.raw_master")

    @raw_master.setter
    def raw_master(self, value: str | None) -> None:
        self._data["raw_master"] = value

    @property
    def master_audio(self) -> str | None:
        return _optional_string(self._data, "master_audio", "workflow-state.json::assets.master_audio")

    @master_audio.setter
    def master_audio(self, value: str | None) -> None:
        self._data["master_audio"] = value

    @property
    def master_video(self) -> str | None:
        return _optional_string(self._data, "master_video", "workflow-state.json::assets.master_video")

    @master_video.setter
    def master_video(self, value: str | None) -> None:
        self._data["master_video"] = value

    def set_known(self, key: AssetKey, value: JSONValue) -> None:
        """CLI が公開する asset key を schema 検証して更新する。"""
        if key == "thumbnail":
            if not isinstance(value, bool):
                raise WorkflowStateError("workflow-state.json::assets.thumbnail must be a boolean")
        elif key == "loop_video":
            if not isinstance(value, bool) and value != "failed":
                raise WorkflowStateError("workflow-state.json::assets.loop_video must be a boolean or 'failed'")
        elif key in {"music_prompts", "music_downloaded", "description"}:
            if not isinstance(value, bool):
                raise WorkflowStateError(f"workflow-state.json::assets.{key} must be a boolean")
        elif value is not None and not isinstance(value, str):
            raise WorkflowStateError(f"workflow-state.json::assets.{key} must be a string or null")
        self._data[key] = deepcopy(value)


class MusicPlanningState(_ObjectSection):
    """planning.music の型付き view。"""

    @property
    def engine(self) -> MusicEngine | None:
        value = _optional_string(self._data, "engine", "workflow-state.json::planning.music.engine")
        if value is None:
            return None
        if value not in _MUSIC_ENGINES:
            raise WorkflowStateError(f"unsupported workflow-state music engine: {value}")
        return cast(MusicEngine, value)

    @engine.setter
    def engine(self, value: MusicEngine) -> None:
        self._data["engine"] = value

    @property
    def expected_file_count(self) -> int | None:
        value = self._data.get("expected_file_count")
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise WorkflowStateError(
                "workflow-state.json::planning.music.expected_file_count must be a non-negative integer"
            )
        return value

    @property
    def patterns(self) -> dict[str, JSONValue] | None:
        value = self._data.get("patterns")
        if value is None:
            return None
        if not isinstance(value, dict):
            raise WorkflowStateError("workflow-state.json::planning.music.patterns must be an object")
        return deepcopy(value)

    def validate_known(self) -> None:
        """CLI から受け取る既知 field の型を検証する。"""
        _engine = self.engine
        _expected_file_count = self.expected_file_count
        for key in ("mood", "instruments", "exclude"):
            value = self._data.get(key)
            if value is not None and (not isinstance(value, list) or not all(isinstance(item, str) for item in value)):
                raise WorkflowStateError(f"workflow-state.json::planning.music.{key} must be an array of strings")
        for key in ("atmosphere", "suno_playlist_url"):
            _optional_string(self._data, key, f"workflow-state.json::planning.music.{key}")
        tempo = _optional_string(self._data, "tempo", "workflow-state.json::planning.music.tempo")
        if tempo is not None and tempo not in _MUSIC_TEMPOS:
            raise WorkflowStateError(f"unsupported workflow-state music tempo: {tempo}")


class PlanningState(_ObjectSection):
    """planning metadata の型付き view。"""

    @property
    def music(self) -> MusicPlanningState | None:
        value = self._data.get("music")
        if value is None:
            return None
        if not isinstance(value, dict):
            raise WorkflowStateError("workflow-state.json::planning.music must be an object")
        return MusicPlanningState(value)

    @property
    def activities(self) -> str | None:
        return _optional_string(self._data, "activities", "workflow-state.json::planning.activities")

    @property
    def playlists(self) -> list[str] | None:
        """このコレクションを追加するプレイリスト key の明示指定 (#4346).

        `None` は「未決定」、`[]` は「auto_add 以外へは意図的に追加しない」を意味する。
        両者を取り違えると preflight の未割り当て検出が無意味になるため、
        欠落と空配列は区別して返す。
        """
        if "playlists" not in self._data:
            return None
        value = self._data["playlists"]
        label = "workflow-state.json::planning.playlists"
        if not isinstance(value, list):
            raise WorkflowStateError(f"{label} must be an array of strings")
        keys: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item:
                raise WorkflowStateError(f"{label} must contain only non-empty strings")
            keys.append(item)
        return keys

    @property
    def scene_emoji(self) -> str | None:
        return _optional_string(self._data, "scene_emoji", "workflow-state.json::planning.scene_emoji")

    @property
    def publish_target_at(self) -> str | None:
        return _optional_string(self._data, "publish_target_at", "workflow-state.json::planning.publish_target_at")

    @property
    def final_title_en(self) -> str | None:
        return _optional_string(self._data, "final_title_en", "workflow-state.json::planning.final_title_en")

    @property
    def final_title(self) -> str | None:
        return _optional_string(self._data, "final_title", "workflow-state.json::planning.final_title")

    def set_known(self, key: PlanningKey, value: JSONValue) -> None:
        """CLI が公開する planning key を schema 検証して更新する。"""
        if key == "generated":
            if not isinstance(value, bool):
                raise WorkflowStateError("workflow-state.json::planning.generated must be a boolean")
        elif key == "music":
            if not isinstance(value, dict):
                raise WorkflowStateError("workflow-state.json::planning.music must be an object")
            music = MusicPlanningState(value)
            music.validate_known()
        elif key == "playlists":
            label = "workflow-state.json::planning.playlists"
            if not isinstance(value, list):
                raise WorkflowStateError(f"{label} must be an array of strings")
            if not all(isinstance(item, str) and item for item in value):
                raise WorkflowStateError(f"{label} must contain only non-empty strings")
        elif not isinstance(value, str):
            raise WorkflowStateError(f"workflow-state.json::planning.{key} must be a string")
        self._data[key] = deepcopy(value)


class PostUploadState(_ObjectSection):
    """公開後処理の型付き view。"""

    @property
    def shorts(self) -> list[dict[str, JSONValue]]:
        value = self._data.get("shorts")
        if value is None:
            return []
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise WorkflowStateError("workflow-state.json::post_upload.shorts must be an array of objects")
        return deepcopy(value)

    @shorts.setter
    def shorts(self, value: list[dict[str, JSONValue]]) -> None:
        if not all(isinstance(item, dict) for item in value):
            raise WorkflowStateError("workflow-state.json::post_upload.shorts must be an array of objects")
        for index, item in enumerate(value):
            short_num = item.get("short_num")
            if short_num is not None and (isinstance(short_num, bool) or not isinstance(short_num, int)):
                raise WorkflowStateError(
                    f"workflow-state.json::post_upload.shorts[{index}].short_num must be an integer or null"
                )
            for key in ("video_id", "uploaded_at", "publish_at", "resume_session_uri"):
                _optional_string(item, key, f"workflow-state.json::post_upload.shorts[{index}].{key}")
        self._data["shorts"] = deepcopy(value)


class UploadState(_ObjectSection):
    """YouTube upload state の型付き view。"""

    @property
    def video_id(self) -> str | None:
        return _optional_string(self._data, "video_id", "workflow-state.json::upload.video_id")

    @video_id.setter
    def video_id(self, value: str | None) -> None:
        self._data["video_id"] = value

    @property
    def video_url(self) -> str | None:
        return _optional_string(self._data, "video_url", "workflow-state.json::upload.video_url")

    @video_url.setter
    def video_url(self, value: str | None) -> None:
        self._data["video_url"] = value

    @property
    def publish_at(self) -> str | None:
        return _optional_string(self._data, "publish_at", "workflow-state.json::upload.publish_at")

    @publish_at.setter
    def publish_at(self, value: str | None) -> None:
        self._data["publish_at"] = value


class HandoffState(_ObjectSection):
    """境界引き渡しの完了marker参照と現在owner。"""

    @property
    def point(self) -> HandoffPoint | None:
        value = _optional_string(self._data, "point", "workflow-state.json::handoff.point")
        if value is None:
            return None
        if value != "suno_download":
            raise WorkflowStateError(f"unsupported workflow-state handoff point: {value}")
        return "suno_download"

    @property
    def owner(self) -> ExecutionOwner | None:
        value = _optional_string(self._data, "owner", "workflow-state.json::handoff.owner")
        if value is None:
            return None
        if value not in {"local", "cloud"}:
            raise WorkflowStateError(f"unsupported workflow-state handoff owner: {value}")
        return cast(ExecutionOwner, value)

    @property
    def manifest_key(self) -> str | None:
        value = _optional_string(self._data, "manifest_key", "workflow-state.json::handoff.manifest_key")
        if value is not None:
            _validate_manifest_key(value)
        return value

    @property
    def root_sha256(self) -> str | None:
        value = _optional_string(self._data, "root_sha256", "workflow-state.json::handoff.root_sha256")
        if value is not None:
            _validate_root_sha256(value)
        return value


class HumanTasksState(_ObjectSection):
    """API 非対応の人手作業について完了事実を保持する型付き view。"""

    @property
    def distrokid_submission_completed_at(self) -> str | None:
        value = self._data.get("distrokid_submission")
        if value is None:
            return None
        if not isinstance(value, dict):
            raise WorkflowStateError("workflow-state.json::human_tasks.distrokid_submission must be an object")
        completed_at = _optional_string(
            value,
            "completed_at",
            "workflow-state.json::human_tasks.distrokid_submission.completed_at",
        )
        if completed_at is not None:
            _validate_iso_datetime(
                completed_at,
                "workflow-state.json::human_tasks.distrokid_submission.completed_at",
            )
        return completed_at

    def record_distrokid_submission(self, completed_at: str) -> None:
        _validate_iso_datetime(
            completed_at,
            "workflow-state.json::human_tasks.distrokid_submission.completed_at",
        )
        existing = self.distrokid_submission_completed_at
        if existing is not None:
            return
        task = self._data.setdefault("distrokid_submission", {})
        assert isinstance(task, dict)
        task["completed_at"] = completed_at


class WorkflowState(MutableMapping[str, JSONValue]):
    """既知 section を型付きで扱い、未知キーも保持する document object。"""

    def __init__(self, data: Mapping[str, JSONValue]) -> None:
        self._data = deepcopy(dict(data))
        self._validate_object_sections()

    def __getitem__(self, key: str) -> JSONValue:
        return deepcopy(self._data[key])

    def __setitem__(self, key: str, value: JSONValue) -> None:
        if key in _KNOWN_OBJECT_SECTIONS and not isinstance(value, dict):
            raise WorkflowStateSectionTypeError(key)
        self._data[key] = deepcopy(value)

    def __delitem__(self, key: str) -> None:
        del self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def _validate_object_sections(self) -> None:
        for key in _KNOWN_OBJECT_SECTIONS & self._data.keys():
            if not isinstance(self._data[key], dict):
                raise WorkflowStateSectionTypeError(key)
        planning = self.planning
        if planning is not None:
            _music = planning.music
        handoff = self.handoff
        if handoff is not None:
            _point = handoff.point
            _owner = handoff.owner
            _manifest_key = handoff.manifest_key
            _root_sha256 = handoff.root_sha256
        human_tasks = self.human_tasks
        if human_tasks is not None:
            _distrokid_submission_completed_at = human_tasks.distrokid_submission_completed_at

    @property
    def phase(self) -> Phase | None:
        value = _optional_string(self._data, "phase", "workflow-state.json::phase")
        if value is None:
            return None
        if value not in _PHASES:
            raise WorkflowStateError(f"unsupported workflow-state phase: {value}")
        return cast(Phase, value)

    @property
    def updated_at(self) -> str | None:
        value = _optional_string(self._data, "updated_at", "workflow-state.json::updated_at")
        if value is not None:
            _validate_iso_datetime(value, "workflow-state.json::updated_at")
        return value

    @phase.setter
    def phase(self, value: Phase) -> None:
        if value not in _PHASES:
            raise WorkflowStateError(f"unsupported workflow-state phase: {value}")
        self._data["phase"] = value

    @property
    def stage(self) -> Stage | None:
        value = _optional_string(self._data, "stage", "workflow-state.json::stage")
        if value is None:
            return None
        if value not in _STAGES:
            raise WorkflowStateError(f"unsupported workflow-state stage: {value}")
        return cast(Stage, value)

    @stage.setter
    def stage(self, value: Stage) -> None:
        if value not in _STAGES:
            raise WorkflowStateError(f"unsupported workflow-state stage: {value}")
        self._data["stage"] = value

    @property
    def planning(self) -> PlanningState | None:
        value = self._data.get("planning")
        return PlanningState(value) if isinstance(value, dict) else None

    @property
    def assets(self) -> AssetsState | None:
        value = self._data.get("assets")
        return AssetsState(value) if isinstance(value, dict) else None

    @property
    def upload(self) -> UploadState | None:
        value = self._data.get("upload")
        return UploadState(value) if isinstance(value, dict) else None

    @property
    def post_upload(self) -> PostUploadState | None:
        value = self._data.get("post_upload")
        return PostUploadState(value) if isinstance(value, dict) else None

    @property
    def handoff(self) -> HandoffState | None:
        value = self._data.get("handoff")
        return HandoffState(value) if isinstance(value, dict) else None

    @property
    def human_tasks(self) -> HumanTasksState | None:
        value = self._data.get("human_tasks")
        return HumanTasksState(value) if isinstance(value, dict) else None

    @property
    def distrokid_submission_completed_at(self) -> str | None:
        human_tasks = self.human_tasks
        return human_tasks.distrokid_submission_completed_at if human_tasks is not None else None

    def touch(self) -> None:
        """`updated_at` を UTC・ミリ秒精度の正準 RFC 3339 形式で刻印する。"""
        self._data["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def set_phase(self, phase: Phase) -> None:
        """phase を検証して更新し、更新時刻を刻印する。"""
        self.phase = phase
        self.touch()

    def set_stage(self, stage: Stage) -> None:
        """stage を検証して更新し、更新時刻を刻印する。"""
        self.stage = stage
        self.touch()

    def set_asset(self, key: AssetKey, value: JSONValue) -> None:
        """asset section を必要に応じて生成し、既知 key を検証して更新する。"""
        assets = self._data.setdefault("assets", {})
        assert isinstance(assets, dict)
        AssetsState(assets).set_known(key, value)
        self.touch()

    def set_planning(self, key: PlanningKey, value: JSONValue) -> None:
        """planning section を必要に応じて生成し、既知 key を検証して更新する。"""
        self.set_planning_known(key, value)
        self.touch()

    def record_upload(
        self,
        *,
        video_id: str,
        video_url: str | None | _UnsetType = _UNSET,
        publish_at: str | None | _UnsetType = _UNSET,
    ) -> None:
        """YouTube upload の既知値を記録し、省略された任意値は保持する。"""
        if not isinstance(video_id, str):
            raise WorkflowStateError("workflow-state.json::upload.video_id must be a string")
        upload = self._data.setdefault("upload", {})
        assert isinstance(upload, dict)
        typed_upload = UploadState(upload)
        typed_upload.video_id = video_id
        if video_url is not _UNSET:
            if video_url is not None and not isinstance(video_url, str):
                raise WorkflowStateError("workflow-state.json::upload.video_url must be a string or null")
            typed_upload.video_url = cast(str | None, video_url)
        if publish_at is not _UNSET:
            if publish_at is not None and not isinstance(publish_at, str):
                raise WorkflowStateError("workflow-state.json::upload.publish_at must be a string or null")
            typed_upload.publish_at = cast(str | None, publish_at)
        self.touch()

    def record_master_video(self, path: str | None) -> None:
        """master video asset を検証して記録する。"""
        self.set_asset("master_video", path)

    def record_master_audio(self, path: str | None) -> None:
        """master audio asset と mastered phase を一度の遷移で記録する。"""
        assets = self._data.setdefault("assets", {})
        assert isinstance(assets, dict)
        AssetsState(assets).set_known("master_audio", path)
        self.phase = "mastered"
        self.touch()

    def record_collection_plan(self, *, final_title: str, target_persona: str) -> None:
        """承認済み collection plan の既知 planning 値をまとめて記録する。"""
        planning = self._data.setdefault("planning", {})
        assert isinstance(planning, dict)
        typed_planning = PlanningState(planning)
        typed_planning.set_known("generated", True)
        typed_planning.set_known("final_title", final_title)
        typed_planning.set_known("target_persona", target_persona)
        self.touch()

    @property
    def music_prompt_approved_digest(self) -> str | None:
        return _optional_string(
            self._data, "music_prompt_approved_digest", "workflow-state.json::music_prompt_approved_digest"
        )

    def record_music_prompt_approval(self, artifact_digest: str) -> None:
        """承認した prompt の正本 digest と完了 flag を一緒に記録する。"""
        self.set_asset("music_prompts", True)
        self._data["music_prompt_approved_digest"] = artifact_digest

    def record_thumbnail_review_selection(self, selection: Mapping[str, JSONValue]) -> None:
        """承認済み thumbnail review selection を記録する。"""
        self._data["thumbnail_review_selection"] = deepcopy(dict(selection))
        self.touch()

    def record_short_upload(self, entry: Mapping[str, JSONValue]) -> None:
        """short_num 単位で公開記録を upsert し、更新時刻を刻印する。"""
        short_num = entry.get("short_num")
        if short_num is not None and (isinstance(short_num, bool) or not isinstance(short_num, int)):
            raise WorkflowStateError("workflow-state.json::post_upload.shorts[].short_num must be an integer or null")
        post_upload = self._data.setdefault("post_upload", {})
        assert isinstance(post_upload, dict)
        typed_post_upload = PostUploadState(post_upload)
        shorts = typed_post_upload.shorts
        replacement = deepcopy(dict(entry))
        for index, existing in enumerate(shorts):
            if existing.get("short_num") == short_num:
                shorts[index] = replacement
                break
        else:
            shorts.append(replacement)
        typed_post_upload.shorts = shorts
        self.touch()

    def record_distrokid_submission(self, completed_at: str) -> None:
        """DistroKid提出の初回完了時刻を保持し、再実行では上書きしない。"""
        human_tasks = self._data.setdefault("human_tasks", {})
        assert isinstance(human_tasks, dict)
        HumanTasksState(human_tasks).record_distrokid_submission(completed_at)

    def record_cloud_handoff(
        self,
        *,
        point: HandoffPoint,
        manifest_key: str,
        root_sha256: str,
    ) -> None:
        """Suno DL完了markerを記録し、工程所有権をcloudへ一方向遷移する。"""

        _validate_handoff_reference(point, manifest_key, root_sha256)
        existing = self.handoff
        if self.phase == "cloud_owned":
            if (
                existing is not None
                and existing.point == point
                and existing.owner == "cloud"
                and existing.manifest_key == manifest_key
                and existing.root_sha256 == root_sha256
            ):
                return
            raise WorkflowStateError("workflow-state handoff already records a different manifest")
        if self.phase != "prepared":
            raise WorkflowStateError("workflow-state handoff requires phase prepared")
        if self.music_engine != "suno":
            raise WorkflowStateError("workflow-state suno_download handoff requires music engine suno")
        assets = self.assets
        if assets is None or assets.music_downloaded is not True:
            raise WorkflowStateError("workflow-state handoff requires assets.music_downloaded true")
        if existing is not None:
            known = (existing.point, existing.owner, existing.manifest_key, existing.root_sha256)
            if any(value is not None for value in known):
                raise WorkflowStateError("workflow-state handoff already records a different manifest")

        handoff = self._data.setdefault("handoff", {})
        assert isinstance(handoff, dict)
        handoff.update(
            {
                "point": point,
                "owner": "cloud",
                "manifest_key": manifest_key,
                "root_sha256": root_sha256,
            }
        )
        self.phase = "cloud_owned"

    def set_thumbnail_approved(self, approved: bool) -> None:
        if not isinstance(approved, bool):
            raise WorkflowStateError("workflow-state.json::assets.thumbnail must be a boolean")
        assets = self._data.setdefault("assets", {})
        assert isinstance(assets, dict)
        AssetsState(assets).thumbnail = approved

        legacy = self._data.get("thumbnail")
        if isinstance(legacy, dict):
            legacy.pop("approved", None)
            if not legacy:
                del self._data["thumbnail"]

    def set_description_generated(self, generated: bool) -> None:
        if not isinstance(generated, bool):
            raise WorkflowStateError("workflow-state.json::assets.description must be a boolean")
        assets = self._data.setdefault("assets", {})
        assert isinstance(assets, dict)
        AssetsState(assets).description = generated

        legacy = self._data.get("description")
        if isinstance(legacy, dict):
            legacy.pop("generated", None)
            if not legacy:
                del self._data["description"]

    def set_planning_known(self, key: PlanningKey, value: JSONValue) -> None:
        planning = self._data.setdefault("planning", {})
        assert isinstance(planning, dict)
        PlanningState(planning).set_known(key, value)
        if key == "music":
            self._data.pop("music_engine", None)

    @property
    def theme(self) -> str | None:
        return _optional_string(self._data, "theme", "workflow-state.json::theme")

    @property
    def created_at(self) -> str | None:
        return _optional_string(self._data, "created_at", "workflow-state.json::created_at")

    @property
    def collection_name(self) -> str | None:
        return _optional_string(self._data, "collection_name", "workflow-state.json::collection_name")

    @property
    def title_activity(self) -> str | None:
        return _optional_string(self._data, "title_activity", "workflow-state.json::title_activity")

    @property
    def track_count(self) -> int | None:
        value = self._data.get("track_count")
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise WorkflowStateError("workflow-state.json::track_count must be an integer or null")
        return value

    @property
    def track_display_names(self) -> dict[str, JSONValue] | None:
        value = self._data.get("track_display_names")
        if value is None:
            return None
        if not isinstance(value, dict):
            raise WorkflowStateError("workflow-state.json::track_display_names must be an object")
        return deepcopy(value)

    @property
    def scene_phrases(self) -> dict[str, JSONValue] | None:
        value = self._data.get("scene_phrases")
        return deepcopy(value) if isinstance(value, dict) else None

    @property
    def allow_volume_patterns(self) -> bool:
        return self._section_bool("title_template_check", "allow_volume_patterns") is True

    @property
    def thumbnail_approved(self) -> bool:
        legacy = self._section_bool("thumbnail", "approved")
        assets = self.assets
        current = assets.thumbnail if assets is not None else None
        return legacy is True or current is True

    @property
    def description_generated(self) -> bool:
        legacy = self._section_bool("description", "generated")
        assets = self.assets
        current = assets.description if assets is not None else None
        return legacy is True or current is True

    @property
    def music_engine(self) -> MusicEngine | None:
        top_level = _optional_string(self._data, "music_engine", "workflow-state.json::music_engine")
        planning = self.planning
        music = planning.music if planning is not None else None
        nested = music.engine if music is not None else None
        if top_level is not None and top_level not in _MUSIC_ENGINES:
            raise WorkflowStateError(f"unsupported workflow-state music engine: {top_level}")
        if top_level is not None and nested is not None and top_level != nested:
            raise WorkflowStateError(
                f"workflow-state music engine mismatch: top-level={top_level}, planning.music={nested}"
            )
        return nested or cast(MusicEngine | None, top_level)

    def _section_bool(self, section: str, key: str) -> bool | None:
        value = self._data.get(section)
        if not isinstance(value, dict):
            return None
        return _optional_bool(value, key, f"workflow-state.json::{section}.{key}")

    def to_dict(self) -> dict[str, JSONValue]:
        """永続化用に document の独立したコピーを返す。"""
        return deepcopy(self._data)


def _validate_handoff_reference(point: str, manifest_key: str, root_sha256: str) -> None:
    if point != "suno_download":
        raise WorkflowStateError(f"unsupported workflow-state handoff point: {point}")
    _validate_manifest_key(manifest_key)
    _validate_root_sha256(root_sha256)


def _validate_manifest_key(manifest_key: str) -> None:
    key = PurePosixPath(manifest_key)
    if (
        not manifest_key
        or manifest_key.startswith("/")
        or "\\" in manifest_key
        or any(part in {"", ".", ".."} for part in key.parts)
        or len(key.parts) != 4
        or key.name != "manifest.json"
    ):
        raise WorkflowStateError("workflow-state handoff.manifest_key must be a relative manifest.json key")
    try:
        normalized = MediaKey(key.parts[0], key.parts[1], key.parts[2], key.parts[3]).as_posix()
    except ValidationError as exc:
        raise WorkflowStateError("workflow-state handoff.manifest_key must use safe MediaKey segments") from exc
    if normalized != manifest_key:
        raise WorkflowStateError("workflow-state handoff.manifest_key must be a canonical MediaKey")


def _validate_root_sha256(root_sha256: str) -> None:
    if len(root_sha256) != 64 or any(character not in "0123456789abcdef" for character in root_sha256):
        raise WorkflowStateError("workflow-state handoff.root_sha256 must be 64 lowercase hex characters")


def _validate_iso_datetime(value: str, label: str) -> None:
    if not isinstance(value, str):
        raise WorkflowStateError(f"{label} must be a string or null")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkflowStateError(f"{label} must be an ISO 8601 datetime") from exc
    if parsed.tzinfo is None:
        raise WorkflowStateError(f"{label} must include a timezone")


def _read_payload(path: Path) -> dict[str, JSONValue]:
    if path.is_symlink():
        raise WorkflowStateError(f"workflow-state.json must not be a symlink: {path}")
    if not path.is_file():
        raise WorkflowStateError(f"workflow-state.json is not a regular file: {path}")
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WorkflowStateError(f"workflow-state.json could not be read: {path}") from exc
    if not isinstance(payload, dict):
        raise WorkflowStateError(f"workflow-state.json root must be an object: {path}")
    return cast(dict[str, JSONValue], payload)


def read(path: Path) -> WorkflowState:
    """通常ファイルの workflow-state.json を厳密に読み込む。"""
    return WorkflowState(_read_payload(path))


def read_or_none(path: Path) -> WorkflowState | None:
    """ファイル不在だけを None とし、破損や symlink は拒否する。"""
    if path.is_symlink():
        raise WorkflowStateError(f"workflow-state.json must not be a symlink: {path}")
    if not path.exists():
        return None
    return read(path)


def _write_atomically(path: Path, state: WorkflowState) -> None:
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=".workflow-state.", suffix=".tmp")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(state.to_dict(), stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_symlink():
            raise WorkflowStateError(f"workflow-state.json must not be a symlink: {path}")
        os.replace(temporary, path)
    except WorkflowStateError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError as cleanup_exc:
            raise WorkflowStateError(
                f"workflow-state.json update failed and temporary file could not be removed: {path}: "
                f"{exc}; {cleanup_exc}"
            ) from cleanup_exc
        raise
    except (OSError, TypeError, ValueError) as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError as cleanup_exc:
            raise WorkflowStateError(
                f"workflow-state.json could not be written and temporary file could not be removed: {path}: "
                f"{exc}; {cleanup_exc}"
            ) from cleanup_exc
        raise WorkflowStateError(f"workflow-state.json could not be written: {path}") from exc


def update(path: Path, updater: WorkflowStateUpdater) -> WorkflowState:
    """lock 内で read-modify-write し、更新後の document を返す。"""
    with file_lock(path):
        current = read_or_none(path)
        state = current if current is not None else WorkflowState({})
        replacement = updater(state)
        if replacement is not None:
            state = replacement
        _write_atomically(path, state)
        return state
