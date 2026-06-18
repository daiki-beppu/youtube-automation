import {
  existsSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { dirname, join } from "node:path";

import { toServiceError } from "../errors.ts";
import type { ServiceError } from "../errors.ts";
import { err, ok } from "../result.ts";
import type { Result } from "../result.ts";
import { ChannelInitInputSchema, ChannelInitOutputSchema } from "./schema.ts";
import type { ChannelInitInput, ChannelInitOutput } from "./schema.ts";

const CONFIG_SUBDIR = "config/channel";
const GITKEEP_NAME = ".gitkeep";

const CONFIG_FILES = [
  "meta.json",
  "content.json",
  "youtube.json",
  "analytics.json",
  "playlists.json",
  "workflow.json",
  "audio.json",
] as const;

const GITKEEP_DIRS = [
  "auth",
  "collections",
  "data",
  "docs/benchmarks",
  "research",
] as const;

type ActionKind = "created" | "skipped" | "overwritten";

interface FileAction {
  readonly diff: string;
  readonly kind: ActionKind;
  readonly newText: string;
  readonly path: string;
  readonly rel: string;
}

interface DirectoryAction {
  readonly kind: ActionKind;
  readonly path: string;
  readonly rel: string;
}

interface Plan {
  readonly directories: readonly DirectoryAction[];
  readonly files: readonly FileAction[];
}

type JsonObject = Record<string, unknown>;

type TemplateRenderer = (input: ChannelInitInput) => JsonObject;

const renderMeta: TemplateRenderer = (input) => ({
  channel: {
    name: input.name,
    short: input.short,
    url: "",
    youtube_handle: "",
  },
});

const renderContent: TemplateRenderer = (input) => ({
  descriptions: { hashtags: [], opening: "", perfect_for: [] },
  genre: {
    context: input.context,
    primary: input.genre,
    style: input.style,
  },
  tags: { base: [], themes: {} },
  title: { template: "" },
});

const renderYoutube = (): JsonObject => ({
  youtube: {
    category_id: "10",
    language: "en",
    privacy_status: "public",
  },
});

const renderAnalytics = (): JsonObject => ({
  benchmark: {
    channels: [],
  },
});

const renderEmpty = (): JsonObject => ({});

const TEMPLATES: Record<(typeof CONFIG_FILES)[number], TemplateRenderer> = {
  "analytics.json": renderAnalytics,
  "audio.json": renderEmpty,
  "content.json": renderContent,
  "meta.json": renderMeta,
  "playlists.json": renderEmpty,
  "workflow.json": renderEmpty,
  "youtube.json": renderYoutube,
};

const serializeJson = (data: JsonObject): string =>
  `${JSON.stringify(data, null, 2)}\n`;

const splitLines = (text: string): string[] => {
  if (text === "") {
    return [];
  }
  const lines = text.split("\n");
  if (text.endsWith("\n")) {
    lines.pop();
  }
  return lines;
};

const hunkRange = (lineCount: number): string => {
  if (lineCount === 0) {
    return "0,0";
  }
  if (lineCount === 1) {
    return "1";
  }
  return `1,${lineCount}`;
};

const assertDirectoryExists = (path: string): string => {
  if (!existsSync(path) || !statSync(path).isDirectory()) {
    throw new Error(
      `config: channelDir が存在するディレクトリではありません: ${path}`
    );
  }
  return realpathSync(path);
};

const unifiedDiff = (current: string, next: string, rel: string): string => {
  const currentLines = splitLines(current);
  const nextLines = splitLines(next);
  const lines = [
    `--- ${rel} (existing)\n`,
    `+++ ${rel} (template)\n`,
    `@@ -${hunkRange(currentLines.length)} +${hunkRange(nextLines.length)} @@\n`,
    ...currentLines.map((line) => `-${line}\n`),
    ...nextLines.map((line) => `+${line}\n`),
  ];
  return lines.join("");
};

const planFile = (
  path: string,
  rel: string,
  newText: string,
  force: boolean
): FileAction => {
  if (!existsSync(path)) {
    return { diff: "", kind: "created", newText, path, rel };
  }

  const current = readFileSync(path, "utf-8");
  if (current === newText) {
    return { diff: "", kind: "skipped", newText, path, rel };
  }
  if (force) {
    return { diff: "", kind: "overwritten", newText, path, rel };
  }
  return {
    diff: unifiedDiff(current, newText, rel),
    kind: "skipped",
    newText,
    path,
    rel,
  };
};

const planDirectory = (target: string, rel: string): DirectoryAction => {
  const path = join(target, rel);
  const gitkeep = join(path, GITKEEP_NAME);
  if (
    existsSync(path) &&
    statSync(path).isDirectory() &&
    existsSync(gitkeep) &&
    statSync(gitkeep).isFile()
  ) {
    return { kind: "skipped", path, rel };
  }
  return { kind: "created", path, rel };
};

const planActions = (target: string, input: ChannelInitInput): Plan => {
  const files = CONFIG_FILES.map((name) => {
    const rel = `${CONFIG_SUBDIR}/${name}`;
    return planFile(
      join(target, rel),
      rel,
      serializeJson(TEMPLATES[name](input)),
      input.force
    );
  });
  const directories = GITKEEP_DIRS.map((rel) => planDirectory(target, rel));
  return { directories, files };
};

const assertDirectoryPathAvailable = (target: string, rel: string): void => {
  let cursor = target;
  for (const segment of rel.split("/")) {
    cursor = join(cursor, segment);
    if (existsSync(cursor) && !statSync(cursor).isDirectory()) {
      throw new Error(
        `config: channel-init scaffold path is blocked by a file: ${cursor}`
      );
    }
  }
};

const preflightPlan = (plan: Plan, target: string): void => {
  const directoryRels = new Set<string>();
  for (const action of plan.files) {
    if (action.kind === "created" || action.kind === "overwritten") {
      directoryRels.add(dirname(action.rel));
    }
  }
  for (const action of plan.directories) {
    if (action.kind === "created") {
      directoryRels.add(action.rel);
      const gitkeep = join(action.path, GITKEEP_NAME);
      if (existsSync(gitkeep) && !statSync(gitkeep).isFile()) {
        throw new Error(
          `config: channel-init .gitkeep path is blocked by a directory: ${gitkeep}`
        );
      }
    }
  }
  for (const rel of directoryRels) {
    assertDirectoryPathAvailable(target, rel);
  }
};

const applyPlan = (plan: Plan): void => {
  for (const action of plan.files) {
    if (action.kind === "created" || action.kind === "overwritten") {
      mkdirSync(dirname(action.path), { recursive: true });
      writeFileSync(action.path, action.newText, "utf-8");
    }
  }
  for (const action of plan.directories) {
    if (action.kind === "created") {
      mkdirSync(action.path, { recursive: true });
      writeFileSync(join(action.path, GITKEEP_NAME), "", "utf-8");
    }
  }
};

const formatSummary = (plan: Plan): string => {
  const fileLines = plan.files.map(
    (action) => `  ${action.kind.padEnd(11, " ")} ${action.rel}`
  );
  const directoryLines = plan.directories.map(
    (action) => `  ${action.kind.padEnd(11, " ")} ${action.rel}/`
  );
  return [...fileLines, ...directoryLines].join("\n");
};

const collectDiffs = (plan: Plan): string =>
  plan.files.map((action) => action.diff).join("");

export const channelInitService = (
  input: ChannelInitInput,
  deps: { channelDir: string }
): Promise<Result<ChannelInitOutput, ServiceError>> => {
  try {
    const request = ChannelInitInputSchema.parse(input);
    const channelDir = assertDirectoryExists(deps.channelDir);
    const plan = planActions(channelDir, request);
    preflightPlan(plan, channelDir);
    applyPlan(plan);

    return Promise.resolve(
      ok(
        ChannelInitOutputSchema.parse({
          diff: collectDiffs(plan),
          directories: plan.directories.map((action) => ({
            kind: action.kind,
            rel: action.rel,
          })),
          files: plan.files.map((action) => ({
            kind: action.kind,
            rel: action.rel,
          })),
          summary: formatSummary(plan),
        })
      )
    );
  } catch (error) {
    return Promise.resolve(err(toServiceError(error)));
  }
};
