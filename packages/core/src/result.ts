// Discriminated-union result type (ADR-0003 §1). External-dependency-free so
// every layer (core / CLI / MCP) can serialize it as plain JSON. `ok` is the
// single discriminant — narrowing on it picks the populated arm.
export type Result<T, E> = { ok: true; value: T } | { ok: false; error: E };

export const ok = <T>(value: T): Result<T, never> => ({ ok: true, value });
export const err = <E>(error: E): Result<never, E> => ({ error, ok: false });
