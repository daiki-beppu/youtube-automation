// 画像生成プロバイダー抽象化レイヤの公開 API
// （Python `utils/image_provider/__init__.py` の移植）。
//
// 公開 API:
// - generateImageService(input, deps): ADR-0003 Result 境界（ImageProvider.generate をラップ）
// - GenerateImageInput / GenerateImageOutput: service 境界の zod schema（+ z.infer 型）
// - getProvider(config): ImageGenerationConfig から ImageProvider 実装にディスパッチ
// - parseImageGenerationConfig(raw): skill-config から ImageGenerationConfig を構築
// - ImageProvider / ImageGenerationRequest / ImageGenerationResult: 抽象契約
// - RETRY_MAX / RETRY_BACKOFF: 共通リトライ定数
// - OPENAI_SUPPORTED_ASPECT_RATIOS: OpenAI が受理するアスペクト比

import type { ImageProvider } from "./base.ts";
import type { ImageGenerationConfig } from "./config.ts";
import { GeminiImageProvider } from "./gemini.ts";
import { OpenAIImageProvider } from "./openai.ts";

export {
  type ImageGenerationRequest,
  type ImageGenerationResult,
  type ImageProvider,
  RETRY_BACKOFF,
  RETRY_MAX,
} from "./base.ts";
export {
  type GeminiConfig,
  type ImageGenerationConfig,
  OPENAI_SUPPORTED_ASPECT_RATIOS,
  type OpenAIConfig,
  parseImageGenerationConfig,
} from "./config.ts";
export { GeminiImageProvider, type GeminiProviderDeps } from "./gemini.ts";
export { OpenAIImageProvider, type OpenAIProviderDeps } from "./openai.ts";
export { GenerateImageInput, GenerateImageOutput } from "./schema.ts";
export { generateImageService } from "./service.ts";

/**
 * `ImageGenerationConfig` から対応する provider 実装を返す。
 *
 * `provider` が {gemini, openai} 以外（手組みの不正値など）なら `config:` prefix Error で fail fast。
 */
export const getProvider = (config: ImageGenerationConfig): ImageProvider => {
  if (config.provider === "gemini") {
    return new GeminiImageProvider(config.gemini);
  }
  if (config.provider === "openai") {
    return new OpenAIImageProvider(config.openai);
  }
  const { provider } = config as { provider: string };
  throw new Error(`config: 未対応の provider=${JSON.stringify(provider)}`);
};
