import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import {
  existsSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

interface PackageJson {
  bin?: Record<string, string>;
  dependencies?: Record<string, string>;
  devDependencies?: Record<string, string>;
  files?: string[];
  name?: string;
  optionalDependencies?: Record<string, string>;
  private?: boolean;
  scripts?: Record<string, string>;
  workspaces?: string[];
}

const repoRoot = resolve(import.meta.dir, "..", "..", "..");
const cliDir = resolve(repoRoot, "packages", "cli");
const coreDir = resolve(repoRoot, "packages", "core");
const workflowPath = resolve(
  repoRoot,
  ".github",
  "workflows",
  "npm-publish-alpha.yml"
);
const automationReleaseDir = resolve(
  repoRoot,
  ".claude",
  "skills",
  "automation-release"
);
const automationReleaseSkillPath = resolve(automationReleaseDir, "SKILL.md");
const automationReleasePrepareChecklistPath = resolve(
  automationReleaseDir,
  "references",
  "prepare-checklist.md"
);
const automationReleasePublishChecklistPath = resolve(
  automationReleaseDir,
  "references",
  "publish-checklist.md"
);
const NPM_TOKEN_ENV_LINE = [
  "NODE_AUTH_TOKEN: $",
  "{{ secrets.NPM_TOKEN }}",
].join("");
const NPM_WORKFLOW_DISPATCH_LINE = [
  'gh workflow run npm-publish-alpha.yml --ref main -f version="$',
  '{VER}"',
].join("");
const NPM_WORKFLOW_RUN_NAME_LINE = [
  "run-name: Publish tayk@$",
  "{{ inputs.version }}",
].join("");
const NPM_RUN_TITLE_FILTER = [
  '.displayTitle == \\"Publish tayk@$',
  '{VER}\\"',
].join("");
const NPM_RUN_CREATED_AT_FILTER = [
  'createdAt >= \\"$',
  '{dispatch_start}\\"',
].join("");
const NPM_VERSION_VIEW_LINE = ['npm view "tayk@$', '{VER}" version'].join("");
const UNPUBLISHED_ALPHA_RESUME_TEXT = [
  "`tayk@$",
  "{VER}` が npm alpha として未 publish",
].join("");
const RELEASE_COMMIT_FLAG_LINE = "main_head_is_release_commit=false";
const VERSION_TAG_FLAG_LINE = "tag_exists_for_ver=false";
const TAG_POINTS_TO_MAIN_FLAG_LINE = "tag_points_to_main=false";
const ANY_OPEN_RELEASE_BRANCH_LINE = [
  'any_open_release_branch=$(git ls-remote --heads origin "release/v*"',
].join("");
const VERSION_OPEN_RELEASE_BRANCH_LINE = [
  'open_release_branch_for_ver=$(git ls-remote --heads origin "release/v$',
  '{VER}"',
].join("");
const MERGED_RELEASE_PR_FALLBACK_LINE = [
  'elif [ "$',
  '{release_pr_merge_sha}" = "$',
  '{main_sha}" ]; then',
].join("");
const RELEASE_PR_MERGE_SHA_LINE = [
  "release_pr_merge_sha=$(gh pr list --state merged --search ",
  '"chore(release): v$',
  '{VER}" --json mergeCommit',
].join("");
const VERSION_TAG_REMOTE_CHECK = [
  'git ls-remote --tags origin "v$',
  '{VER}" | grep -q "refs/tags/v$',
  '{VER}$"',
].join("");
const GITHUB_RELEASE_EXISTS_FLAG_LINE = "github_release_exists=false";
const GITHUB_RELEASE_VIEW_LINE = ['gh release view "v$', '{VER}"'].join("");
const TAG_EXISTS_BRANCH_LINE = [
  'if [ "$',
  '{tag_exists}" = "true" ]; then',
].join("");
const CREATE_TAG_LINE = ['git tag "v$', '{VER}"'].join("");
const SKIP_EXISTING_TAG_LINE = [
  'echo "Tag v$',
  '{VER} already exists. Skipping tag push."',
].join("");
const PUBLISH_RESUME_RULE =
  "| **publish resume** | `main_head_is_release_commit == true` かつ `tag_points_to_main == true` かつ `github_release_exists == true` かつ `npm_alpha_published == false`";
const PUBLISH_RELEASE_RESUME_RULE =
  "| **publish release resume** | `main_head_is_release_commit == true` かつ `tag_points_to_main == true` かつ `github_release_exists == false`";
const NO_OP_RULE =
  "| **no-op** | `main_head_is_release_commit == true` かつ `tag_points_to_main == true` かつ `github_release_exists == true` かつ `npm_alpha_published == true`";
const PUBLISH_RULE =
  "| **publish** | `main_head_is_release_commit == true` かつ `tag_exists_for_ver == false` かつ `any_open_release_branch` 無し";
const PREPARE_RULE =
  "| **prepare** | `main_head_is_release_commit == false` かつ `any_open_release_branch` 無し";
const TAG_MISMATCH_ABORT_RULE =
  "| **abort** | `main_head_is_release_commit == true` かつ `tag_exists_for_ver == true` かつ `tag_points_to_main == false`";
const ADVANCED_MAIN_ABORT_RULE =
  "| **abort** | `release_pr_merged == true` かつ `main_head_is_release_commit == false` かつ `tag_exists_for_ver == false`";
const MAIN_SHA_HEAD_LINE = "main_sha=$(git rev-parse HEAD)";
const MAIN_RELEASE_COMMIT_FLAG_LINE = "main_is_release_commit=false";
const MAIN_RELEASE_COMMIT_ERROR = [
  'echo "ERROR: main HEAD $',
  "{main_sha} is not the release commit for v$",
  '{VER}"',
].join("");
const TAG_SHA_LINE = ['tag_sha=$(git rev-parse "v$', '{VER}^{commit}"'].join(
  ""
);
const TAG_MISMATCH_IF_LINE = [
  'if [ "$',
  '{tag_sha}" != "$',
  '{main_sha}" ]; then',
].join("");
const TAG_MISMATCH_PHASE2_ERROR = [
  'echo "ERROR: existing tag v$',
  "{VER} points to $",
  "{tag_sha}, not main HEAD $",
  '{main_sha}"',
].join("");

const tmpDirs: string[] = [];

const readJson = <T>(path: string): T =>
  JSON.parse(readFileSync(path, "utf-8")) as T;

const readRootPackage = (): PackageJson =>
  readJson<PackageJson>(join(repoRoot, "package.json"));

const readCliPackage = (): PackageJson =>
  readJson<PackageJson>(join(cliDir, "package.json"));

const readCorePackage = (): PackageJson =>
  readJson<PackageJson>(join(coreDir, "package.json"));

const makeTmp = (prefix: string): string => {
  const dir = realpathSync(mkdtempSync(join(tmpdir(), prefix)));
  tmpDirs.push(dir);
  return dir;
};

const runChecked = (
  command: string[],
  options: { cwd: string; env?: Record<string, string | undefined> }
): Bun.SyncSubprocess<"pipe", "pipe"> => {
  const proc = Bun.spawnSync(command, options);
  if (proc.exitCode !== 0) {
    throw new Error(`${command.join(" ")} failed: ${proc.stderr.toString()}`);
  }
  return proc;
};

const packCli = (destination: string) => {
  runChecked(["bun", "pm", "pack", "--destination", destination, "--quiet"], {
    cwd: cliDir,
  });
  const tarball = readdirSync(destination).find((file) =>
    file.endsWith(".tgz")
  );
  if (tarball === undefined) {
    throw new Error("bun pm pack produced no tarball");
  }
  return join(destination, tarball);
};

const tarEntries = (tarball: string): string[] =>
  runChecked(["tar", "-tzf", tarball], { cwd: repoRoot })
    .stdout.toString()
    .split("\n")
    .filter((line) => line.length > 0);

const readTarJson = <T>(tarball: string, entry: string): T =>
  JSON.parse(
    runChecked(["tar", "-xOf", tarball, entry], {
      cwd: repoRoot,
    }).stdout.toString()
  ) as T;

afterAll(() => {
  Bun.spawnSync(["bun", "run", "scripts/bundle-symlinks.ts", "restore"], {
    cwd: cliDir,
  });
  for (const dir of tmpDirs.splice(0)) {
    rmSync(dir, { force: true, recursive: true });
  }
});

describe("tayk package metadata for npm publish (#968)", () => {
  test("publishes the CLI workspace as the public tayk package", () => {
    const rootPackage = readRootPackage();
    const cliPackage = readCliPackage();
    const corePackage = readCorePackage();

    expect(rootPackage.name).toBe("tayk");
    expect(rootPackage.private).toBe(true);
    expect(rootPackage.workspaces).toEqual(["packages/*"]);
    expect(cliPackage.name).toBe("tayk");
    expect(cliPackage.private).toBeUndefined();
    expect(corePackage.name).toBe("@tayk/core");
    expect(corePackage.private).toBe(true);
  });

  test("exposes only the bundled bun entrypoint as the tayk bin", () => {
    const cliPackage = readCliPackage();

    expect(cliPackage.bin).toEqual({ tayk: "./dist/cli.js" });
    expect(cliPackage.files).toEqual(["dist", "_skills", "_claude_md"]);
  });

  test("builds the bundle before materializing package assets for pack", () => {
    const cliPackage = readCliPackage();

    expect(cliPackage.scripts?.prepack).toBe(
      "bun run build && bun run scripts/bundle-symlinks.ts materialize"
    );
    expect(cliPackage.scripts?.postpack).toBe(
      "bun run scripts/bundle-symlinks.ts restore"
    );
  });

  test("keeps sharp as the only external runtime dependency", () => {
    const cliPackage = readCliPackage();
    const build = cliPackage.scripts?.build;

    expect(typeof build).toBe("string");
    expect(build).toContain("bun build ./bin/tayk.ts");
    expect(build).toContain("--outfile=dist/cli.js");
    expect(build).toContain("--external sharp");
    expect(build).toContain("--banner");
    expect(build).toContain("#!/usr/bin/env bun");
    expect(cliPackage.optionalDependencies?.sharp).toBe("^0.34.0");
    expect(cliPackage.dependencies).toBeUndefined();
    expect(cliPackage.devDependencies?.citty).toBe("^0.2.2");
  });

  test("keeps bun.lock root metadata aligned with the rebranded package", () => {
    const lockfile = readFileSync(join(repoRoot, "bun.lock"), "utf-8");

    expect(lockfile).toContain('"": {\n      "name": "tayk"');
    expect(lockfile).toContain(
      '"packages/cli": {\n      "name": "tayk",\n      "version": "0.1.0-alpha.0"'
    );
  });
});

describe("tayk package tarball contract (#968)", () => {
  let entries: string[] = [];
  let packedPackage: PackageJson;
  let tarballPath: string;

  beforeAll(() => {
    tarballPath = packCli(makeTmp("tayk-pack-"));
    entries = tarEntries(tarballPath);
    packedPackage = readTarJson<PackageJson>(
      tarballPath,
      "package/package.json"
    );
  });

  test("ships the generated dist cli and omits TypeScript source entrypoints", () => {
    expect(entries).toContain("package/dist/cli.js");
    expect(entries.some((entry) => entry.startsWith("package/src/"))).toBe(
      false
    );
    expect(entries.some((entry) => entry.startsWith("package/lib/"))).toBe(
      false
    );
    expect(entries).not.toContain("package/bin/tayk.ts");
  });

  test("published package.json has no bundled JS runtime dependency", () => {
    expect(packedPackage.name).toBe("tayk");
    expect(packedPackage.private).toBeUndefined();
    expect(packedPackage.bin).toEqual({ tayk: "./dist/cli.js" });
    expect(packedPackage.optionalDependencies?.sharp).toBe("^0.34.0");
    expect(packedPackage.dependencies).toBeUndefined();
    expect(packedPackage.devDependencies?.citty).toBe("^0.2.2");
    expect(JSON.stringify(packedPackage)).not.toContain("workspace:*");
  });

  test("runs bunx tayk --help after installing the packed package in a clean downstream project", () => {
    const downstreamDir = makeTmp("tayk-downstream-");
    const bunTmpDir = makeTmp("tayk-bun-tmp-");
    writeFileSync(
      join(downstreamDir, "package.json"),
      JSON.stringify({ devDependencies: { tayk: tarballPath }, private: true })
    );

    const env = { ...Bun.env, TMPDIR: bunTmpDir };
    runChecked(
      ["bun", "install", "--cwd", downstreamDir, "--cache-dir", bunTmpDir],
      { cwd: repoRoot, env }
    );
    const proc = runChecked(["bunx", "tayk", "--help"], {
      cwd: downstreamDir,
      env,
    });
    expect(proc.stdout.toString()).toContain("skills");
  });
});

describe("built tayk CLI smoke (#968)", () => {
  beforeAll(() => {
    runChecked(["bun", "run", "build"], { cwd: cliDir });
  });

  test("dist/cli.js has a bun shebang and prints help", () => {
    const distCli = join(cliDir, "dist", "cli.js");

    expect(
      readFileSync(distCli, "utf-8").startsWith("#!/usr/bin/env bun")
    ).toBe(true);
    const proc = runChecked(["bun", distCli, "--help"], { cwd: repoRoot });
    expect(proc.stdout.toString()).toContain("skills");
  });

  test("dist/cli.js reads bundled skills assets in json mode", () => {
    const distCli = join(cliDir, "dist", "cli.js");

    const proc = runChecked(["bun", distCli, "skills", "list", "--json"], {
      cwd: repoRoot,
    });
    const parsed = JSON.parse(proc.stdout.toString()) as {
      skills: string[];
      source: string;
    };
    expect(parsed.source).toContain("_skills");
    expect(parsed.skills.length).toBeGreaterThan(0);
  });
});

describe("npm alpha publish workflow contract (#968)", () => {
  test("uses manual version input with npm provenance and alpha dist-tag", () => {
    expect(existsSync(workflowPath)).toBe(true);
    const workflow = readFileSync(workflowPath, "utf-8");

    expect(workflow).toContain("workflow_dispatch:");
    expect(workflow).toContain(NPM_WORKFLOW_RUN_NAME_LINE);
    expect(workflow).toContain("version:");
    expect(workflow).toContain("id-token: write");
    expect(workflow).toContain("oven-sh/setup-bun@v2");
    expect(workflow).toContain("actions/setup-node@v4");
    expect(workflow).toContain("registry-url: https://registry.npmjs.org");
    expect(workflow).toContain("working-directory: packages/cli");
    expect(workflow).toContain("npm publish --provenance --tag alpha");
    expect(workflow).toContain(NPM_TOKEN_ENV_LINE);
  });

  test("fails before publishing when the requested version does not match the package", () => {
    expect(existsSync(workflowPath)).toBe(true);
    const workflow = readFileSync(workflowPath, "utf-8");

    expect(workflow).toContain("github.event.inputs.version");
    expect(workflow).toContain("packages/cli/package.json");
    expect(workflow).toContain('"version"');
    expect(workflow).toContain("exit 1");
  });
});

describe("automation-release npm publish wiring (#968)", () => {
  test("documents the npm release source of truth and workflow dispatch", () => {
    const skill = readFileSync(automationReleaseSkillPath, "utf-8");

    expect(skill).toContain("packages/cli/package.json::version");
    expect(skill).toContain("bun install --lockfile-only");
    expect(skill).toContain("npm-publish-alpha.yml");
    expect(skill).toContain(NPM_WORKFLOW_DISPATCH_LINE);
    expect(skill).toContain("dispatch_start=$(date -u");
    expect(skill).toContain("--event workflow_dispatch");
    expect(skill).toContain(NPM_RUN_TITLE_FILTER);
    expect(skill).toContain(NPM_RUN_CREATED_AT_FILTER);
    expect(skill).not.toContain("--limit 1 --json databaseId");
    expect(skill).toContain("npm publish --provenance --tag alpha");
    expect(skill).toContain("bunx tayk --help");
    expect(skill).not.toContain("pyproject.toml::version");
    expect(skill).not.toContain("uv.lock");
    expect(skill).not.toContain("git+https");
  });

  test("does not treat a pushed tag as complete until tayk alpha is published", () => {
    const skill = readFileSync(automationReleaseSkillPath, "utf-8");
    const publish = readFileSync(
      automationReleasePublishChecklistPath,
      "utf-8"
    );

    expect(skill).toContain(NPM_VERSION_VIEW_LINE);
    expect(skill).toContain("npm view tayk dist-tags.alpha");
    expect(skill).toContain("npm_alpha_published=false");
    expect(skill).toContain(GITHUB_RELEASE_EXISTS_FLAG_LINE);
    expect(skill).toContain(GITHUB_RELEASE_VIEW_LINE);
    expect(skill).toContain(PUBLISH_RESUME_RULE);
    expect(skill).toContain(PUBLISH_RELEASE_RESUME_RULE);
    expect(skill).toContain(NO_OP_RULE);
    expect(skill).toContain("tag 到達だけで no-op にしない");
    expect(publish).toContain(UNPUBLISHED_ALPHA_RESUME_TEXT);
    expect(publish).toContain(NPM_WORKFLOW_DISPATCH_LINE);
  });

  test("keeps release state detection mutually exclusive for merged release PRs", () => {
    const skill = readFileSync(automationReleaseSkillPath, "utf-8");

    expect(skill).toContain(RELEASE_COMMIT_FLAG_LINE);
    expect(skill).toContain(VERSION_TAG_FLAG_LINE);
    expect(skill).toContain(TAG_POINTS_TO_MAIN_FLAG_LINE);
    expect(skill).toContain(RELEASE_PR_MERGE_SHA_LINE);
    expect(skill).toContain(MERGED_RELEASE_PR_FALLBACK_LINE);
    expect(skill).toContain(VERSION_TAG_REMOTE_CHECK);
    expect(skill).toContain(PUBLISH_RESUME_RULE);
    expect(skill).toContain(PUBLISH_RULE);
    expect(skill).toContain(PREPARE_RULE);
    expect(skill).not.toContain(
      "| **prepare** | `open_release_branch` 無し かつ `main_sha != tag_sha`"
    );
  });

  test("blocks prepare while any release branch is open", () => {
    const skill = readFileSync(automationReleaseSkillPath, "utf-8");

    expect(skill).toContain(ANY_OPEN_RELEASE_BRANCH_LINE);
    expect(skill).toContain(VERSION_OPEN_RELEASE_BRANCH_LINE);
    expect(skill).toContain(PREPARE_RULE);
    expect(skill).toContain(
      "| **abort** | `any_open_release_branch` 有り かつ `release_pr_merged == false`"
    );
    expect(skill).toContain(
      "| **publish (alt)** | `main_head_is_release_commit == true` かつ `tag_exists_for_ver == false` かつ `open_release_branch_for_ver` 有り"
    );
    expect(skill).not.toContain(
      "| **prepare** | `main_head_is_release_commit == false` かつ `open_release_branch` 無し"
    );
  });

  test("aborts when an existing version tag does not point at main", () => {
    const skill = readFileSync(automationReleaseSkillPath, "utf-8");
    const publish = readFileSync(
      automationReleasePublishChecklistPath,
      "utf-8"
    );

    expect(skill).toContain(TAG_MISMATCH_ABORT_RULE);
    expect(skill).toContain(MAIN_SHA_HEAD_LINE);
    expect(skill).toContain(TAG_SHA_LINE);
    expect(skill).toContain(TAG_MISMATCH_IF_LINE);
    expect(skill).toContain(TAG_MISMATCH_PHASE2_ERROR);
    expect(skill).toContain("exit 1");
    expect(publish).toContain(TAG_MISMATCH_PHASE2_ERROR);
  });

  test("does not classify older released tags as publish tag mismatches", () => {
    const skill = readFileSync(automationReleaseSkillPath, "utf-8");

    expect(skill).toContain(TAG_MISMATCH_ABORT_RULE);
    expect(skill).toContain(PREPARE_RULE);
    expect(skill).not.toContain(
      "| **abort** | `tag_exists_for_ver == true` かつ `tag_points_to_main == false`"
    );
  });

  test("refuses publish when main has advanced past the merged release PR", () => {
    const skill = readFileSync(automationReleaseSkillPath, "utf-8");

    expect(skill).toContain(RELEASE_PR_MERGE_SHA_LINE);
    expect(skill).toContain(MERGED_RELEASE_PR_FALLBACK_LINE);
    expect(skill).toContain(ADVANCED_MAIN_ABORT_RULE);
    expect(skill).toContain(MAIN_RELEASE_COMMIT_FLAG_LINE);
    expect(skill).toContain(MAIN_RELEASE_COMMIT_ERROR);
  });

  test("retries GitHub Release creation before npm workflow dispatch", () => {
    const skill = readFileSync(automationReleaseSkillPath, "utf-8");
    const publish = readFileSync(
      automationReleasePublishChecklistPath,
      "utf-8"
    );

    expect(skill).toContain(GITHUB_RELEASE_EXISTS_FLAG_LINE);
    expect(skill).toContain(PUBLISH_RELEASE_RESUME_RULE);
    expect(skill).toContain(PUBLISH_RESUME_RULE);
    expect(skill).toContain(
      "tag は存在するが GitHub Release 未作成の場合は 2-3 を再実行する"
    );
    expect(publish).toContain(
      "GitHub Release が無い → GitHub Release 作成を再実行"
    );
    expect(publish).toContain(
      "GitHub Release が存在するまで npm workflow dispatch へ進まない"
    );
  });

  test("skips local tag creation when resuming an already tagged npm publish", () => {
    const skill = readFileSync(automationReleaseSkillPath, "utf-8");

    const branchIndex = skill.indexOf(TAG_EXISTS_BRANCH_LINE);
    const createTagIndex = skill.indexOf(CREATE_TAG_LINE);

    expect(branchIndex).toBeGreaterThan(-1);
    expect(createTagIndex).toBeGreaterThan(branchIndex);
    expect(skill).toContain(SKIP_EXISTING_TAG_LINE);
  });

  test("keeps automation-release checklists on the npm tayk contract", () => {
    const prepare = readFileSync(
      automationReleasePrepareChecklistPath,
      "utf-8"
    );
    const publish = readFileSync(
      automationReleasePublishChecklistPath,
      "utf-8"
    );

    expect(prepare).toContain("packages/cli/package.json::version");
    expect(prepare).toContain("bun install --lockfile-only");
    expect(prepare).toContain("bunx tayk <cmd>");
    expect(publish).toContain("npm-publish-alpha.yml");
    expect(publish).toContain("npm publish --provenance --tag alpha");
    expect(publish).toContain("bunx tayk --help");
    expect(`${prepare}\n${publish}`).not.toContain("uv.lock");
    expect(`${prepare}\n${publish}`).not.toContain("pyproject.toml::version");
  });
});
