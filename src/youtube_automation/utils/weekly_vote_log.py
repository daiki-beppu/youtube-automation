"""``data/community/weekly-vote-log.json`` の loader / validator / append utility。

YouTube Studio の Sunday Vote 結果を ``yt-vote-log append`` で
週次で記録するログファイルを扱う。``/collection-ideate`` の theme weight 計算では
直近 N 週の ``top_axis`` を hook 経由で取り込み、

- 連続 2 週以上 1 位の軸を **強制採用** (theme weight を最大化)
- それ以外の軸は **直近 N 週の重みづけ平均** (新しい週ほど重い) で加点

する。

ファイルレイアウト::

    data/community/weekly-vote-log.json
    {
      "schema_version": 1,
      "entries": [
        {
          "week_start": "2026-05-04",   # ISO 8601 YYYY-MM-DD (日曜日想定だが強制せず)
          "axes": [                       # 提示した N-1 軸（順不同）
            {"key": "rain_window", "label": "Rain Window", "votes": 124},
            {"key": "midnight_drive", "label": "Midnight Drive", "votes": 98}
          ],
          "top_axis": "rain_window",     # axes の中で votes 最大の key
          "total_votes": 222,             # axes.votes の合計
          "notes": ""                     # 任意フリーテキスト
        }
      ]
    }

schema は ``schemas/weekly_vote_log.schema.json`` を参照。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from importlib import resources
from pathlib import Path
from typing import Any, Iterable

from youtube_automation.infrastructure.errors import ConfigError, ValidationError

logger = logging.getLogger(__name__)

WEEKLY_VOTE_LOG_SCHEMA_VERSION = 1
DEFAULT_VOTE_LOG_PATH = Path("data/community/weekly-vote-log.json")


@dataclass(frozen=True)
class AxisVote:
    """1 軸の投票結果."""

    key: str
    label: str
    votes: int

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "votes": self.votes}


@dataclass(frozen=True)
class WeeklyVoteEntry:
    """1 週分の投票結果."""

    week_start: str
    axes: tuple[AxisVote, ...]
    top_axis: str
    total_votes: int
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "week_start": self.week_start,
            "axes": [axis.to_dict() for axis in self.axes],
            "top_axis": self.top_axis,
            "total_votes": self.total_votes,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class WeeklyVoteLog:
    """週次投票ログ全体 (schema_version + entries)."""

    schema_version: int = WEEKLY_VOTE_LOG_SCHEMA_VERSION
    entries: tuple[WeeklyVoteEntry, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "entries": [entry.to_dict() for entry in self.entries],
        }

    def recent(self, n: int) -> tuple[WeeklyVoteEntry, ...]:
        """``week_start`` の降順で直近 N 件を返す."""
        if n <= 0:
            return ()
        sorted_entries = sorted(self.entries, key=lambda e: e.week_start, reverse=True)
        return tuple(sorted_entries[:n])


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_iso_date(value: str, *, context: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{context}: ISO 8601 (YYYY-MM-DD) 形式の文字列を期待 (got {type(value).__name__})")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"{context}: ISO 8601 (YYYY-MM-DD) として解釈不能: {value}") from exc
    return value


def _validate_axis(payload: Any, *, context: str) -> AxisVote:
    if not isinstance(payload, dict):
        raise ValidationError(f"{context}: dict を期待 (got {type(payload).__name__})")
    for key in ("key", "label", "votes"):
        if key not in payload:
            raise ValidationError(f"{context}: 必須キー '{key}' が欠落")
    key = payload["key"]
    label = payload["label"]
    votes = payload["votes"]
    if not isinstance(key, str) or not key:
        raise ValidationError(f"{context}.key: 非空の文字列を期待")
    if not isinstance(label, str):
        raise ValidationError(f"{context}.label: 文字列を期待")
    if not isinstance(votes, int) or isinstance(votes, bool):
        raise ValidationError(f"{context}.votes: 整数を期待")
    if votes < 0:
        raise ValidationError(f"{context}.votes: 0 以上を期待 (got {votes})")
    return AxisVote(key=key, label=label, votes=votes)


def _validate_entry(payload: Any, *, context: str) -> WeeklyVoteEntry:
    if not isinstance(payload, dict):
        raise ValidationError(f"{context}: dict を期待 (got {type(payload).__name__})")
    for key in ("week_start", "axes", "top_axis"):
        if key not in payload:
            raise ValidationError(f"{context}: 必須キー '{key}' が欠落")

    week_start = _validate_iso_date(payload["week_start"], context=f"{context}.week_start")

    axes_payload = payload["axes"]
    if not isinstance(axes_payload, list) or not axes_payload:
        raise ValidationError(f"{context}.axes: 非空の list を期待")
    axes = tuple(_validate_axis(axis, context=f"{context}.axes[{idx}]") for idx, axis in enumerate(axes_payload))

    keys = [axis.key for axis in axes]
    if len(set(keys)) != len(keys):
        raise ValidationError(f"{context}.axes: 重複した key が存在 ({keys})")

    top_axis = payload["top_axis"]
    if not isinstance(top_axis, str) or not top_axis:
        raise ValidationError(f"{context}.top_axis: 非空の文字列を期待")
    if top_axis not in keys:
        raise ValidationError(f"{context}.top_axis: axes 内に存在しない key ({top_axis})")

    total_votes = payload.get("total_votes")
    expected_total = sum(axis.votes for axis in axes)
    if total_votes is None:
        total_votes = expected_total
    else:
        if not isinstance(total_votes, int) or isinstance(total_votes, bool):
            raise ValidationError(f"{context}.total_votes: 整数を期待")
        if total_votes != expected_total:
            raise ValidationError(
                f"{context}.total_votes: axes.votes の合計と不一致 (declared={total_votes}, computed={expected_total})"
            )

    notes = payload.get("notes", "")
    if not isinstance(notes, str):
        raise ValidationError(f"{context}.notes: 文字列を期待")

    return WeeklyVoteEntry(
        week_start=week_start,
        axes=axes,
        top_axis=top_axis,
        total_votes=total_votes,
        notes=notes,
    )


def validate_weekly_vote_log(payload: Any) -> WeeklyVoteLog:
    """``payload`` (dict) を ``WeeklyVoteLog`` へ変換しつつバリデーションする."""
    if not isinstance(payload, dict):
        raise ValidationError(f"weekly-vote-log: トップは dict を期待 (got {type(payload).__name__})")

    schema_version = payload.get("schema_version", WEEKLY_VOTE_LOG_SCHEMA_VERSION)
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise ValidationError("weekly-vote-log.schema_version: 整数を期待")
    if schema_version != WEEKLY_VOTE_LOG_SCHEMA_VERSION:
        raise ValidationError(
            f"weekly-vote-log.schema_version: 未知のバージョン {schema_version} "
            f"(expected {WEEKLY_VOTE_LOG_SCHEMA_VERSION})"
        )

    entries_payload = payload.get("entries", [])
    if not isinstance(entries_payload, list):
        raise ValidationError("weekly-vote-log.entries: list を期待")

    entries = tuple(
        _validate_entry(entry, context=f"weekly-vote-log.entries[{idx}]") for idx, entry in enumerate(entries_payload)
    )

    # week_start 重複チェック
    week_starts = [entry.week_start for entry in entries]
    if len(set(week_starts)) != len(week_starts):
        raise ValidationError(f"weekly-vote-log.entries: 重複した week_start が存在 ({week_starts})")

    return WeeklyVoteLog(schema_version=schema_version, entries=entries)


# ---------------------------------------------------------------------------
# Loader / writer
# ---------------------------------------------------------------------------


def _resolve_path(channel_dir: Path, path: Path | str | None = None) -> Path:
    if path is None:
        return channel_dir / DEFAULT_VOTE_LOG_PATH
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return channel_dir / candidate


def load_weekly_vote_log(
    *,
    channel_dir: Path,
    path: Path | str | None = None,
    missing_ok: bool = True,
) -> WeeklyVoteLog:
    """``data/community/weekly-vote-log.json`` を読み込み ``WeeklyVoteLog`` を返す.

    Args:
        channel_dir: チャンネルディレクトリ (相対パス解決の base)
        path: ``channel_dir`` からの相対パス or 絶対パス。未指定なら
            ``data/community/weekly-vote-log.json``
        missing_ok: True (default) なら未存在時に空の ``WeeklyVoteLog`` を返す。
            False のときは ``ConfigError``

    Raises:
        ConfigError: missing_ok=False かつ未存在、または JSON パース失敗時
        ValidationError: schema 違反
    """
    target = _resolve_path(channel_dir, path)
    if not target.exists():
        if missing_ok:
            return WeeklyVoteLog()
        raise ConfigError(f"weekly-vote-log が見つかりません: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"weekly-vote-log の JSON パースに失敗: {target} ({exc})") from exc
    return validate_weekly_vote_log(payload)


def save_weekly_vote_log(
    log: WeeklyVoteLog,
    *,
    channel_dir: Path,
    path: Path | str | None = None,
) -> Path:
    """``WeeklyVoteLog`` を JSON として書き出す (親ディレクトリは自動作成)."""
    target = _resolve_path(channel_dir, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(log.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def append_weekly_vote_entry(
    *,
    channel_dir: Path,
    week_start: str | date,
    axes: Iterable[AxisVote | dict[str, Any]],
    notes: str = "",
    path: Path | str | None = None,
    replace: bool = False,
) -> WeeklyVoteLog:
    """直近 1 週分の投票結果を append し、保存する.

    Args:
        channel_dir: チャンネルディレクトリ
        week_start: 投票週開始日 (ISO 8601 文字列 or ``date``)
        axes: 軸ごとの ``AxisVote`` または同等の dict のリスト
        notes: 任意フリーテキスト
        path: log ファイルパス上書き
        replace: 同 ``week_start`` が既存なら True で置換、False で ``ValidationError``

    Returns:
        書き込み後の ``WeeklyVoteLog``
    """
    if isinstance(week_start, date):
        week_start_str = week_start.isoformat()
    else:
        week_start_str = _validate_iso_date(week_start, context="append.week_start")

    axes_objs: list[AxisVote] = []
    for idx, axis in enumerate(axes):
        if isinstance(axis, AxisVote):
            axes_objs.append(axis)
        else:
            axes_objs.append(_validate_axis(axis, context=f"append.axes[{idx}]"))
    if not axes_objs:
        raise ValidationError("append.axes: 1 件以上の軸を指定してください")

    # top_axis を votes 最大の key として計算 (同票時は最初の出現順)
    top_axis = max(axes_objs, key=lambda a: a.votes).key
    total_votes = sum(axis.votes for axis in axes_objs)

    new_entry = WeeklyVoteEntry(
        week_start=week_start_str,
        axes=tuple(axes_objs),
        top_axis=top_axis,
        total_votes=total_votes,
        notes=notes,
    )

    existing = load_weekly_vote_log(channel_dir=channel_dir, path=path)
    existing_map = {entry.week_start: entry for entry in existing.entries}
    if week_start_str in existing_map and not replace:
        raise ValidationError(
            f"append.week_start: 既存エントリと衝突 ({week_start_str}). "
            "上書きしたい場合は replace=True を指定してください"
        )
    existing_map[week_start_str] = new_entry

    merged_entries = tuple(sorted(existing_map.values(), key=lambda e: e.week_start))
    updated_log = WeeklyVoteLog(
        schema_version=existing.schema_version,
        entries=merged_entries,
    )
    save_weekly_vote_log(updated_log, channel_dir=channel_dir, path=path)
    return updated_log


# ---------------------------------------------------------------------------
# Hook for /collection-ideate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VoteLogHookResult:
    """``/collection-ideate`` 向け hook の出力.

    Attributes:
        weights: 軸 key → weight (重みづけ平均から得た 0.0 以上の浮動小数点)
        forced_axis: 連続 2 週以上 1 位だった軸の key (なければ ``None``)
        forced_streak: ``forced_axis`` の連続 1 位週数 (なければ 0)
        considered_weeks: hook 計算に使った週数
    """

    weights: dict[str, float]
    forced_axis: str | None
    forced_streak: int
    considered_weeks: int


def compute_vote_log_weights(
    log: WeeklyVoteLog,
    *,
    recent_weeks: int = 4,
    forced_streak_threshold: int = 2,
    decay: float = 0.7,
) -> VoteLogHookResult:
    """直近 N 週の ``top_axis`` から軸ごとの weight と forced_axis を算出する.

    重みづけ平均の式::

        weight[key] = Σ_{i=0..N-1} decay^i × (1 if entry[i].top_axis == key else 0)

    where ``entry[0]`` is the most recent entry. すなわち新しい週ほど重い。

    forced_axis は **最新から ``forced_streak_threshold`` 週連続で同じ ``top_axis``** だった軸。
    満たさなければ ``None``。

    Args:
        log: ``WeeklyVoteLog``
        recent_weeks: 計算対象の週数 (>=1)
        forced_streak_threshold: 強制採用判定の連続週数 (>=2)
        decay: 1 週古くなるごとに weight に掛ける減衰率 (0 < decay <= 1)

    Returns:
        ``VoteLogHookResult``
    """
    if recent_weeks <= 0:
        raise ValidationError("compute_vote_log_weights: recent_weeks は 1 以上")
    if forced_streak_threshold < 2:
        raise ValidationError("compute_vote_log_weights: forced_streak_threshold は 2 以上")
    if not (0.0 < decay <= 1.0):
        raise ValidationError("compute_vote_log_weights: decay は (0, 1] の範囲")

    recent = log.recent(recent_weeks)
    weights: dict[str, float] = {}
    for idx, entry in enumerate(recent):
        weight = decay**idx
        weights[entry.top_axis] = weights.get(entry.top_axis, 0.0) + weight

    forced_axis: str | None = None
    forced_streak = 0
    if len(recent) >= forced_streak_threshold:
        head_axis = recent[0].top_axis
        streak = 1
        for entry in recent[1:]:
            if entry.top_axis == head_axis:
                streak += 1
            else:
                break
        if streak >= forced_streak_threshold:
            forced_axis = head_axis
            forced_streak = streak

    return VoteLogHookResult(
        weights=weights,
        forced_axis=forced_axis,
        forced_streak=forced_streak,
        considered_weeks=len(recent),
    )


# ---------------------------------------------------------------------------
# Deprecation helper
# ---------------------------------------------------------------------------


_POLL_DEPRECATION_MESSAGE = (
    "community-draft type='poll' は DEPRECATED です。"
    "新規投稿は /community-draft --batch、既存 poll 結果の記録は "
    "yt-vote-log append を使用してください."
)


def warn_poll_deprecated() -> None:
    """旧 ``type=poll`` 利用時に呼び出すと warning ログを残す."""
    logger.warning(_POLL_DEPRECATION_MESSAGE)


def poll_deprecation_message() -> str:
    """テスト・CLI 表示用のメッセージ getter."""
    return _POLL_DEPRECATION_MESSAGE


def parse_iso_date(value: str) -> date:
    """``YYYY-MM-DD`` を ``date`` へ。CLI からの呼び出し用."""
    return date.fromisoformat(_validate_iso_date(value, context="parse_iso_date"))


def parse_isoformat_datetime(value: str) -> datetime:
    """ISO 8601 datetime を ``datetime`` へ。CLI からの汎用ヘルパ."""
    return datetime.fromisoformat(value)


def load_weekly_vote_log_schema() -> dict[str, Any]:
    """同梱の JSON Schema (``schemas/weekly_vote_log.schema.json``) を dict で返す.

    呼び出し側で ``jsonschema`` 等の外部バリデータと組み合わせる用途を想定する。
    本モジュールの ``validate_weekly_vote_log`` は手書きバリデータだが、
    schema は同梱して下流ツール (LSP / 編集補助 / 外部監査) が参照できる。
    """
    schema_file = resources.files("youtube_automation.utils.schemas").joinpath("weekly_vote_log.schema.json")
    with resources.as_file(schema_file) as path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
