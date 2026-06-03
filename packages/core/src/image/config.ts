// 画像生成プロバイダーの設定型と skill-config パーサ（Python
// `utils/image_provider/config.py` の移植）。
//
// skill-config の `image_generation:` namespace を解析し、`provider` 値に応じた
// `GeminiConfig` / `OpenAIConfig` を保持する discriminated union を構築する。
//
// 移植スコープ（plan §4-D）: legacy `gemini_image:` namespace・`gemini_cli` /
// `codex` provider・`thinking`・`replace_model` は移植しない。よって未対応の
// provider 値（"codex" / "gemini_cli" を含む）は ConfigError で fail fast する。
// 入力キーは snake_case（既存 config パーサと同様）、出力は camelCase。

import { ConfigError } from "../errors.ts";
import { isRecord } from "./internal.ts";

// サポートする provider 識別子。`getProvider` の dispatch キーと一致させる。
const SUPPORTED_PROVIDERS = ["gemini", "openai"] as const;

/** OpenAI が受理するアスペクト比（16:9 と 9:16 のみ）。 */
export const OPENAI_SUPPORTED_ASPECT_RATIOS = ["16:9", "9:16"] as const;

const DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-image-preview";
const DEFAULT_GEMINI_IMAGE_SIZE = "2K";
const DEFAULT_OPENAI_MODEL = "gpt-image-2";
const DEFAULT_OPENAI_QUALITY = "high";
const DEFAULT_OPENAI_ASPECT_RATIO = "16:9";
const DEFAULT_OPENAI_BATCH = 1;

/**
 * Gemini 画像生成プロバイダーの設定。
 *
 * `aspectRatio` フィールドは持たない。Gemini は branding/icon.png 用途で 1:1 等の
 * 任意比率を受け付けるため、aspectRatio は `ImageGenerationRequest` 経由で都度渡す。
 */
export interface GeminiConfig {
  readonly model: string;
  readonly imageSize: string;
}

/**
 * OpenAI 画像生成プロバイダー（gpt-image-2 系）の設定。
 *
 * `aspectRatio` はパース時に `OPENAI_SUPPORTED_ASPECT_RATIOS` へ制限する（fail fast）。
 */
export interface OpenAIConfig {
  readonly model: string;
  readonly quality: string;
  readonly aspectRatio: string;
  readonly batch: number;
}

/**
 * provider 切り替え可能な画像生成設定。`provider` で判別する discriminated union で、
 * 対応する側の sub-config のみを保持する。
 */
export type ImageGenerationConfig =
  | { readonly provider: "gemini"; readonly gemini: GeminiConfig }
  | { readonly provider: "openai"; readonly openai: OpenAIConfig };

const readString = (
  source: Record<string, unknown>,
  key: string,
  fallback: string
): string => {
  const value = source[key];
  return typeof value === "string" ? value : fallback;
};

const readInt = (
  source: Record<string, unknown>,
  key: string,
  fallback: number
): number => {
  const value = source[key];
  return typeof value === "number" ? value : fallback;
};

const buildGemini = (sub: Record<string, unknown>): GeminiConfig => ({
  imageSize: readString(sub, "image_size", DEFAULT_GEMINI_IMAGE_SIZE),
  model: readString(sub, "model", DEFAULT_GEMINI_MODEL),
});

const buildOpenAI = (sub: Record<string, unknown>): OpenAIConfig => {
  const aspectRatio = readString(
    sub,
    "aspect_ratio",
    DEFAULT_OPENAI_ASPECT_RATIO
  );
  if (
    !OPENAI_SUPPORTED_ASPECT_RATIOS.includes(
      aspectRatio as (typeof OPENAI_SUPPORTED_ASPECT_RATIOS)[number]
    )
  ) {
    throw new ConfigError(
      `OpenAI image_generation.openai.aspect_ratio=${JSON.stringify(aspectRatio)} は未対応。` +
        `許容値: ${JSON.stringify(OPENAI_SUPPORTED_ASPECT_RATIOS)}`
    );
  }
  return {
    aspectRatio,
    batch: readInt(sub, "batch", DEFAULT_OPENAI_BATCH),
    model: readString(sub, "model", DEFAULT_OPENAI_MODEL),
    quality: readString(sub, "quality", DEFAULT_OPENAI_QUALITY),
  };
};

const defaultConfig = (): ImageGenerationConfig => ({
  gemini: {
    imageSize: DEFAULT_GEMINI_IMAGE_SIZE,
    model: DEFAULT_GEMINI_MODEL,
  },
  provider: "gemini",
});

const subSection = (
  section: Record<string, unknown>,
  key: string
): Record<string, unknown> => {
  const value = section[key];
  return isRecord(value) ? value : {};
};

/**
 * skill-config（raw）から `ImageGenerationConfig` を組み立てる。
 *
 * `image_generation:` namespace が無ければ gemini 既定値を返す。`provider` が
 * {gemini, openai} 以外なら ConfigError で fail fast する。
 */
export const parseImageGenerationConfig = (
  raw: unknown
): ImageGenerationConfig => {
  if (!isRecord(raw)) {
    return defaultConfig();
  }
  const section = raw.image_generation;
  if (!isRecord(section)) {
    return defaultConfig();
  }

  const provider = readString(section, "provider", "gemini");
  if (provider === "gemini") {
    return { gemini: buildGemini(subSection(section, "gemini")), provider };
  }
  if (provider === "openai") {
    return { openai: buildOpenAI(subSection(section, "openai")), provider };
  }
  throw new ConfigError(
    `image_generation.provider=${JSON.stringify(provider)} は未対応。` +
      `許容値: ${JSON.stringify(SUPPORTED_PROVIDERS)}`
  );
};
