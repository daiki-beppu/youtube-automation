// 画像生成サービス境界の入力 / 出力 schema（ADR-0003 §8: zod を source of truth）。
//
// 入力はチャンネル config / API レスポンス由来の JSON ではなく、呼び出し側が
// 組み立てる in-process な値オブジェクトのため、snake_case → camelCase の
// `.transform()` は不要で camelCase のまま declare する。型は `z.infer` で導出し
// 並書の `interface` は持たない。`.strict()` で未知キーを reject（fail fast）。

import { z } from "zod";

/**
 * 1 件分の画像生成リクエスト。
 *
 * - `prompt`: 生成プロンプト
 * - `outputPath`: 出力先（拡張子 .png なら PNG、.jpg なら JPEG として保存）
 * - `aspectRatio`: "16:9" / "9:16" / "1:1" など。OpenAI は 16:9 / 9:16 のみ受理
 * - `imageSize`: Provider 固有の解像度ヒント（Gemini は "1K"/"2K"/"4K" 等）
 * - `references`: 参照画像パス（省略・空なら参照なしモード）
 */
export const GenerateImageInput = z
  .object({
    aspectRatio: z.string(),
    imageSize: z.string(),
    outputPath: z.string(),
    prompt: z.string(),
    references: z.array(z.string()).optional(),
  })
  .strict();
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
