import { readFile, realpath } from "node:fs/promises";

import { createService } from "../service.ts";
import { buildEntries } from "./builder.ts";
import { readSunoConfig } from "./config.ts";
import { parsePatternsYaml } from "./parser.ts";
import { resolveSunoPaths } from "./paths.ts";
import { renderMarkdown } from "./renderer.ts";
import { GenerateSunoInputSchema, GenerateSunoOutputSchema } from "./schema.ts";
import { writeSunoPromptFiles } from "./writer.ts";

export const generateSunoPromptsService = createService(
  GenerateSunoInputSchema,
  GenerateSunoOutputSchema,
  async (request, deps: { channelDir: string }) => {
    const channelDir = await realpath(deps.channelDir);
    const paths = await resolveSunoPaths(channelDir, request.path);
    const [patternsText, config] = await Promise.all([
      readFile(paths.patternsPath, "utf-8"),
      readSunoConfig(channelDir),
    ]);
    const patternsFile = parsePatternsYaml(patternsText);
    const result = buildEntries(patternsFile, config);
    const markdown = renderMarkdown(patternsFile.title, result, config.config);
    const files = await writeSunoPromptFiles(
      paths.collectionDir,
      markdown,
      result.entries
    );

    return {
      entryCount: result.entries.length,
      jsonPath: files.jsonPath,
      markdownPath: files.markdownPath,
      warnings: result.warnings,
    };
  }
);
