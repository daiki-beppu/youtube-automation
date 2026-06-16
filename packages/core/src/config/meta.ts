// チャンネルメタ情報とブランディング設定（merged の `channel` + `youtube_channel` を合成）。

import { z } from "zod";

import { snakeToCamel } from "../../internal/case.ts";

/** `channel` セクション + `youtube_channel`（Branding）の合成。 */
export const ChannelMeta = z
  .object({
    channel: z
      .object({
        // YouTube チャンネル ID（`UC...`）。未設定（空文字）時は照合をスキップ (#561)。
        channel_id: z.string().default(""),
        core_message: z.string().default(""),
        cta_subscribe: z.string().default(""),
        name: z.string(),
        short: z.string(),
        tagline: z.string().default(""),
        url: z.string(),
        youtube_handle: z.string(),
      })
      .strict(),
    // `youtube_channel` セクション（YouTube チャンネル本体設定・任意）。
    // 未設定は null。`false` は明示的な「子供向けでない」申告として保持する。
    youtube_channel: z
      .object({
        country: z.string().default(""),
        default_language: z.string().default(""),
        description: z.string().default(""),
        keywords: z.array(z.string()).default([]),
        made_for_kids: z.boolean().nullable().default(null),
        unsubscribed_trailer: z.string().default(""),
      })
      .strict()
      .prefault({}),
  })
  .transform((o) => ({
    branding: snakeToCamel(o.youtube_channel),
    channelId: o.channel.channel_id,
    channelName: o.channel.name,
    channelShort: o.channel.short,
    channelUrl: o.channel.url,
    coreMessage: o.channel.core_message,
    ctaSubscribe: o.channel.cta_subscribe,
    tagline: o.channel.tagline,
    youtubeHandle: o.channel.youtube_handle,
  }));

export type ChannelMeta = z.infer<typeof ChannelMeta>;
export type Branding = ChannelMeta["branding"];

/**
 * Branding を YouTube API / yt-channel-settings が扱う dict 形式に戻す。
 * 未設定キーは省略するが、`made_for_kids=false` は明示申告のため省略しない。
 */
export const brandingAsApiDict = (b: Branding): Record<string, unknown> => {
  const out: Record<string, unknown> = {};
  if (b.description) {
    out.description = b.description;
  }
  if (b.keywords.length > 0) {
    out.keywords = [...b.keywords];
  }
  if (b.country) {
    out.country = b.country;
  }
  if (b.defaultLanguage) {
    out.default_language = b.defaultLanguage;
  }
  if (b.unsubscribedTrailer) {
    out.unsubscribed_trailer = b.unsubscribedTrailer;
  }
  if (b.madeForKids !== null) {
    out.made_for_kids = b.madeForKids;
  }
  return out;
};
