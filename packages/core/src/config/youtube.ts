// YouTube API 設定・music_engine・content_model・overlays（Python `youtube.py` の移植）。

import { ConfigError } from "../errors.ts";
import { asRecord, isRecord } from "./internal.ts";

/** `youtube` セクション（API 基本設定）。 */
interface YoutubeApi {
  readonly categoryId: string;
  readonly privacyStatus: string;
  readonly language: string;
  // 未設定時は現行の振る舞いに合わせ true（AI 開示フラグ）。
  readonly containsSyntheticMedia: boolean;
  // 未設定時は現行の振る舞いに合わせ false（子供向け申告）。
  readonly selfDeclaredMadeForKids: boolean;
}

/** `content_model` セクション（optional）。 */
interface ContentModel {
  readonly type: string;
  readonly languages: readonly string[];
}

/** `overlays.audio_visualizer` セクション（optional, #511）。 */
interface OverlayAudioVisualizer {
  readonly enabled: boolean;
  readonly mode: string;
  readonly size: string;
  readonly rate: string;
  readonly fscale: string;
  readonly winSize: number;
  readonly winFunc: string;
  readonly colors: string;
  readonly position: string;
  readonly opacity: number;
  readonly glowEnabled: boolean;
  readonly glowSigma: number;
  readonly glowOpacity: number;
}

/** `overlays.subscribe_popup` セクション（optional, #511）。 */
interface OverlaySubscribePopup {
  readonly enabled: boolean;
  readonly image: string;
  readonly startSec: number;
  readonly durationSec: number;
  readonly fadeSec: number;
  readonly position: string;
  readonly opacity: number;
}

/** `overlays.encoder` セクション（optional, #511）。 */
interface OverlayEncoder {
  readonly codec: string;
  readonly preset: string;
  readonly crf: number;
  readonly pixFmt: string;
  readonly maxrate: string;
  readonly bufsize: string;
  readonly profile: string;
  readonly framerate: number;
}

/** `overlays` セクション（optional, #511）。 */
interface Overlays {
  readonly enabled: boolean;
  readonly audioVisualizer: OverlayAudioVisualizer;
  readonly subscribePopup: OverlaySubscribePopup;
  readonly encoder: OverlayEncoder;
}

/** YouTube 責務の合成。 */
export interface YoutubeSection {
  readonly api: YoutubeApi;
  readonly musicEngine: string;
  readonly contentModel: ContentModel;
  readonly overlays: Overlays;
}

const parseAudioVisualizer = (raw: unknown): OverlayAudioVisualizer => {
  const av = asRecord(raw, "overlays.audio_visualizer");
  return {
    colors: (av.colors as string | undefined) ?? "white",
    enabled: (av.enabled as boolean | undefined) ?? false,
    fscale: (av.fscale as string | undefined) ?? "log",
    glowEnabled: (av.glow_enabled as boolean | undefined) ?? true,
    glowOpacity: (av.glow_opacity as number | undefined) ?? 0.45,
    glowSigma: (av.glow_sigma as number | undefined) ?? 12,
    mode: (av.mode as string | undefined) ?? "bar",
    opacity: (av.opacity as number | undefined) ?? 0.85,
    position: (av.position as string | undefined) ?? "(W-w)/2:H-h-40",
    rate: (av.rate as string | undefined) ?? "24",
    size: (av.size as string | undefined) ?? "1280x180",
    winFunc: (av.win_func as string | undefined) ?? "hann",
    winSize: (av.win_size as number | undefined) ?? 2048,
  };
};

const parseSubscribePopup = (raw: unknown): OverlaySubscribePopup => {
  const sp = asRecord(raw, "overlays.subscribe_popup");
  return {
    durationSec: (sp.duration_sec as number | undefined) ?? 8,
    enabled: (sp.enabled as boolean | undefined) ?? false,
    fadeSec: (sp.fade_sec as number | undefined) ?? 0.6,
    image: (sp.image as string | undefined) ?? "subscribe-popup.png",
    opacity: (sp.opacity as number | undefined) ?? 1,
    position: (sp.position as string | undefined) ?? "W-w-40:40",
    startSec: (sp.start_sec as number | undefined) ?? 5,
  };
};

const parseEncoder = (raw: unknown): OverlayEncoder => {
  const enc = asRecord(raw, "overlays.encoder");
  return {
    bufsize: (enc.bufsize as string | undefined) ?? "8M",
    codec: (enc.codec as string | undefined) ?? "libx264",
    crf: (enc.crf as number | undefined) ?? 20,
    framerate: (enc.framerate as number | undefined) ?? 24,
    maxrate: (enc.maxrate as string | undefined) ?? "4M",
    pixFmt: (enc.pix_fmt as string | undefined) ?? "yuv420p",
    preset: (enc.preset as string | undefined) ?? "medium",
    profile: (enc.profile as string | undefined) ?? "high",
  };
};

const parseOverlays = (raw: unknown): Overlays => {
  const root = raw === undefined || raw === null ? {} : raw;
  if (!isRecord(root)) {
    throw new ConfigError("overlays セクションは object でなければなりません");
  }
  return {
    audioVisualizer: parseAudioVisualizer(root.audio_visualizer),
    enabled: (root.enabled as boolean | undefined) ?? false,
    encoder: parseEncoder(root.encoder),
    subscribePopup: parseSubscribePopup(root.subscribe_popup),
  };
};

export const parseYoutube = (
  merged: Record<string, unknown>
): YoutubeSection => {
  const yt = merged.youtube as Record<string, unknown>;
  const api: YoutubeApi = {
    categoryId: yt.category_id as string,
    containsSyntheticMedia:
      (yt.contains_synthetic_media as boolean | undefined) ?? true,
    language: yt.language as string,
    privacyStatus: yt.privacy_status as string,
    selfDeclaredMadeForKids:
      (yt.self_declared_made_for_kids as boolean | undefined) ?? false,
  };

  const cm = asRecord(merged.content_model, "content_model");
  const contentModel: ContentModel = {
    languages: [...((cm.languages as string[] | undefined) ?? [api.language])],
    type: (cm.type as string | undefined) ?? "release",
  };

  const musicEngine = (merged.music_engine as string | undefined) ?? "suno";
  if (musicEngine !== "suno" && musicEngine !== "lyria") {
    console.warn(
      `music_engine='${musicEngine}' は未知の値です（既知: 'suno' / 'lyria'）`
    );
  }

  return {
    api,
    contentModel,
    musicEngine,
    overlays: parseOverlays(merged.overlays),
  };
};
