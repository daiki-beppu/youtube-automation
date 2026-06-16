// 画像生成サービス境界（ADR-0003 §1）。`ImageProvider.generate` を Result でラップする。
//
// リトライ・バックオフ・永続化は本 service が所有する（#959）。provider は 1-attempt
// 契約（成功は画像 bytes、失敗は throw）に縮退済みで、`withRetry` が一時エラーを
// 既定の 10/30/60 秒バックオフで再試行する。コンテンツポリシー（SAFETY / RECITATION）
// と `config:` 等のドメインエラー・quota は retry しても通らないため即 rethrow される。
// core 内部（provider）は throw OK。境界の try/catch で `toServiceError` 経由に集約し、
// CLI/MCP は `if (!r.ok)` で discriminate する。マッピング:
//   - schema 違反（未知キー等）       → err(domain "validation")  (zod ZodError)
//   - 生成 + 保存成功                  → ok({ savedPath })
//   - 未 prefix の provider throw（画像なし / SAFETY 等）→ err(domain "io")
//   - provider が `config:` prefix throw（未対応比率など）→ err(domain "config")
//
// credentials は service input に含めない。SDK client / API キーは provider が自身の
// deps（`createClient`）で保持し、service は構築済み provider を `deps` で受け取る
// （ADR-0003 §7 / DI seam そのまま）。

import { toServiceError } from "../errors.ts";
import type { ServiceError } from "../errors.ts";
import { err, ok } from "../result.ts";
import type { Result } from "../result.ts";
import { defaultShouldRetry, withRetry } from "../retry.ts";
import type { SleepMs } from "../retry.ts";
import { isContentPolicyError } from "./base.ts";
import type { ImageProvider, PersistImage } from "./base.ts";
import { defaultPersist, defaultSleep } from "./io.ts";
import { GenerateImageInput, GenerateImageOutput } from "./schema.ts";

/**
 * 画像を 1 枚生成して保存し、保存先を `Result` で返す。
 *
 * 構築済み `ImageProvider`（gemini / openai）を `deps` で受け取る（ADR-0003 §7 /
 * DI seam そのまま）。`persist` / `sleep` は省略時に production default
 * （ディスク書き出し / 実時間待機）が使われる。入力は `.strict()` schema で先に
 * 検証してから provider を呼ぶため、不正入力は provider に到達せず validation
 * エラーになる。
 */
export const generateImageService = async (
  input: GenerateImageInput,
  deps: { persist?: PersistImage; provider: ImageProvider; sleep?: SleepMs }
): Promise<Result<GenerateImageOutput, ServiceError>> => {
  try {
    const request = GenerateImageInput.parse(input);
    const bytes = await withRetry(() => deps.provider.generate(request), {
      // SAFETY / RECITATION はリトライしても通らないため non-retryable に倒す。
      shouldRetry: (error) =>
        defaultShouldRetry(error) && !isContentPolicyError(error),
      sleep: deps.sleep ?? defaultSleep,
    });
    const savedPath = await (deps.persist ?? defaultPersist)(
      request.outputPath,
      bytes
    );
    return ok(GenerateImageOutput.parse({ savedPath }));
  } catch (error) {
    return err(toServiceError(error));
  }
};
