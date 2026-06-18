// CLI dependency resolver（#993 / ADR-0003 §6「CLI が I/O を所有」）。registry entry の
// `deps` 宣言を、run() に渡す具体的な DepsMap slice へ変換する単一の窓口。各依存を lazy に
// 構築するため、deps が空なら config ロードも認証も走らない（skills.list が無用な認証を
// 踏まない）。yt / ytAnalytics は 1 回の OAuth dance が返す同一 token から両 client を
// 構築し、認証往復は 1 度に閉じる。config singleton の起動もここだけに閉じる（#961 前倒し:
// service は loadConfig() を内部呼びしない）。
//
// MCP 到着時は env token + refresh のみの別 adapter を作る（interactive flow を持たない）。

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { channelDir, loadConfig } from "@youtube-automation/core/config";
import type {
  ImageGenerationConfig,
  OpenAIProviderDeps,
} from "@youtube-automation/core/image";
import {
  getProvider,
  OpenAIImageProvider,
  parseImageGenerationConfig,
} from "@youtube-automation/core/image";
import {
  buildYouTubeAnalyticsClient,
  buildYouTubeClient,
} from "@youtube-automation/core/oauth/client";
import type { DepsMap } from "@youtube-automation/core/registry";
import { parse as parseYaml } from "yaml";

import { resolveTokenJson } from "./oauth.ts";
import { resolveSecret } from "./secrets.ts";

const THUMBNAIL_SKILL_CONFIG_PATH = ["config", "skills", "thumbnail.yaml"];

const loadThumbnailSkillConfig = (root: string): ImageGenerationConfig => {
  const path = join(root, ...THUMBNAIL_SKILL_CONFIG_PATH);
  if (!existsSync(path)) {
    return parseImageGenerationConfig({});
  }
  const text = readFileSync(path, "utf-8");
  return parseImageGenerationConfig(parseYaml(text));
};

const createOpenAIClientFromSecret: OpenAIProviderDeps["createClient"] =
  async () => {
    const apiKey = await resolveSecret("OPENAI_API_KEY");
    const { default: OpenAI } = await import("openai");
    return new OpenAI({ apiKey }) as unknown as Awaited<
      ReturnType<OpenAIProviderDeps["createClient"]>
    >;
  };

const buildImageProvider = (
  config: ImageGenerationConfig
): DepsMap["imageProvider"] => {
  if (config.provider !== "openai") {
    return getProvider(config);
  }
  return new OpenAIImageProvider(config.openai, {
    createClient: createOpenAIClientFromSecret,
  });
};

/**
 * entry.deps を見て、要求された依存だけを lazy に構築した DepsMap slice を返す。
 *
 * - `config`      → loadConfig()（singleton loader の起動はここだけ）
 * - `imageProvider` → config/skills/thumbnail.yaml から Gemini / OpenAI provider を構築
 * - `yt` /
 *   `ytAnalytics` → 同一 token（resolveTokenJson の 1 回 dance）から該当 client を構築
 * - 空 deps       → 副作用ゼロで `{}` を返す
 */
export const resolveDeps = async <D extends keyof DepsMap>(
  deps: readonly D[]
): Promise<Pick<DepsMap, D>> => {
  const requested = new Set<keyof DepsMap>(deps);
  const resolved: Partial<DepsMap> = {};

  if (requested.has("config")) {
    resolved.config = loadConfig();
  }

  if (requested.has("channelDir")) {
    resolved.channelDir = channelDir();
  }

  if (requested.has("imageProvider")) {
    const root = channelDir();
    const config = loadThumbnailSkillConfig(root);
    resolved.imageProvider = buildImageProvider(config);
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
