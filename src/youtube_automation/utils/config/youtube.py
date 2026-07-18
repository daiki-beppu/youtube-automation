"""YouTube API 設定・music_engine・content_model・overlays の責務別 dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class YoutubeApi:
    """`youtube` セクション（API 基本設定）.

    `contains_synthetic_media`: アップロード時に申告する AI 開示フラグ
        (`status.containsSyntheticMedia`)。未設定時は現行の振る舞いに合わせ `True`。
    `self_declared_made_for_kids`: 子供向け申告 (`status.selfDeclaredMadeForKids`)。
        未設定時は現行の振る舞いに合わせ `False`。
    """

    category_id: str
    privacy_status: str
    language: str
    contains_synthetic_media: bool = True
    self_declared_made_for_kids: bool = False
    default_publish_time: str | None = None
    default_publish_timezone: str = "Asia/Tokyo"


@dataclass(frozen=True)
class ContentModel:
    """`content_model` セクション（optional）.

    `type`: `"release"` / `"collection"` など。
    `languages`: 配信対象言語。未指定時は loader が `[api.language]` を注入する。
    """

    type: str = "release"
    languages: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OverlayAudioVisualizerRing:
    """円形 visualizer 固有の幾何設定（optional, #1684）."""

    inner_r: int = 120
    length: int = 160
    arc_deg: tuple[float, float] = (0.0, 360.0)


@dataclass(frozen=True)
class AudioVisualizerFill:
    """Visualizer の配色。未指定時は従来の ``colors`` 経路を使う。"""

    type: str = "solid"
    color: str = "white"
    top: str = "0xA9CBF0"
    bottom: str = "0x3A5696"


@dataclass(frozen=True)
class AudioVisualizerRounding:
    """Alpha mask に適用する角丸化パラメータ。"""

    blur: float = 2.3
    contrast: float = 3.2


@dataclass(frozen=True)
class AudioVisualizerGlow:
    """コアの下に合成する glow。``enabled`` で個別に無効化できる。"""

    enabled: bool = True
    sigma: float = 12.0
    opacity: float = 0.45


@dataclass(frozen=True)
class OverlayAudioVisualizer:
    """`overlays.audio_visualizer` セクション（optional, #511）.

    `style` は既存互換の `bar` を既定とし、`mirror-mountain` / `ring` /
    `ring-line` / `heart` を選択できる。`enabled: false` または overlays 自体が
    無効化されているときは無視される。

    フィールドはすべて FFmpeg フィルタの引数にそのまま流し込めるよう文字列で保持する。
    `position` は `overlay` フィルタの `x:y` 式（例 `(W-w)/2:H-h-40`）。
    `glow_*` は `gblur` glow パスのパラメータ。
    """

    enabled: bool = False
    style: str = "bar"
    bars: int = 16
    mode: str = "bar"
    size: str = "1280x180"
    rate: str = "24"
    fscale: str = "log"
    win_size: int = 2048
    win_func: str = "hann"
    colors: str = "white"
    position: str = "(W-w)/2:H-h-40"
    opacity: float = 0.85
    glow_enabled: bool = True
    glow_sigma: float = 12.0
    glow_opacity: float = 0.45
    ring: OverlayAudioVisualizerRing = field(default_factory=OverlayAudioVisualizerRing)
    fill: AudioVisualizerFill | None = None
    mirror_center: bool = False
    symmetric_vertical: bool = False
    rounding: AudioVisualizerRounding | None = None
    glow: AudioVisualizerGlow | None = None


@dataclass(frozen=True)
class OverlaySubscribePopup:
    """`overlays.subscribe_popup` セクション（optional, #511）.

    静止 PNG を時間窓だけ fade in / out しながら合成する subscribe popup の設定。
    `image` は `assets_dir` からの相対パス（既定 `subscribe-popup.png`）。
    `start_sec` / `duration_sec` は秒指定。`fade_sec` は in / out 共通の長さ。
    `position` は `overlay` フィルタの `x:y` 式。
    """

    enabled: bool = False
    image: str = "subscribe-popup.png"
    start_sec: float = 5.0
    duration_sec: float = 8.0
    fade_sec: float = 0.6
    position: str = "W-w-40:40"
    opacity: float = 1.0


@dataclass(frozen=True)
class OverlayEncoder:
    """`overlays.encoder` セクション（optional, #511）.

    overlays を合成すると `-c:v copy` は不可能になるため x264 で再エンコードする。
    値はすべて FFmpeg に直接渡す文字列。bitrate / bufsize は `-maxrate` / `-bufsize`
    と同じ書式を許容する（例 `4M`, `8000k`）。
    """

    codec: str = "libx264"
    preset: str = "medium"
    crf: int = 20
    pix_fmt: str = "yuv420p"
    maxrate: str = "4M"
    bufsize: str = "8M"
    profile: str = "high"
    framerate: int = 24


@dataclass(frozen=True)
class Overlays:
    """`overlays` セクション（optional, #511）.

    `enabled: false`（未設定時の既定）の場合 `generate_videos.sh` は従来通り
    `stream copy` 経路で動画を生成し、本セクションは完全に無視される。
    `enabled: true` のときのみ `audio_visualizer` / `subscribe_popup` が
    `filter_complex` 経路で合成され、`encoder` で再エンコードされる。
    """

    enabled: bool = False
    audio_visualizer: OverlayAudioVisualizer = field(default_factory=OverlayAudioVisualizer)
    subscribe_popup: OverlaySubscribePopup = field(default_factory=OverlaySubscribePopup)
    encoder: OverlayEncoder = field(default_factory=OverlayEncoder)


@dataclass(frozen=True)
class YoutubeSection:
    """YouTube 責務の合成."""

    api: YoutubeApi
    music_engine: str
    content_model: ContentModel
    overlays: Overlays = field(default_factory=Overlays)
