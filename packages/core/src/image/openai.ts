// OpenAI 画像生成プロバイダー（gpt-image-2 系。Python
// `utils/image_provider/openai.py` の移植）。
//
// `openai` SDK の `images.generate` / `images.edit` を呼ぶ。`aspectRatio` を
// OpenAI Images API の `size` 文字列にマップし、未対応比率は SDK を呼ぶ前に
// ConfigError で fail fast（リトライしない）。SDK client / sleep / persist は
// 注入され（テストは fake で差し替え）、API キーは `resolveSecret` 経由で取得する。

import { basename } from "node:path";

import { ConfigError } from "../errors.ts";
import { resolveSecret } from "../secrets.ts";
import { backoffMs, RETRY_MAX } from "./base.ts";
import type {
  ImageGenerationRequest,
  ImageGenerationResult,
  ImageProvider,
  PersistImage,
  SleepMs,
} from "./base.ts";
import { OPENAI_SUPPORTED_ASPECT_RATIOS } from "./config.ts";
import type { OpenAIConfig } from "./config.ts";
import { isRecord } from "./internal.ts";
import { defaultPersist, defaultSleep } from "./io.ts";
import { readReferenceFiles } from "./references.ts";

// `openai` client の最小シェイプ（注入点の seam）。
interface OpenAIClient {
  images: {
    generate(params: unknown): Promise<unknown>;
    edit(params: unknown): Promise<unknown>;
  };
}

/** OpenAIImageProvider の注入依存。省略時は production default が使われる。 */
export interface OpenAIProviderDeps {
  createClient: () => OpenAIClient | Promise<OpenAIClient>;
  persist: PersistImage;
  sleep: SleepMs;
}

// OpenAI Images API が受け付ける size 文字列へのマッピング。
const ASPECT_RATIO_TO_SIZE: Record<string, string> = {
  "16:9": "1536x1024",
  "9:16": "1024x1536",
};

// `{ data: [{ b64_json }, ...] }` から先頭の b64_json を持つ要素を decode する。
// b64_json を持たない要素はスキップする（openai.py:140-143）。
const decodeFirstImage = (response: unknown): Uint8Array | null => {
  if (!isRecord(response) || !Array.isArray(response.data)) {
    return null;
  }
  for (const item of response.data) {
    if (isRecord(item) && typeof item.b64_json === "string") {
      return new Uint8Array(Buffer.from(item.b64_json, "base64"));
    }
  }
  return null;
};

const defaultCreateClient = async (): Promise<OpenAIClient> => {
  const apiKey = await resolveSecret("OPENAI_API_KEY");
  const { default: OpenAI } = await import("openai");
  return new OpenAI({ apiKey }) as unknown as OpenAIClient;
};

const defaultDeps = (): OpenAIProviderDeps => ({
  createClient: defaultCreateClient,
  persist: defaultPersist,
  sleep: defaultSleep,
});

/** OpenAI Images API（gpt-image-2 系）で画像を 1 枚生成して保存する。 */
export class OpenAIImageProvider implements ImageProvider {
  readonly name = "openai";
  readonly supportedAspectRatios: readonly string[] = [
    ...OPENAI_SUPPORTED_ASPECT_RATIOS,
  ];

  private readonly config: OpenAIConfig;
  private readonly deps: OpenAIProviderDeps;

  // deps はテスト/サービス層が SDK client を差し替えるための注入点。省略時のみ
  // production default を使う（fallback ではなく明示的な DI 既定）。
  constructor(config: OpenAIConfig, deps?: OpenAIProviderDeps) {
    this.config = config;
    this.deps = deps ?? defaultDeps();
  }

  async generate(req: ImageGenerationRequest): Promise<ImageGenerationResult> {
    const size = ASPECT_RATIO_TO_SIZE[req.aspectRatio];
    if (size === undefined) {
      // 未対応比率は client 生成・SDK 呼び出し前に fail fast（リトライしない）。
      throw new ConfigError(
        `OpenAI image_generation の aspect_ratio=${JSON.stringify(req.aspectRatio)} は未対応。` +
          `許容値: ${JSON.stringify(Object.keys(ASPECT_RATIO_TO_SIZE))}`
      );
    }

    const { createClient, persist, sleep } = this.deps;
    const client = await createClient();
    const references = req.references ?? [];

    for (let attempt = 0; attempt < RETRY_MAX; attempt += 1) {
      try {
        const response = await this.callApi(client, req, size, references);
        const bytes = decodeFirstImage(response);
        if (bytes) {
          const savedPath = await persist(req.outputPath, bytes);
          return { savedPath, success: true };
        }
        // 画像なしレスポンス → リトライ。
      } catch {
        // 一時エラー → リトライ。
      }

      if (attempt < RETRY_MAX - 1) {
        await sleep(backoffMs(attempt));
      }
    }

    return { savedPath: null, success: false };
  }

  // 参照画像があれば images.edit、なければ images.generate を呼ぶ。
  private callApi(
    client: OpenAIClient,
    req: ImageGenerationRequest,
    size: string,
    references: readonly string[]
  ): Promise<unknown> {
    const base = {
      model: this.config.model,
      n: this.config.batch,
      prompt: req.prompt,
      quality: this.config.quality,
      size,
    };
    if (references.length > 0) {
      const image = readReferenceFiles(references).map(
        ({ bytes, path }) => new File([bytes], basename(path))
      );
      return client.images.edit({ ...base, image });
    }
    return client.images.generate(base);
  }
}
