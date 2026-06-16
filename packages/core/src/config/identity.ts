// identity バケット — チャンネルの同一性（channel / youtube_channel）。
// 旧 flat な `meta` セクションを identity 名前空間へ束ねる（Issue #827）。

import { z } from "zod";

import { ChannelMeta } from "./meta.ts";

/** identity バケット: merged から meta セクションを取り出して束ねる。 */
export const Identity = z.unknown().transform((merged) => ({
  meta: ChannelMeta.parse(merged),
}));
