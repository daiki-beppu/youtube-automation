import { z } from "zod";

// ADR-0003 §3: 内部 throw class は payload を持つ 3 個 (下記) のみ存続する。
// payload を持たない config / auth / validation / upload / generator 系の
// 5 名前タグ class は廃止し、plain Error + prefix convention ("config:" 等) に置き換える。

/** core 内部例外の基底。MCP serialization には乗せず、境界で toServiceError を通す。 */
export class AutomationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AutomationError";
  }
}

/** YouTube Data/Analytics API 由来の失敗。HTTP status と reason を payload で運ぶ。 */
export class YouTubeAPIError extends AutomationError {
  readonly statusCode?: number;
  readonly reason?: string;
  readonly context?: Record<string, unknown>;

  constructor(
    message: string,
    payload?: { statusCode?: number; reason?: string; context?: Record<string, unknown> },
  ) {
    super(message);
    this.name = "YouTubeAPIError";
    this.statusCode = payload?.statusCode;
    this.reason = payload?.reason;
    this.context = payload?.context;
  }
}

/** quota 超過 (HTTP 429)。retryAfterSeconds を payload に持ち retry semantic を型に乗せる。 */
export class QuotaExhaustedError extends YouTubeAPIError {
  readonly retryAfterSeconds?: number;

  constructor(
    message: string,
    payload?: { retryAfterSeconds?: number; reason?: string; context?: Record<string, unknown> },
  ) {
    super(message, { statusCode: 429, reason: payload?.reason, context: payload?.context });
    this.name = "QuotaExhaustedError";
    this.retryAfterSeconds = payload?.retryAfterSeconds;
  }
}

// ADR-0003 §2: ServiceError は domain を discriminator とする zod discriminated union。
// MCP の JSON-RPC error として JSON.stringify(r.error) で直接 serialize 可能。
export const ServiceError = z.discriminatedUnion("domain", [
  z.object({
    domain: z.literal("quota"),
    message: z.string(),
    retryAfterSeconds: z.number().optional(),
    httpStatus: z.literal(429),
  }),
  z.object({
    domain: z.literal("api"),
    message: z.string(),
    httpStatus: z.number(),
    reason: z.string().optional(),
  }),
  z.object({ domain: z.literal("auth"), message: z.string() }),
  z.object({ domain: z.literal("config"), message: z.string(), path: z.string().optional() }),
  z.object({ domain: z.literal("validation"), message: z.string(), field: z.string().optional() }),
  z.object({ domain: z.literal("io"), message: z.string(), path: z.string().optional() }),
]);
export type ServiceError = z.infer<typeof ServiceError>;

// ADR-0003 §3: service 境界の唯一の例外 → ServiceError 変換口。
// instanceof で payload 系を精密判定し、残りは message prefix convention で domain を決める。
// instanceof の判定順序が契約: QuotaExhaustedError は YouTubeAPIError の派生なので必ず先に判定する。
export function toServiceError(e: unknown): ServiceError {
  if (e instanceof QuotaExhaustedError) {
    return {
      domain: "quota",
      retryAfterSeconds: e.retryAfterSeconds,
      httpStatus: 429,
      message: e.message,
    };
  }
  if (e instanceof YouTubeAPIError) {
    // statusCode は payload 任意 (ADR-0003 §3): 不明な API 失敗は 500 (server error) に寄せる。
    return { domain: "api", httpStatus: e.statusCode ?? 500, reason: e.reason, message: e.message };
  }
  if (e instanceof z.ZodError) {
    // path は PropertyKey[]（symbol を含みうる）。素の join(".") は symbol 要素で
    // TypeError を throw し、全域変換境界（ADR-0003 §3）の totality 契約を破る。
    // map(String) で明示変換し、symbol path でも throw せず validation domain に落とす。
    return { domain: "validation", message: e.message, field: e.issues[0]?.path.map(String).join(".") };
  }
  const message = e instanceof Error ? e.message : String(e);
  if (message.startsWith("config:")) return { domain: "config", message };
  if (message.startsWith("auth:")) return { domain: "auth", message };
  return { domain: "io", message };
}
