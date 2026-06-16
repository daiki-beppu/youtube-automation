// integrations バケット — 外部システム連携（distrokid / analytics）。
// 旧 flat な `distrokid` / `analytics` セクションを integrations 名前空間へ束ねる（Issue #827）。

import { z } from "zod";

import { Analytics } from "./analytics.ts";
import { Distrokid } from "./distrokid.ts";

/** integrations バケット: merged から外部連携セクションを取り出して束ねる。 */
export const Integrations = z.unknown().transform((merged) => ({
  analytics: Analytics.parse(merged),
  distrokid: Distrokid.parse(merged),
}));
