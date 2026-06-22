import { describe, expect, test } from "bun:test";

import { err, ok } from "@youtube-automation/core";
import type { ServiceError } from "@youtube-automation/core";

import { createEmitResult } from "../lib/run-command.ts";

const makeEmitHarness = () => {
  const exitCodes: number[] = [];
  const stderr: string[] = [];
  const stdout: string[] = [];
  const emitResult = createEmitResult({
    exit: (code: number) => {
      exitCodes.push(code);
      throw new Error(`exit ${code}`);
    },
    writeStderr: (message: string) => {
      stderr.push(message);
    },
    writeStdout: (message: string) => {
      stdout.push(message);
    },
  });

  return { emitResult, exitCodes, stderr, stdout };
};

describe("emitResult — CLI terminal contract", () => {
  test("writes config errors to stderr with exit 1 and no stdout", () => {
    const { emitResult, exitCodes, stderr, stdout } = makeEmitHarness();
    const error = {
      domain: "config",
      message: "CHANNEL_DIR is required",
    } satisfies ServiceError;

    expect(() =>
      emitResult(err(error), {
        json: false,
        renderText: () => "unused",
      })
    ).toThrow("exit 1");

    expect(exitCodes).toEqual([1]);
    expect(stderr).toEqual(["[config] CHANNEL_DIR is required\n"]);
    expect(stderr.join("")).not.toContain("Error:");
    expect(stdout).toEqual([]);
  });

  test("writes io errors to stderr with exit 1 and no stdout", () => {
    const { emitResult, exitCodes, stderr, stdout } = makeEmitHarness();
    const error = {
      domain: "io",
      message: "skills directory not found",
    } satisfies ServiceError;

    expect(() =>
      emitResult(err(error), {
        json: false,
        renderText: () => "unused",
      })
    ).toThrow("exit 1");

    expect(exitCodes).toEqual([1]);
    expect(stderr).toEqual(["[io] skills directory not found\n"]);
    expect(stdout).toEqual([]);
  });

  test("maps quota errors to exit 75", () => {
    const { emitResult, exitCodes, stderr, stdout } = makeEmitHarness();
    const error = {
      domain: "quota",
      httpStatus: 429,
      message: "quota exceeded",
    } satisfies ServiceError;

    expect(() =>
      emitResult(err(error), {
        json: false,
        renderText: () => "unused",
      })
    ).toThrow("exit 75");

    expect(exitCodes).toEqual([75]);
    expect(stderr).toEqual(["[quota] quota exceeded\n"]);
    expect(stdout).toEqual([]);
  });

  test("writes successful JSON output to stdout only", () => {
    const { emitResult, exitCodes, stderr, stdout } = makeEmitHarness();

    emitResult(ok({ path: "/tmp/result" }), {
      json: true,
      renderText: () => "unused",
    });

    expect(exitCodes).toEqual([]);
    expect(stderr).toEqual([]);
    expect(stdout).toEqual(['{"path":"/tmp/result"}\n']);
  });

  test("writes successful text output via renderText when json is false", () => {
    const { emitResult, exitCodes, stderr, stdout } = makeEmitHarness();

    emitResult(ok({ count: 3, path: "/tmp/result" }), {
      json: false,
      renderText: (value) => `Synced ${value.count} files to ${value.path}`,
    });

    expect(exitCodes).toEqual([]);
    expect(stderr).toEqual([]);
    expect(stdout).toEqual(["Synced 3 files to /tmp/result\n"]);
  });
});
