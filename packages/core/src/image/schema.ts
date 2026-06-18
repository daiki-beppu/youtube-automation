// 画像生成サービス境界の入力 / 出力 schema（ADR-0003 §8: zod を source of truth）。
//
// registry / CLI から入る raw input は snake_case のみ受理し、provider が consume する
// 内部 shape は camelCase へ正規化する。型は `z.infer` で導出し、並書の `interface` は
// 持たない。`.strict()` で未知キーを reject（fail fast）。

import { z } from "zod";

import { snakeToCamel } from "../../internal/case.ts";

/**
 * 1 件分の画像生成リクエスト。
 *
 * - `prompt`: 生成プロンプト
 * - `outputPath`: 出力先（拡張子 .png なら PNG、.jpg なら JPEG として保存）
 * - `aspectRatio`: "16:9" / "9:16" / "1:1" など。OpenAI は 16:9 / 9:16 のみ受理
 * - `imageSize`: Provider 固有の解像度ヒント（Gemini は "1K"/"2K"/"4K" 等）
 * - `references`: 参照画像パス（省略・空なら参照なしモード）
 */
export const GenerateImageRequest = z
  .object({
    aspectRatio: z.string(),
    imageSize: z.string(),
    outputPath: z.string(),
    prompt: z.string(),
    references: z.array(z.string()).readonly().optional(),
  })
  .strict();
export type GenerateImageRequest = z.infer<typeof GenerateImageRequest>;

export const GenerateImageInput = z
  .object({
    aspect_ratio: z.string(),
    image_size: z.string(),
    output_path: z.string(),
    prompt: z.string(),
    references: z.array(z.string()).optional(),
  })
  .strict()
  .transform(
    (input): GenerateImageRequest =>
      GenerateImageRequest.parse(snakeToCamel(input))
  );
export type GenerateImageInput = z.infer<typeof GenerateImageInput>;

/**
 * 画像生成の成功結果。
 *
 * - `savedPath`: 保存先パス。service は provider が保存成功した場合にのみ
 *   この値を `ok` で返し、失敗（保存なし）は `ServiceError` に変換する。
 */
export const GenerateImageOutput = z
  .object({
    savedPath: z.string(),
  })
  .strict();
export type GenerateImageOutput = z.infer<typeof GenerateImageOutput>;
