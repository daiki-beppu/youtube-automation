// ImageProvider 抽象の最小契約（Python `utils/image_provider/base.py` の移植）。
//
// Gemini / OpenAI の差を吸収する薄い抽象化レイヤ。Provider 実装は 1-attempt 契約の
// `generate(req)` を実装し、成功なら画像 bytes を return、失敗は throw する（#959）。
// リトライ・バックオフ・永続化は service 層（`service.ts` の `withRetry` + persist）が
// 所有し、provider は SDK 呼び出しとレスポンス decode に集中する。Provider 中立の
// 値のみを `Request` に保持し、API 固有の `size` 文字列・`quality` 等は Provider
// 実装側で `aspectRatio` から導出する。

// 1 件分の画像生成リクエストは service 境界の入力 schema を単一の真実とする
// （ADR-0003 §8: zod を source of truth）。provider はその検証済みの値を受け取る。
import type { GenerateImageInput } from "./schema.ts";

export type ImageGenerationRequest = GenerateImageInput;

/**
 * 画像生成プロバイダーの最小契約。
 *
 * - `name`: 識別子（"gemini" / "openai"）
 * - `supportedAspectRatios`: 許容するアスペクト比の列。空配列は「制限なし」を意味する
 * - `generate(req)`: 1 attempt で画像 bytes を返す。失敗は throw（リトライは
 *   service の `withRetry` が所有する）
 */
export interface ImageProvider {
  readonly name: string;
  readonly supportedAspectRatios: readonly string[];
  generate(req: ImageGenerationRequest): Promise<Uint8Array>;
}

/** 生成した画像バイト列を `outputPath` に永続化し、保存先パスを返す注入点。 */
export type PersistImage = (
  outputPath: string,
  bytes: Uint8Array
) => Promise<string>;

/**
 * コンテンツポリシー由来のエラー（SAFETY / RECITATION）かを判定する。
 *
 * リトライしても通らないため、service 側の `shouldRetry` が non-retryable と
 * 判定するのに使う（Python `gemini.py` の即時失敗判定の移植）。
 */
export const isContentPolicyError = (error: unknown): boolean => {
  const message = (
    error instanceof Error ? error.message : String(error)
  ).toUpperCase();
  return message.includes("SAFETY") || message.includes("RECITATION");
};
