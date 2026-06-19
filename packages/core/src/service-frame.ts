import type { z } from "zod";

import { toServiceError } from "./errors.ts";
import type { ServiceError } from "./errors.ts";
import { err, ok } from "./result.ts";
import type { Result } from "./result.ts";

type EmptyDeps = Record<string, never>;
type ServiceResult<O extends z.ZodType> = Promise<
  Result<z.output<O>, ServiceError>
>;

const resolveDeps = <D>(deps: D | undefined, defaultDeps: D | undefined): D => {
  if (deps !== undefined) {
    return deps;
  }
  if (defaultDeps !== undefined) {
    return defaultDeps;
  }
  return {} as D;
};

export function createService<I extends z.ZodType, O extends z.ZodType>(
  inputSchema: I,
  outputSchema: O,
  execute: (input: z.output<I>, deps: EmptyDeps) => Promise<z.input<O>>
): (input: z.input<I>, deps?: EmptyDeps) => ServiceResult<O>;
export function createService<I extends z.ZodType, O extends z.ZodType, D>(
  inputSchema: I,
  outputSchema: O,
  execute: (input: z.output<I>, deps: D) => Promise<z.input<O>>
): (input: z.input<I>, deps: D) => ServiceResult<O>;
export function createService<I extends z.ZodType, O extends z.ZodType, D>(
  inputSchema: I,
  outputSchema: O,
  execute: (input: z.output<I>, deps: D) => Promise<z.input<O>>,
  defaultDeps: D
): (input: z.input<I>, deps?: D) => ServiceResult<O>;
export function createService<I extends z.ZodType, O extends z.ZodType, D>(
  inputSchema: I,
  outputSchema: O,
  execute: (input: z.output<I>, deps: D) => Promise<z.input<O>>,
  defaultDeps?: D
) {
  return async (input: z.input<I>, deps?: D): ServiceResult<O> => {
    try {
      const parsed = inputSchema.parse(input);
      const resolvedDeps = resolveDeps(deps, defaultDeps);
      const raw = await execute(parsed, resolvedDeps);
      return ok(outputSchema.parse(raw));
    } catch (error) {
      return err(toServiceError(error));
    }
  };
}
