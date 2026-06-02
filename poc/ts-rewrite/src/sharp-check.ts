import sharp from "sharp";
import type { CheckResult } from "./types";

const CHECK_NAME = "sharp";
const SOURCE_SIZE = 64;
const TARGET_SIZE = 16;

/**
 * メモリ上で生成した PNG を resize し、出力サイズが指定どおりかを確認する。
 * native binding (libvips) が bun でロードできることの証拠になる。
 * native load 失敗時は例外を握りつぶさず ok:false として返し、run-smoke の撤退判定サマリを欠落させない。
 */
export async function checkSharp(): Promise<CheckResult> {
  try {
    const source = await sharp({
      create: {
        width: SOURCE_SIZE,
        height: SOURCE_SIZE,
        channels: 4,
        background: { r: 255, g: 0, b: 0, alpha: 1 },
      },
    })
      .png()
      .toBuffer();

    const resized = await sharp(source)
      .resize(TARGET_SIZE, TARGET_SIZE)
      .png()
      .toBuffer();

    const meta = await sharp(resized).metadata();
    const ok = meta.width === TARGET_SIZE && meta.height === TARGET_SIZE;
    return {
      name: CHECK_NAME,
      ok,
      detail: `${SOURCE_SIZE}x${SOURCE_SIZE} -> ${meta.width}x${meta.height}`,
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return {
      name: CHECK_NAME,
      ok: false,
      detail: `resize に失敗: ${message}`,
    };
  }
}
