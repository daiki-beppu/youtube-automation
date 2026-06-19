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
    const service = createService(Input, Output, (input) => ({
      greeting: `hello ${input.name}`,
    }));

    const result = await service({ name: "metadata" }, {});

    expect(result).toEqual({ ok: true, value: { greeting: "hello metadata" } });
  });

  test("maps input validation failures to ServiceError", async () => {
    const service = createService(Input, Output, (input) => ({
      greeting: `hello ${input.name}`,
    }));

    const result = await service(
      { name: 123 } as unknown as z.input<typeof Input>,
      {}
    );

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected validation failure");
    }
    expect(result.error.domain).toBe("validation");
  });

  test("maps output validation failures to ServiceError", async () => {
    const service = createService(
      Input,
      Output,
      () =>
        ({ extra: true, greeting: "hello" }) as unknown as z.output<
          typeof Output
        >
    );

    const result = await service({ name: "metadata" }, {});

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected validation failure");
    }
    expect(result.error.domain).toBe("validation");
  });
});
