import type { z } from "zod";

import { toServiceError } from "./errors.ts";
import type { ServiceError } from "./errors.ts";
import { err, ok } from "./result.ts";
import type { Result } from "./result.ts";

type ServiceHandler<I extends z.ZodType, O extends z.ZodType, D> = (
  input: z.output<I>,
  deps: D
) => Promise<z.input<O>>;

type EmptyDeps = Record<string, never>;
type ServiceResult<O extends z.ZodType> = Promise<
  Result<z.output<O>, ServiceError>
>;

export function createService<I extends z.ZodType, O extends z.ZodType>(
  inputSchema: I,
  outputSchema: O,
  handler: ServiceHandler<I, O, EmptyDeps>
): (input: z.input<I>, deps?: EmptyDeps) => ServiceResult<O>;
export function createService<I extends z.ZodType, O extends z.ZodType, D>(
  inputSchema: I,
  outputSchema: O,
  handler: ServiceHandler<I, O, D>
): (input: z.input<I>, deps: D) => ServiceResult<O>;
export function createService<I extends z.ZodType, O extends z.ZodType, D>(
  inputSchema: I,
  outputSchema: O,
  handler: ServiceHandler<I, O, D>
) {
  return async (input: z.input<I>, deps?: D): ServiceResult<O> => {
    try {
      const parsedInput = inputSchema.parse(input);
      const resolvedDeps = deps === undefined ? ({} as D) : deps;
      const output = await handler(parsedInput, resolvedDeps);
      return ok(outputSchema.parse(output));
    } catch (error) {
      return err(toServiceError(error));
    }
  };
}
