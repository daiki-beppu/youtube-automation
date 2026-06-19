// 参照画像ファイルの読み込みを 1 箇所に集約するヘルパー。
// Gemini（base64 inlineData 化）と OpenAI（File 化）の双方が生バイト読み込みを共有する。

import { readFileSync } from "node:fs";

/** 読み込んだ参照画像 1 件（パスと生バイト列のペア）。 */
export interface ReferenceImage {
  readonly path: string;
  readonly bytes: Uint8Array;
}

/** 参照画像パス列を読み込み、パスと生バイト列のペア列に変換する。順序は保つ。 */
export const readReferenceFiles = (
  references: readonly string[]
): ReferenceImage[] =>
  references.map((path) => ({
    bytes: new Uint8Array(readFileSync(path)),
    path,
  }));
