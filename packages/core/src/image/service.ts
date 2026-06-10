// 画像生成サービス境界（ADR-0003 §1）。`ImageProvider.generate` を Result でラップする。
//
// core 内部（provider）は throw OK。境界の try/catch で `toServiceError` 経由に集約し、
// CLI/MCP は `if (!r.ok)` で discriminate する。マッピング:
//   - schema 違反（未知キー等）       → err(domain "validation")  (zod ZodError)
//   - provider 成功                    → ok({ savedPath })
//   - provider が保存なし（success:false）→ 未 prefix Error を throw → err(domain "io")
//   - provider が `config:` prefix throw（未対応比率など）→ err(domain "config")
//
// credentials は service input に含めない。SDK client / API キーは provider が自身の
// deps（`createClient`）で保持し、service は構築済み provider を `deps` で受け取る
// （ADR-0003 §7 / DI seam そのまま）。

import { toServiceError } from "../errors.ts";
import type { ServiceError } from "../errors.ts";
import { err, ok } from "../result.ts";
import type { Result } from "../result.ts";
import type { ImageProvider } from "./base.ts";
import { GenerateImageInput, GenerateImageOutput } from "./schema.ts";

/**
 * 画像を 1 枚生成して保存し、保存先を `Result` で返す。
 *
 * 構築済み `ImageProvider`（gemini / openai）を `deps` で受け取る（ADR-0003 §7 /
 * DI seam そのまま）。入力は `.strict()` schema で先に検証してから provider を
 * 呼ぶため、不正入力は provider に到達せず validation エラーになる。
 */
export const generateImageService = async (
  input: GenerateImageInput,
  deps: { provider: ImageProvider }
): Promise<Result<GenerateImageOutput, ServiceError>> => {
  try {
    const request = GenerateImageInput.parse(input);
    const result = await deps.provider.generate(request);
    if (!result.success || result.savedPath === null) {
      // 未 prefix の失敗は io ドメインへ（toServiceError の既定経路）。
      throw new Error(
        `${deps.provider.name} provider が画像を保存できませんでした`
      );
    }
    return ok(GenerateImageOutput.parse({ savedPath: result.savedPath }));
  } catch (error) {
    return err(toServiceError(error));
  }
};
