import { readFileSync } from "node:fs";

export interface ReferenceImage {
  readonly path: string;
  readonly bytes: Uint8Array;
}

export const readReferenceFiles = (
  references: readonly string[]
): ReferenceImage[] =>
  references.map((path) => {
    try {
      return { bytes: new Uint8Array(readFileSync(path)), path };
    } catch (error) {
      throw new Error(`Failed to read reference image: ${path}`, {
        cause: error,
      });
    }
  });
