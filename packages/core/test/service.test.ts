import { describe, expect, test } from "bun:test";

import { z } from "zod";

import { createService } from "../src/service.ts";

const Input = z.object({ name: z.string().min(1) }).strict();
const Output = z.object({ greeting: z.string() }).strict();

describe("createService", () => {
  test("parses input and output around the handler", async () => {
    const service = createService(Input, Output, (request) => ({
      greeting: `hello ${request.name}`,
    }));

    const result = await service({ name: "world" }, {});

    expect(result).toEqual({
      ok: true,
      value: { greeting: "hello world" },
    });
  });

  test("returns validation ServiceError before running the handler", async () => {
    let calls = 0;
    const service = createService(Input, Output, (request) => {
      calls += 1;
      return { greeting: `hello ${request.name}` };
    });

    const result = await service({ name: "" }, {});

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected validation failure");
    }
    expect(result.error.domain).toBe("validation");
    expect(calls).toBe(0);
  });

  test("maps handler failures to ServiceError", async () => {
    const service = createService(Input, Output, () => {
      throw new Error("config: missing setting");
    });

    const result = await service({ name: "world" }, {});

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected config failure");
    }
    expect(result.error.domain).toBe("config");
  });
});
