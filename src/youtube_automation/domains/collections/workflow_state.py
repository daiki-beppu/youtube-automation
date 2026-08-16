"""workflow-state.json の document object と安全な永続化境界。"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Iterator, Mapping, MutableMapping
from copy import deepcopy
from pathlib import Path
from typing import Literal, TypedDict, cast

from youtube_automation.core.errors import WorkflowStateError
from youtube_automation.infrastructure.filesystem import JSONValue, file_lock

Phase = Literal["planning", "prepared", "mastered", "publishing", "complete"]
Stage = Literal["planning", "live"]
MusicEngine = Literal["suno", "lyria"]
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
PlanningKey = Literal["generated", "final_title", "target_persona", "publish_target_at", "music"]


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


class AssetsDocument(TypedDict, total=False):
    thumbnail: bool | str
    loop_video: bool | Literal["failed"]
    music_prompts: bool
    music_downloaded: bool
    raw_master: str | None
    master_audio: str | None
    master_video: str | None
    description: bool


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


class ThumbnailDocument(TypedDict, total=False):
    approved: bool


class DescriptionDocument(TypedDict, total=False):
    generated: bool


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
    music_engine: MusicEngine
    planning: PlanningDocument
    scene_phrases: dict[str, str]
    title_template_check: TitleTemplateCheckDocument
    assets: AssetsDocument
    music_pair_selection: MusicPairSelectionDocument
    upload: UploadDocument
    post_upload: PostUploadDocument
    track_display_names: dict[str, str]
    title_activity: str
    thumbnail_auto_selection: ThumbnailAutoSelectionDocument
    thumbnail: ThumbnailDocument
    description: DescriptionDocument


_PHASES = frozenset({"planning", "prepared", "mastered", "publishing", "complete"})
_STAGES = frozenset({"planning", "live"})
_MUSIC_ENGINES = frozenset({"suno", "lyria"})
_MUSIC_TEMPOS = frozenset({"very slow", "slow", "gentle", "moderate", "lively"})
_KNOWN_OBJECT_SECTIONS = frozenset(
    {
        "assets",
        "description",
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
    def thumbnail(self) -> bool | str | None:
        value = self._data.get("thumbnail")
        if value is None or isinstance(value, bool | str):
            return value
        raise WorkflowStateError("workflow-state.json::assets.thumbnail must be a boolean, string, or null")

    @thumbnail.setter
    def thumbnail(self, value: bool | str | None) -> None:
        self._data["thumbnail"] = value

    @property
    def description(self) -> bool | None:
        return _optional_bool(self._data, "description", "workflow-state.json::assets.description")

    @description.setter
    def description(self, value: bool) -> None:
        self._data["description"] = value

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

    @property
    def video(self) -> str | None:
        return _optional_string(self._data, "video", "workflow-state.json::assets.video")

    def set_known(self, key: AssetKey, value: JSONValue) -> None:
        """CLI が公開する asset key を schema 検証して更新する。"""
        if key == "thumbnail":
            if value is not None and not isinstance(value, bool | str):
                raise WorkflowStateError("workflow-state.json::assets.thumbnail must be a boolean, string, or null")
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


class WorkflowState(MutableMapping[str, JSONValue]):
    """既知 section を型付きで扱い、未知キーも保持する document object。"""

    def __init__(self, data: Mapping[str, JSONValue]) -> None:
        self._data = deepcopy(dict(data))
        self._validate_object_sections()

    def __getitem__(self, key: str) -> JSONValue:
        return deepcopy(self._data[key])

    def __setitem__(self, key: str, value: JSONValue) -> None:
        if key in _KNOWN_OBJECT_SECTIONS and not isinstance(value, dict):
            raise WorkflowStateError(f"workflow-state.json::{key} must be an object")
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
                raise WorkflowStateError(f"workflow-state.json::{key} must be an object")
        planning = self.planning
        if planning is not None:
            _music = planning.music

    @property
    def phase(self) -> Phase | None:
        value = _optional_string(self._data, "phase", "workflow-state.json::phase")
        if value is None:
            return None
        if value not in _PHASES:
            raise WorkflowStateError(f"unsupported workflow-state phase: {value}")
        return cast(Phase, value)

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

    def set_thumbnail_approved(self, approved: bool) -> None:
        section = self._data.setdefault("thumbnail", {})
        assert isinstance(section, dict)
        section["approved"] = approved

    def set_description_generated(self, generated: bool) -> None:
        section = self._data.setdefault("description", {})
        assert isinstance(section, dict)
        section["generated"] = generated

    @property
    def theme(self) -> str | None:
        return _optional_string(self._data, "theme", "workflow-state.json::theme")

    @property
    def created_at(self) -> str | None:
        return _optional_string(self._data, "created_at", "workflow-state.json::created_at")

    @property
    def video_id(self) -> str | None:
        return _optional_string(self._data, "video_id", "workflow-state.json::video_id")

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
