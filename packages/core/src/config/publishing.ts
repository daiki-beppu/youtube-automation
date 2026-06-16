// publishing バケット — 「出す物」の定義（content / workflow / audio / shorts / youtube）。
// youtube は production / publishing パラメータのため publishing へ束ねる（Issue #827）。
//
// content.tags.channelName は meta（identity バケット）由来のため、合成ルート（config.ts）が
// 注入する。ここでは Content schema が置くプレースホルダ（空文字）のまま素通しする。

import { z } from "zod";

import { Audio } from "./audio.ts";
import { Content } from "./content.ts";
import { Shorts } from "./shorts.ts";
import { Workflow } from "./workflow.ts";
import { Youtube } from "./youtube.ts";

/** publishing バケット: merged から出力系セクションを取り出して束ねる。 */
export const Publishing = z.unknown().transform((merged) => ({
  audio: Audio.parse(merged),
  content: Content.parse(merged),
  shorts: Shorts.parse(merged),
  workflow: Workflow.parse(merged),
  youtube: Youtube.parse(merged),
}));
