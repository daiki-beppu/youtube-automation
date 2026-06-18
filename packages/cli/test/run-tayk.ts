import { join, resolve } from "node:path";

const repoRoot = resolve(import.meta.dir, "..", "..", "..");

const taykBin = join(repoRoot, "packages", "cli", "bin", "tayk.ts");
const DEFAULT_TIMEOUT_MS = 60_000;

interface RunTaykOptions {
  cwd?: string;
  env?: Record<string, string | undefined>;
  timeoutMs?: number;
}

const resolveEnv = (
  overrides: Record<string, string | undefined> | undefined
): Record<string, string> | undefined => {
  if (overrides === undefined) {
    return undefined;
  }

  const env: Record<string, string> = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (value !== undefined) {
      env[key] = value;
    }
  }
  for (const [key, value] of Object.entries(overrides)) {
    if (value === undefined) {
      Reflect.deleteProperty(env, key);
    } else {
      env[key] = value;
    }
  }
  return env;
};

export const runTayk = (options: RunTaykOptions, ...argv: string[]) => {
  const proc = Bun.spawnSync(["bun", taykBin, ...argv], {
    cwd: options.cwd ?? repoRoot,
    env: resolveEnv(options.env),
    timeout: options.timeoutMs ?? DEFAULT_TIMEOUT_MS,
  });

  if (proc.exitCode === null) {
    throw new Error(
      [
        `tayk subprocess timed out after ${options.timeoutMs ?? DEFAULT_TIMEOUT_MS}ms`,
        `argv: tayk ${argv.join(" ")}`,
        `cwd: ${options.cwd ?? repoRoot}`,
        `stdout:\n${proc.stdout.toString()}`,
        `stderr:\n${proc.stderr.toString()}`,
      ].join("\n")
    );
  }

  return proc;
};

export const expectExitCode = (
  proc: ReturnType<typeof runTayk>,
  expected: number
): void => {
  if (proc.exitCode !== expected) {
    throw new Error(
      [
        `expected exit ${expected}, got ${String(proc.exitCode)}`,
        `stdout:\n${proc.stdout.toString()}`,
        `stderr:\n${proc.stderr.toString()}`,
      ].join("\n")
    );
  }
};

export const expectNonZeroExit = (proc: ReturnType<typeof runTayk>): void => {
  if (proc.exitCode === 0) {
    throw new Error(
      [
        "expected non-zero exit, got 0",
        `stdout:\n${proc.stdout.toString()}`,
        `stderr:\n${proc.stderr.toString()}`,
      ].join("\n")
    );
  }
};
