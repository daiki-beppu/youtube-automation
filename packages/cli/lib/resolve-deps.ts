// CLI dependency resolver（#993 / ADR-0003 §6「CLI が I/O を所有」）。registry entry の
// `deps` 宣言を、run() に渡す具体的な DepsMap slice へ変換する単一の窓口。各依存を lazy に
// 構築するため、deps が空なら config ロードも認証も走らない（skills.list が無用な認証を
// 踏まない）。yt / ytAnalytics は 1 回の OAuth dance が返す同一 token から両 client を
// 構築し、認証往復は 1 度に閉じる。config singleton の起動もここだけに閉じる（#961 前倒し:
// service は loadConfig() を内部呼びしない）。
//
// MCP 到着時は env token + refresh のみの別 adapter を作る（interactive flow を持たない）。

import { channelDir, loadConfig } from "@youtube-automation/core/config";
import {
  buildYouTubeAnalyticsClient,
  buildYouTubeClient,
} from "@youtube-automation/core/oauth/client";
import type { DepsMap } from "@youtube-automation/core/registry";

import { resolveTokenJson } from "./oauth.ts";

/**
 * entry.deps を見て、要求された依存だけを lazy に構築した DepsMap slice を返す。
 *
 * - `config`      → loadConfig()（singleton loader の起動はここだけ）
 * - `yt` /
 *   `ytAnalytics` → 同一 token（resolveTokenJson の 1 回 dance）から該当 client を構築
 * - 空 deps       → 副作用ゼロで `{}` を返す
 */
export const resolveDeps = async <D extends keyof DepsMap>(
  deps: readonly D[],
  overrides?: Partial<Pick<DepsMap, "channelDir">>
): Promise<Pick<DepsMap, D>> => {
  const requested = new Set<keyof DepsMap>(deps);
  const resolved: Partial<DepsMap> = {};

  if (requested.has("config")) {
    resolved.config = loadConfig();
  }

  if (requested.has("channelDir")) {
    resolved.channelDir = overrides?.channelDir ?? channelDir();
  }

  const needsYt = requested.has("yt");
  const needsYtAnalytics = requested.has("ytAnalytics");
  if (needsYt || needsYtAnalytics) {
    const tokenJson = await resolveTokenJson();
    if (needsYt) {
      resolved.yt = buildYouTubeClient(tokenJson);
    }
    if (needsYtAnalytics) {
      resolved.ytAnalytics = buildYouTubeAnalyticsClient(tokenJson);
    }
  }

  return resolved as Pick<DepsMap, D>;
};
