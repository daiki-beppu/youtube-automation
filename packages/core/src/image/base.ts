// ImageProvider 抽象の最小契約と共有リトライ定数（Python `utils/image_provider/base.py` の移植）。
//
// Gemini / OpenAI の差を吸収する薄い抽象化レイヤ。Provider 実装は `generate(req)`
// を実装し、`ImageGenerationResult` を返す。Provider 中立の値のみを `Request` に保持し、
// API 固有の `size` 文字列・`quality` 等は Provider 実装側で `aspectRatio` から導出する。

// 1 件分の画像生成リクエストは service 境界の入力 schema を単一の真実とする
// （ADR-0003 §8: zod を source of truth）。provider はその検証済みの値を受け取る。
import type { GenerateImageInput } from "./schema.ts";

export type ImageGenerationRequest = GenerateImageInput;

// 共通リトライ定数（Gemini / OpenAI で共有）。秒単位。
export const RETRY_MAX = 3;
export const RETRY_BACKOFF = [10, 30, 60] as const;

/**
 * `attempt`（0 始まり）に対応するバックオフ待機をミリ秒で返す。
 *
 * 呼び出し側は `attempt < RETRY_MAX - 1` の範囲でのみ使う。範囲外は不変条件違反
 * として throw する（握りつぶさない）。
 */
export const backoffMs = (attempt: number): number => {
  const seconds = RETRY_BACKOFF[attempt];
  if (seconds === undefined) {
    throw new Error(
      `RETRY_BACKOFF に attempt=${attempt} のエントリがありません`
    );
  }
  return seconds * 1000;
};

/**
 * 画像生成の結果。
 *
 * - `success`: true なら保存成功
 * - `savedPath`: 保存先。失敗時は null
 */
export interface ImageGenerationResult {
  readonly success: boolean;
  readonly savedPath: string | null;
}

/**
 * 画像生成プロバイダーの最小契約。
 *
 * - `name`: 識別子（"gemini" / "openai"）
 * - `supportedAspectRatios`: 許容するアスペクト比の列。空配列は「制限なし」を意味する
 * - `generate(req)`: 1 枚生成して保存する
 */
export interface ImageProvider {
  readonly name: string;
  readonly supportedAspectRatios: readonly string[];
  generate(req: ImageGenerationRequest): Promise<ImageGenerationResult>;
}

/** 生成した画像バイト列を `outputPath` に永続化し、保存先パスを返す注入点。 */
export type PersistImage = (
  outputPath: string,
  bytes: Uint8Array
) => Promise<string>;

/** リトライ間バックオフのスリープ注入点（ミリ秒）。 */
export type SleepMs = (ms: number) => Promise<void>;
