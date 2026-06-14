// OpenAI 画像生成プロバイダー（gpt-image-2 系。Python
// `utils/image_provider/openai.py` の移植）。
//
// `openai` SDK の `images.generate` / `images.edit` を呼ぶ 1-attempt 契約の
// provider（#959）。リトライ・バックオフ・永続化は service 層（`service.ts` の
// `withRetry` + persist）が所有する。`aspectRatio` を OpenAI Images API の `size`
// 文字列にマップし、未対応比率は SDK を呼ぶ前に `config:` prefix Error で fail fast
// （`defaultShouldRetry` が即 rethrow する）。SDK client は注入され（テストは fake で
// 差し替え）、API キーは env から取得する。
//
// #822 で秘密解決を cli 層 (`packages/cli/lib/secrets.ts`) へ移設したため、core は
// op (1Password) を呼べない（ADR 0002 / oxlint で機械担保）。production default は
// `OPENAI_API_KEY` env を直読みし、未設定なら fail fast する。op fallback が必要な
// 経路は cli/service 層が `createClient` を注入して供給する。
// 名前タグ class (ConfigError 等) は #821 で撤廃済み — `config:` prefix が
// ドメインエラーの単一の真実であり、toServiceError でルーティングされる。

import { basename } from "node:path";

import type { ImageGenerationRequest, ImageProvider } from "./base.ts";
import { OPENAI_SUPPORTED_ASPECT_RATIOS } from "./config.ts";
import type { OpenAIConfig } from "./config.ts";
import { isRecord } from "./internal.ts";
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
  const apiKey = process.env.OPENAI_API_KEY;
  if (!apiKey) {
    throw new Error(
      "config: OPENAI_API_KEY が未設定です。" +
        ".env に設定するか、OpenAIImageProvider に createClient を注入してください"
    );
  }
  const { default: OpenAI } = await import("openai");
  return new OpenAI({ apiKey }) as unknown as OpenAIClient;
};

const defaultDeps = (): OpenAIProviderDeps => ({
  createClient: defaultCreateClient,
});

/** OpenAI Images API（gpt-image-2 系）で画像を 1 attempt 生成し、画像 bytes を返す。 */
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

  async generate(req: ImageGenerationRequest): Promise<Uint8Array> {
    const size = ASPECT_RATIO_TO_SIZE[req.aspectRatio];
    if (size === undefined) {
      // 未対応比率は client 生成・SDK 呼び出し前に fail fast（リトライしない）。
      throw new Error(
        `config: OpenAI image_generation の aspect_ratio=${JSON.stringify(req.aspectRatio)} は未対応。` +
          `許容値: ${JSON.stringify(Object.keys(ASPECT_RATIO_TO_SIZE))}`
      );
    }

    const client = await this.deps.createClient();
    const references = req.references ?? [];

    // SDK エラーはそのまま伝播させる（リトライ判定は service 側の責務）。
    const response = await this.callApi(client, req, size, references);
    const bytes = decodeFirstImage(response);
    if (bytes) {
      return bytes;
    }
    // b64 decode できないレスポンスは未 prefix Error（service 側で retryable と判定される）。
    throw new Error("openai が画像なしレスポンスを返しました");
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
