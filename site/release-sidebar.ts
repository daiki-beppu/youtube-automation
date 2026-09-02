import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { z } from "zod";
import { groupReleasesByScale, releaseScaleLabels } from "./release-scale.ts";
import { releaseFrontmatter } from "./release-schema.ts";

export interface ReleaseSidebarGroup {
  readonly items: readonly string[];
  readonly label: string;
}

const releaseSchema = z.object(releaseFrontmatter);

type ReleaseKind = z.infer<typeof releaseSchema>["kind"];

const releaseKindLabels: Record<ReleaseKind, string> = {
  main: "本体",
  extension: "Chrome 拡張",
};
const releaseKinds: readonly ReleaseKind[] = ["main", "extension"];
const frontmatterBlock = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/u;
const topLevelScalar = /^(?<key>[A-Za-z_][\w-]*):[^\S\r\n]+(?<value>\S.*)$/u;

/**
 * ネストしたキー（`sidebar.order`）を持たない frontmatter 前提で、
 * 依存を増やさずに release 判定へ必要なスカラーだけを取り出す。
 */
const parseFrontmatter = (source: string, path: string): Record<string, string> => {
  const block = frontmatterBlock.exec(source);
  if (block === null) {
    throw new Error(`Release note has no frontmatter: ${path}`);
  }

  return Object.fromEntries(
    block[1]
      .split(/\r?\n/u)
      .map((line) => topLevelScalar.exec(line))
      .filter((match) => match !== null)
      .map((match) => [match.groups.key, match.groups.value.replace(/^"(.*)"$/u, "$1")])
  );
};

const readRelease = (directory: string, file: string) => {
  const path = join(directory, file);
  const release = releaseSchema.parse(parseFrontmatter(readFileSync(path, "utf8"), path));
  const expectedVersion = file.replace(/\.md$/u, "");
  if (release.version !== expectedVersion) {
    throw new Error(
      `Release note version does not match its filename: ${path} declares ${release.version}`
    );
  }

  return release;
};

/**
 * `docs/release-notes/` の実ファイルから blume の sidebar 節を導出する。
 * リリースごとに config を手で足す運用は追加漏れで drift するため（#4726）。
 */
export function releaseSidebarGroups(directory: string): ReleaseSidebarGroup[] {
  const releases = readdirSync(directory)
    .filter((file) => file.endsWith(".md"))
    .map((file) => readRelease(directory, file));

  return releaseKinds.flatMap((kind) =>
    groupReleasesByScale(releases.filter((release) => release.kind === kind)).map(
      (group) => ({
        items: group.releases.map((release) => `/${release.version}`),
        label: `${releaseKindLabels[kind]}｜${releaseScaleLabels[group.scale]}`,
      })
    )
  );
}
