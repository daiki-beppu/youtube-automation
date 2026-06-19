import type { z } from "zod";

import { toServiceError } from "./errors.ts";
import type { ServiceError } from "./errors.ts";
import { err, ok } from "./result.ts";
import type { Result } from "./result.ts";

type ServiceHandler<I extends z.ZodType, O extends z.ZodType, D> = (
  input: z.output<I>,
  deps: D
) => Promise<z.output<O>> | z.output<O>;

export const createService =
  <I extends z.ZodType, O extends z.ZodType, D>(
    inputSchema: I,
    outputSchema: O,
    handler: ServiceHandler<I, O, D>
  ) =>
  async (
    input: z.input<I>,
    deps: D
  ): Promise<Result<z.output<O>, ServiceError>> => {
    try {
      const parsedInput = inputSchema.parse(input);
      const output = await handler(parsedInput, deps);
      return ok(outputSchema.parse(output));
    } catch (error) {
      return err(toServiceError(error));
    }
  };
