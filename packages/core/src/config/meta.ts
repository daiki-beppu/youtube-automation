// チャンネルメタ情報とブランディング設定（Python `utils/config/meta.py` の移植）。

import { isRecord } from "./internal.ts";

/** `youtube_channel` セクション（YouTube チャンネル本体設定・任意）。 */
export interface Branding {
  readonly description: string;
  readonly keywords: readonly string[];
  readonly country: string;
  readonly defaultLanguage: string;
  readonly unsubscribedTrailer: string;
  // 未設定は null。`false` は明示的な「子供向けでない」申告として保持する。
  readonly madeForKids: boolean | null;
}

/** `channel` セクション + `youtube_channel`（Branding）の合成。 */
export interface ChannelMeta {
  readonly channelName: string;
  readonly channelShort: string;
  readonly youtubeHandle: string;
  readonly channelUrl: string;
  readonly coreMessage: string;
  readonly ctaSubscribe: string;
  readonly tagline: string;
  // YouTube チャンネル ID（`UC...`）。未設定（空文字）時は照合をスキップ (#561)。
  readonly channelId: string;
  readonly branding: Branding;
}

const parseBranding = (data: unknown): Branding => {
  if (!isRecord(data)) {
    return {
      country: "",
      defaultLanguage: "",
      description: "",
      keywords: [],
      madeForKids: null,
      unsubscribedTrailer: "",
    };
  }
  return {
    country: (data.country as string | undefined) ?? "",
    defaultLanguage: (data.default_language as string | undefined) ?? "",
    description: (data.description as string | undefined) ?? "",
    keywords: [...((data.keywords as string[] | undefined) ?? [])],
    madeForKids: (data.made_for_kids as boolean | undefined) ?? null,
    unsubscribedTrailer:
      (data.unsubscribed_trailer as string | undefined) ?? "",
  };
};

export const parseMeta = (merged: Record<string, unknown>): ChannelMeta => {
  const ch = merged.channel as Record<string, unknown>;
  return {
    branding: parseBranding(merged.youtube_channel),
    channelId: (ch.channel_id as string | undefined) ?? "",
    channelName: ch.name as string,
    channelShort: ch.short as string,
    channelUrl: ch.url as string,
    coreMessage: (ch.core_message as string | undefined) ?? "",
    ctaSubscribe: (ch.cta_subscribe as string | undefined) ?? "",
    tagline: (ch.tagline as string | undefined) ?? "",
    youtubeHandle: ch.youtube_handle as string,
  };
};

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
