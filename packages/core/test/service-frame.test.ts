import { describe, expect, test } from "bun:test";

import { createService } from "@youtube-automation/core/service-frame";
import { z } from "zod";

const InputSchema = z
  .object({
    value: z.number(),
  })
  .strict();

const OutputSchema = z
  .object({
    doubled: z.number(),
  })
  .strict();

describe("createService", () => {
  test("returns validation error when input parsing fails and does not call execute", async () => {
    let executeCalls = 0;
    const service = createService(InputSchema, OutputSchema, (input) => {
      executeCalls++;
      return Promise.resolve({
        doubled: input.value * 2,
      });
    });

    const result = await service({
      value: "not-a-number",
    } as unknown as Parameters<typeof service>[0]);

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("validation");
    }
    expect(executeCalls).toBe(0);
  });

  test("returns io error when the core function throws an unprefixed error", async () => {
    const service = createService(InputSchema, OutputSchema, () =>
      Promise.reject(new Error("disk failed"))
    );

    const result = await service({ value: 1 });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("io");
      expect(result.error.message).toBe("disk failed");
    }
  });

  test("returns ok with parsed output when validation and core execution succeed", async () => {
    const service = createService(InputSchema, OutputSchema, (input) =>
      Promise.resolve({
        doubled: input.value * 2,
      })
    );

    const result = await service({ value: 21 });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value).toEqual({ doubled: 42 });
    }
  });

  test("passes an empty deps object when deps are omitted", async () => {
    let observedDeps: Record<string, never> | undefined;
    const service = createService(InputSchema, OutputSchema, (input, deps) => {
      observedDeps = deps;
      return Promise.resolve({
        doubled: input.value * 2,
      });
    });

    const result = await service({ value: 3 });

    expect(result.ok).toBe(true);
    expect(observedDeps).toEqual({});
  });

  test("returns validation error when output parsing fails", async () => {
    const service = createService(InputSchema, OutputSchema, () =>
      Promise.resolve({
        doubled: "not-a-number",
      } as unknown as z.input<typeof OutputSchema>)
    );

    const result = await service({ value: 1 });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("validation");
    }
  });
});
