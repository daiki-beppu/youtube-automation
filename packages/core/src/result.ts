// service 戻り値の唯一の成功/失敗表現 (ADR-0003 §1)。
// neverthrow / fp-ts を採用せず custom 20 LOC とする: JSON serialize が自然で、
// 依存ゼロ、将来 method API が要れば後付けできる。
export type Result<T, E> = { ok: true; value: T } | { ok: false; error: E };

export const ok = <T>(value: T): Result<T, never> => ({ ok: true, value });
export const err = <E>(error: E): Result<never, E> => ({ ok: false, error });
