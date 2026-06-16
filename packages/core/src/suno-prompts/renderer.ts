import type { BuildEntriesResult, SunoConfig } from "./types.ts";

export const renderMarkdown = (
  title: string,
  result: BuildEntriesResult,
  config: SunoConfig
): string => {
  const sections = result.entries.map((entry) =>
    [
      `## ${entry.name}`,
      "",
      "**Styles:**",
      "```",
      entry.style,
      "```",
      ...(config.excludeStyles === undefined
        ? []
        : ["", "**Exclude Styles:**", "```", config.excludeStyles, "```"]),
      ...(result.mode === "vocal" && entry.lyrics.length > 0
        ? ["", "**Lyrics:**", "```", entry.lyrics, "```"]
        : []),
    ].join("\n")
  );
  return [
    `# Suno Prompts — ${title}`,
    "",
    "## SunoAI 推奨設定",
    "",
    "| パラメータ | 値 |",
    "|-----------|-----|",
    "| Mode | Custom |",
    `| Weirdness | ${config.weirdness}% |`,
    `| Style Influence | ${config.styleInfluence}% |`,
    `| Instrumental | ${result.mode === "vocal" ? "OFF（ボーカルモード）" : "ON（インストモード）"} |`,
    `| Lyrics | ${result.mode === "vocal" ? "各パターンの Lyrics 欄を投入" : "(空)"} |`,
    "",
    "---",
    "",
    ...sections,
  ].join("\n");
};
