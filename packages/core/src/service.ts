import type { z } from "zod";

import { toServiceError } from "./errors.ts";
import type { ServiceError } from "./errors.ts";
import { err, ok } from "./result.ts";
import type { Result } from "./result.ts";

type ServiceDeps<D> = [D] extends [undefined] ? [] : [deps: D];

type ServiceHandler<I extends z.ZodType, D> = (
  request: z.output<I>,
  ...deps: ServiceDeps<D>
) => Promise<unknown> | unknown;

export const createService =
  <I extends z.ZodType, O extends z.ZodType, D = undefined>(
    inputSchema: I,
    outputSchema: O,
    handler: ServiceHandler<I, D>
  ) =>
  async (
    input: z.input<I>,
    ...deps: ServiceDeps<D>
  ): Promise<Result<z.output<O>, ServiceError>> => {
    try {
      const request = inputSchema.parse(input);
      const output = await handler(request, ...deps);
      return ok(outputSchema.parse(output));
    } catch (error) {
      return err(toServiceError(error));
    }
  };
