// Gemini 画像生成プロバイダー（Python `utils/image_provider/gemini.py` の移植）。
//
// `@google/genai` SDK でのリクエスト送信・参照画像の inlineData 化・base64 decode を
// 担う 1-attempt 契約の provider（#959）。リトライ・バックオフ・永続化は service 層
// （`service.ts` の `withRetry` + persist）が所有するため、ここでは SDK エラーを
// そのまま throw する（SAFETY / RECITATION は service 側の `shouldRetry` が
// non-retryable と判定する）。SDK client は注入され（テストは fake で差し替え）、
// ここはレスポンス decode と参照画像の inline 化に集中する。

import type { ImageGenerationRequest, ImageProvider } from "./base.ts";
import type { GeminiConfig } from "./config.ts";
import { isRecord } from "./internal.ts";
import { readReferenceFiles } from "./references.ts";

// `@google/genai` client の最小シェイプ（注入点の seam）。
interface GeminiClient {
  models: {
    generateContent(params: unknown): Promise<unknown>;
  };
}

/** GeminiImageProvider の注入依存。省略時は production default が使われる。 */
export interface GeminiProviderDeps {
  createClient: () => GeminiClient | Promise<GeminiClient>;
}

// `{ candidates: [{ content: { parts: [...] } }] }` から parts を取り出す。
// 想定外の形は空配列に落とし、「画像なしレスポンス」として throw 経路へ合流させる。
const extractParts = (response: unknown): unknown[] => {
  if (!isRecord(response) || !Array.isArray(response.candidates)) {
    return [];
  }
  const [first] = response.candidates;
  if (!isRecord(first) || !isRecord(first.content)) {
    return [];
  }
  return Array.isArray(first.content.parts) ? first.content.parts : [];
};

const inlineImageBytes = (part: unknown): Uint8Array | null => {
  if (
    isRecord(part) &&
    isRecord(part.inlineData) &&
    typeof part.inlineData.data === "string"
  ) {
    return new Uint8Array(Buffer.from(part.inlineData.data, "base64"));
  }
  return null;
};

const referenceMime = (path: string): string =>
  /\.jpe?g$/iu.test(path) ? "image/jpeg" : "image/png";

// 参照画像を base64 inlineData Part に変換し、末尾に prompt を付ける（参照なしは [prompt]）。
const buildContents = (
  prompt: string,
  references: readonly string[]
): unknown[] => {
  if (references.length === 0) {
    return [prompt];
  }
  const parts = readReferenceFiles(references).map(({ bytes, path }) => ({
    inlineData: {
      data: Buffer.from(bytes).toString("base64"),
      mimeType: referenceMime(path),
    },
  }));
  return [...parts, prompt];
};

const defaultCreateClient = async (): Promise<GeminiClient> => {
  const project = process.env.GOOGLE_CLOUD_PROJECT;
  if (!project) {
    throw new Error(
      "config: GOOGLE_CLOUD_PROJECT が未設定です。Vertex AI の project を指定してください"
    );
  }
  const { GoogleGenAI } = await import("@google/genai");
  // 画像系モデルは Vertex AI の global location のみサポート（genai_client.py 参照）。
  return new GoogleGenAI({
    location: "global",
    project,
    vertexai: true,
  }) as unknown as GeminiClient;
};

const defaultDeps = (): GeminiProviderDeps => ({
  createClient: defaultCreateClient,
});

/** Gemini API（Vertex AI 経由）で画像を 1 attempt 生成し、画像 bytes を返す。 */
export class GeminiImageProvider implements ImageProvider {
  readonly name = "gemini";
  // Gemini はアスペクト比を制限しない（branding/icon.png 用途で 1:1 等を許容）。
  readonly supportedAspectRatios: readonly string[] = [];

  private readonly config: GeminiConfig;
  private readonly deps: GeminiProviderDeps;

  // deps はテスト/サービス層が SDK client を差し替えるための注入点。省略時のみ
  // production default を使う（fallback ではなく明示的な DI 既定）。
  constructor(config: GeminiConfig, deps?: GeminiProviderDeps) {
    this.config = config;
    this.deps = deps ?? defaultDeps();
  }

  async generate(req: ImageGenerationRequest): Promise<Uint8Array> {
    const client = await this.deps.createClient();
    const references = req.references ?? [];
    // req.imageSize が空のときのみ config の既定解像度に委ねる（Python と同じ挙動）。
    const imageSize = req.imageSize || this.config.imageSize;
    const params = {
      config: {
        imageConfig: { aspectRatio: req.aspectRatio, imageSize },
        responseModalities: ["IMAGE", "TEXT"],
      },
      contents: buildContents(req.prompt, references),
      model: this.config.model,
    };

    // SDK エラー（SAFETY / RECITATION 含む）はそのまま伝播させる。
    const response = await client.models.generateContent(params);
    for (const part of extractParts(response)) {
      const bytes = inlineImageBytes(part);
      if (bytes) {
        return bytes;
      }
    }
    // 画像なしレスポンスは未 prefix Error（service 側で retryable と判定される）。
    throw new Error("gemini が画像なしレスポンスを返しました");
  }
}
