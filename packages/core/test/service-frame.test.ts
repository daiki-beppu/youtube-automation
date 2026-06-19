import { describe, expect, test } from "bun:test";

import { z } from "zod";

import { createService } from "../src/service-frame.ts";

describe("createService", () => {
  const Input = z
    .object({
      name: z.string(),
    })
    .strict();

  const Output = z
    .object({
      greeting: z.string(),
    })
    .strict();

  test("parses input and output across the service boundary", async () => {
    const service = createService(Input, Output, (input) =>
      Promise.resolve({
        greeting: `hello ${input.name}`,
      })
    );

    const result = await service({ name: "metadata" });

    expect(result).toEqual({ ok: true, value: { greeting: "hello metadata" } });
  });

  test("maps input validation failures to ServiceError", async () => {
    const service = createService(Input, Output, (input) =>
      Promise.resolve({
        greeting: `hello ${input.name}`,
      })
    );

    const result = await service({ name: 123 } as unknown as z.input<
      typeof Input
    >);

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected validation failure");
    }
    expect(result.error.domain).toBe("validation");
  });

  test("maps output validation failures to ServiceError", async () => {
    const service = createService(Input, Output, () =>
      Promise.resolve({ extra: true, greeting: "hello" } as unknown as z.input<
        typeof Output
      >)
    );

    const result = await service({ name: "metadata" });

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected validation failure");
    }
    expect(result.error.domain).toBe("validation");
  });

  test("maps handler throws to ServiceError instead of throwing", async () => {
    const service = createService(Input, Output, () =>
      Promise.reject(new Error("config: broken"))
    );

    const result = await service({ name: "metadata" });

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected handler failure");
    }
    expect(result.error.domain).toBe("config");
    expect(result.error.message).toBe("config: broken");
  });

  test("passes an empty deps object when deps are omitted", async () => {
    let observedDeps: Record<string, never> | undefined;
    const service = createService(Input, Output, (input, deps) => {
      observedDeps = deps;
      return Promise.resolve({
        greeting: `hello ${input.name}`,
      });
    });

    const result = await service({ name: "metadata" });

    expect(result.ok).toBe(true);
    expect(observedDeps).toEqual({});
  });
});
