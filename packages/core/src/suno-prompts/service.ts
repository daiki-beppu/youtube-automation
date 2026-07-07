import { readFile, realpath } from "node:fs/promises";

import { toServiceError } from "../errors.ts";
import type { ServiceError } from "../errors.ts";
import { err, ok } from "../result.ts";
import type { Result } from "../result.ts";
import { buildEntries } from "./builder.ts";
import { readSunoConfig } from "./config.ts";
import { parsePatternsJson } from "./parser.ts";
import { resolveSunoPaths } from "./paths.ts";
import { renderMarkdown } from "./renderer.ts";
import { GenerateSunoInputSchema, GenerateSunoOutputSchema } from "./schema.ts";
import type { GenerateSunoInput, GenerateSunoOutput } from "./schema.ts";
import { writeSunoPromptFiles } from "./writer.ts";

export const generateSunoPromptsService = async (
  input: GenerateSunoInput,
  deps: { channelDir: string }
): Promise<Result<GenerateSunoOutput, ServiceError>> => {
  try {
    const request = GenerateSunoInputSchema.parse(input);
    const channelDir = await realpath(deps.channelDir);
    const paths = await resolveSunoPaths(channelDir, request.path);
    const [patternsText, config] = await Promise.all([
      readFile(paths.patternsPath, "utf-8"),
      readSunoConfig(channelDir),
    ]);
    const patternsFile = parsePatternsJson(patternsText);
    const result = buildEntries(patternsFile, config);
    const markdown = renderMarkdown(patternsFile.title, result, config.config);
    const files = await writeSunoPromptFiles(
      paths.collectionDir,
      markdown,
      result.entries
    );

    return ok(
      GenerateSunoOutputSchema.parse({
        entryCount: result.entries.length,
        jsonPath: files.jsonPath,
        markdownPath: files.markdownPath,
        warnings: result.warnings,
      })
    );
  } catch (error) {
    return err(toServiceError(error));
  }
};
