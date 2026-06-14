// YouTube API 設定・music_engine・content_model・overlays（merged の複数キーを合成）。

import { z } from "zod";

import { snakeToCamel } from "../../internal/case.ts";

/** `overlays.audio_visualizer` セクション（optional, #511）。 */
const OverlayAudioVisualizer = z
  .object({
    colors: z.string().default("white"),
    enabled: z.boolean().default(false),
    fscale: z.string().default("log"),
    glow_enabled: z.boolean().default(true),
    glow_opacity: z.number().default(0.45),
    glow_sigma: z.number().default(12),
    mode: z.string().default("bar"),
    opacity: z.number().default(0.85),
    position: z.string().default("(W-w)/2:H-h-40"),
    rate: z.string().default("24"),
    size: z.string().default("1280x180"),
    win_func: z.string().default("hann"),
    win_size: z.number().default(2048),
  })
  .strict()
  .prefault({});

/** `overlays.subscribe_popup` セクション（optional, #511）。 */
const OverlaySubscribePopup = z
  .object({
    duration_sec: z.number().default(8),
    enabled: z.boolean().default(false),
    fade_sec: z.number().default(0.6),
    image: z.string().default("subscribe-popup.png"),
    opacity: z.number().default(1),
    position: z.string().default("W-w-40:40"),
    start_sec: z.number().default(5),
  })
  .strict()
  .prefault({});

/** `overlays.encoder` セクション（optional, #511）。 */
const OverlayEncoder = z
  .object({
    bufsize: z.string().default("8M"),
    codec: z.string().default("libx264"),
    crf: z.number().default(20),
    framerate: z.number().default(24),
    maxrate: z.string().default("4M"),
    pix_fmt: z.string().default("yuv420p"),
    preset: z.string().default("medium"),
    profile: z.string().default("high"),
  })
  .strict()
  .prefault({});

/** `overlays` セクション（optional, #511）。 */
const Overlays = z
  .object({
    audio_visualizer: OverlayAudioVisualizer,
    enabled: z.boolean().default(false),
    encoder: OverlayEncoder,
    subscribe_popup: OverlaySubscribePopup,
  })
  .strict()
  .prefault({});

/** YouTube 責務の合成（`youtube` + `content_model` + `music_engine` + `overlays`）。 */
export const Youtube = z
  .object({
    content_model: z
      .object({
        // 未設定時は loader で [api.language] にフォールバックする。
        languages: z.array(z.string()).optional(),
        type: z.string().default("release"),
      })
      .strict()
      .prefault({}),
    music_engine: z.string().default("suno"),
    overlays: Overlays,
    youtube: z
      .object({
        category_id: z.string(),
        // 未設定時は現行の振る舞いに合わせ true / false（AI 開示フラグ）。
        contains_synthetic_media: z.boolean().default(true),
        language: z.string(),
        privacy_status: z.string(),
        self_declared_made_for_kids: z.boolean().default(false),
      })
      .strict(),
  })
  .transform((o) => {
    if (o.music_engine !== "suno" && o.music_engine !== "lyria") {
      console.warn(
        `music_engine='${o.music_engine}' は未知の値です（既知: 'suno' / 'lyria'）`
      );
    }
    return {
      api: {
        categoryId: o.youtube.category_id,
        containsSyntheticMedia: o.youtube.contains_synthetic_media,
        language: o.youtube.language,
        privacyStatus: o.youtube.privacy_status,
        selfDeclaredMadeForKids: o.youtube.self_declared_made_for_kids,
      },
      contentModel: {
        languages: o.content_model.languages ?? [o.youtube.language],
        type: o.content_model.type,
      },
      musicEngine: o.music_engine,
      overlays: snakeToCamel(o.overlays),
    };
  });
