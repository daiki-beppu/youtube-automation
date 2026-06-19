# Service-boundary contracts: Result + zod ServiceError + auth seam

## Context

ADR 0002 で `packages/core` の domain feature を schema-first / service-only / thin CLI の三層で書く方針を確定したが、**「service が失敗を caller にどう伝えるか」「重い外部依存 (OAuth / 1Password) との seam をどこに引くか」「schema を 16 個の手書き interface に分解して書くか zod に集約するか」**の 3 点は ADR 0002 では言及していなかった。

S5-S8 自律 loop で 6 child (#732 / #734-#738) を merge した結果、以下の drift が観測された:

- **error 戦略不在**: `errors.ts` に `AutomationError` / `ConfigError` / `YouTubeAPIError` / `QuotaExhaustedError` 等 8 class が並ぶが、retry semantic / HTTP status family / domain area が型に乗っておらず、caller は `instanceof` + `e.statusCode` の ad-hoc 判定を散在させる。MCP は JSON-RPC で error を返すため、class 系統では serialization 不可
- **auth seam の曖昧さ**: Python `oauth_handler.py` は path discovery / 1Password fetch / credentials build / browser flow / token persist / API service factory / connection test を 1 class に同居。TS 側の port (#739 以降) で同形写経すると ADR 0002 の thin client 原則違反 (core が op CLI / fs 操作を抱える)
- **手書き parse pattern の散在**: `config/internal.ts` で `isRecord` を定義しつつ、各 `config/*.ts` (16 file) が `(data.x as T | undefined) ?? default` を手書き再実装。zod 化していないため type と validation が二重管理、ADR 0002 が想定した「schema を MCP の JSON Schema に自動変換」が不可能

これらは規約のない 60+ AFK issue で必ず崩れる。ADR 0002 の "canonical template" を実例レベルまで降ろし、**Phase 2 で書く 8+ service が同一の interface 形状で生まれることを機械担保する**規約が要る。

## Decision

`packages/core` 配下の全 domain service と、auth / secret resolution の seam を以下のシェイプで実装する:

### 1. service 関数は `Promise<Result<T, ServiceError>>` を返す

core 内部関数は throw OK。各 `packages/core/<feature>/service.ts` の export 境界は `createService` で定義し、入力検証・出力検証・`Result` 変換を共通化する。CLI/MCP は `if (!r.ok)` で discriminate する。

```typescript
// packages/core/result.ts (20 LOC、依存ゼロ)
export type Result<T, E> =
  | { ok: true; value: T }
  | { ok: false; error: E };
export const ok = <T>(value: T): Result<T, never> => ({ ok: true, value });
export const err = <E>(error: E): Result<never, E> => ({ ok: false, error });
```

`neverthrow` / `fp-ts` / `effect-ts` を採用しない。custom 20 LOC で十分、JSON serialize 自然、将来 method API が欲しくなったら追加可能。

### 2. `ServiceError` は zod discriminated union

`domain` を discriminator とし、per-domain payload を `z.object()` で型付けする。MCP の JSON-RPC error として直接 serialize 可能。

```typescript
// packages/core/errors.ts
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
```

### 3. 内部 throw class は payload あり 3 個のみ存続

`AutomationError` (base) / `YouTubeAPIError` (statusCode / reason / context payload) / `QuotaExhaustedError extends YouTubeAPIError` (retryAfterSeconds payload) のみ残す。`ConfigError` / `AuthError` / `ValidationError` / `UploadError` / `GeneratorError` の 5 名前タグ class は削除し、plain `Error` + `message.startsWith("config:")` 等の prefix convention に置き換える。

`toServiceError(e: unknown): ServiceError` が `instanceof` で payload 系を精密判定、残りは prefix 判定でフォールバックする。

```typescript
export function toServiceError(e: unknown): ServiceError {
  if (e instanceof QuotaExhaustedError)
    return { domain: "quota", retryAfterSeconds: e.retryAfterSeconds, httpStatus: 429, message: e.message };
  if (e instanceof YouTubeAPIError)
    return { domain: "api", httpStatus: e.statusCode ?? 500, reason: e.reason, message: e.message };
  if (e instanceof z.ZodError)
    return { domain: "validation", message: e.message, field: e.errors[0]?.path.join(".") };
  const m = e instanceof Error ? e.message : String(e);
  if (m.startsWith("config:")) return { domain: "config", message: m };
  if (m.startsWith("auth:")) return { domain: "auth", message: m };
  return { domain: "io", message: m };
}
```

### 4. secret resolution は CLI 層へ

`secrets.ts` (env → 1Password CLI → throw) を `packages/cli/lib/secrets.ts` に移動。core は raw 文字列 (`clientSecretsJson: string`) を受け取り、env / op CLI / file 探索の fallback chain を観測しない。

```typescript
// packages/cli/lib/secrets.ts (thin, op CLI を spawn してよい)
export async function resolveClientSecretsJson(): Promise<string> {
  // 1. CLIENT_SECRETS_JSON env
  // 2. <channel>/auth/client_secrets.json
  // 3. op read SECRET_REFS.CLIENT_SECRETS_JSON
}
```

### 5. OAuth は 2 service に分離 (path-based lint で MCP から interactive を遮断)

`packages/core/oauth/refresh.ts` の `refreshTokenService` は pure (browser 不要、MCP / CLI 両方使用可)、`packages/core/oauth/interactive.ts` の `interactiveAuthService` は内部で browser open + local server を担う (CLI 専用)。oxlint の `no-restricted-imports` で **path-based** に `packages/mcp/**` から `**/oauth/interactive*` を error にする。

```typescript
// packages/core/oauth/refresh.ts
export async function refreshTokenService(input: {
  tokenJson: string;
  clientSecretsJson: string;
}): Promise<Result<{ tokenJson: string }, ServiceError>>;

// packages/core/oauth/interactive.ts (MCP からは import 不可)
export async function interactiveAuthService(input: {
  clientSecretsJson: string;
  scopes: string[];
}): Promise<Result<{ tokenJson: string }, ServiceError>>;
```

### 6. token.json の read/write (0o600 chmod) は CLI 層

secret READ が CLI に移った対称として、token WRITE も CLI が担当。core は文字列を返すだけ、ファイル書き込みは行わない。

```typescript
// packages/cli/lib/oauth.ts
export async function getYouTubeClient(): Promise<youtube_v3.Youtube> {
  const cs = await resolveClientSecretsJson();
  let tokenJson = await readTokenJson(paths.tokenJson());
  if (!tokenJson) {
    const r = await interactiveAuthService({ clientSecretsJson: cs, scopes: SCOPES });
    if (!r.ok) throw r.error;
    tokenJson = r.value.tokenJson;
    await writeTokenJson(paths.tokenJson(), tokenJson); // 0o600
  }
  if (isExpired(tokenJson)) {
    const r = await refreshTokenService({ tokenJson, clientSecretsJson: cs });
    if (!r.ok) throw r.error;
    tokenJson = r.value.tokenJson;
    await writeTokenJson(paths.tokenJson(), tokenJson);
  }
  return buildYouTubeClient(tokenJson);
}
```

### 7. googleapis client は core の pure factory

`buildYouTubeClient(tokenJson) → youtube_v3.Youtube` および `buildYouTubeAnalyticsClient(tokenJson) → youtubeAnalytics_v2.Youtubeanalytics` を `packages/core/oauth/client.ts` に置く。各 domain service は client を `deps` で受け取る。core/oauth と domain service は疎結合。

```typescript
// packages/core/oauth/client.ts
export function buildYouTubeClient(tokenJson: string): youtube_v3.Youtube {
  const oauth2 = new OAuth2Client();
  oauth2.setCredentials(JSON.parse(tokenJson));
  return google.youtube({ version: "v3", auth: oauth2 });
}

// domain service の例
export async function uploadVideoService(
  input: UploadInput,
  deps: { youtube: youtube_v3.Youtube }
): Promise<Result<UploadOutput, ServiceError>>;
```

### 8. schema は zod に集約、`isRecord` / 手書き parseX は撤廃

全 input/output schema を zod で declare、TS 型は `z.infer<typeof Schema>` で導出する。JSON 入力 (config / API レスポンス) は snake_case のまま zod schema を書き、top-level `.transform(snakeToCamel)` で camelCase 出力に変換する。`.strict()` で unknown key を reject、required は `.optional()` を付けないだけで表現、cross-section 制約は `.refine()` で記述。

```typescript
// packages/core/src/config/meta.ts (BEFORE: 93 LOC、interface + parseMeta + isRecord)
// AFTER (~30 LOC):
import { z } from "zod";
export const ChannelMeta = z.object({
  channel: z.object({
    name: z.string(),
    short: z.string(),
    youtube_handle: z.string(),
    url: z.string(),
    channel_id: z.string().default(""),
  }).strict(),
  youtube_channel: BrandingSchema.optional(),
}).strict().transform(snakeToCamel);
export type ChannelMeta = z.infer<typeof ChannelMeta>;
```

`config/internal.ts` (`isRecord`) は削除、`REQUIRED_KEYS_BY_SECTION` map も削除 (schema の required で表現)。

## Why

- **MCP serialization 強制**: ServiceError を zod discriminated union にしたことで、MCP server は `JSON.stringify(r.error)` で素直に JSON-RPC error を返せる。class 系統 + prototype chain では実現できなかった
- **AFK loop の retry semantic 強制**: AI agent が書く service の Result が `domain: "quota"` を返せば、CLI/MCP の caller は型レベルで `retryAfterSeconds` の有無を扱える。「429 を見て exponential backoff」を agent ごとに再発明する必要がない
- **MCP server の boot 制約**: MCP は server プロセスなので browser を開けない。`refresh` / `interactive` を path 分離して oxlint で MCP から interactive を遮断することで、boot 時に「browser を開こうとして hang する」 fail mode を機械的に排除
- **secret seam の対称性**: secret READ (env / op) を CLI に移したので、token WRITE (0o600 chmod) も CLI に移すのが対称。core は string in / string out で、unit test に op binary や temp dir が不要になる
- **schema-first の実証**: ADR 0002 が「zod を source of truth」と宣言したが、#732 以降の 6 child では `interface` + 手書き `parseX` の old shape が選ばれた (acceptance に template 適用が明記されていなかったため)。本 ADR で「`isRecord` / 手書き parseX 禁止、`z.infer` 必須」を明示することで以降の AFK で確実に zod 化される

## Considered Options

- **pure Result everywhere (本 ADR 不採用案)**: 全関数を `Promise<Result>` 化、throw 廃止。boilerplate が重く、TS の `throw` cheap という性質を活かせない。**core 内部の chain で `r.isErr() ? r : continue`** を毎ステップ書く ceremony が AFK loop で agent ごとに揺れる
- **throw のまま + tagged 1-class (本 ADR 不採用案)**: 8 class を `ServiceError` 1 class + `domain` field に縮退。実装最小だが MCP の JSON serialization で prototype chain が落ちる問題が解決しない。class 拘束のままだと将来 instance method を生やしたくなる drift がある
- **core が op / fs / browser をすべて抱え込む (本 ADR 不採用案)**: secret read / token write / browser flow を core に集約。test に op binary / temp dir / virtual display が要り、MCP server の boot が browser に依存して fail mode が増える
- **DI fetcher (TokenStore interface) (本 ADR 不採用案)**: core が `TokenStore { read, write }` を deps として受け取る。型で seam を表現できるが、全 auth callsite に deps を引き回す boilerplate が AFK の生産性を落とす。string-in / string-out + CLI 側で読み書きする方が AI agent も書きやすい
- **schema を camelCase で書いて preprocess で snake→camel (本 ADR 不採用案)**: zod schema 自体を camelCase で declare し、`.preprocess(camelizeDeep)` で JSON snake を吸収。declaration が読みやすいが、`preprocess` の型 `unknown` がエラーメッセージを劣化させる。snake_case で declare → `.transform()` の方が zod のエラーが原 JSON の field 名を指してくれる

## Canonical Template (ADR 0002 update)

ADR 0002 の canonical template を Phase 1 規約に合わせて以下へ更新する。**新規 service issue の acceptance criteria に本テンプレ準拠を明記する**:

> **📁 配置規約 (2026-06-14)**: core feature の canonical 配置は **`packages/core/src/<feature>/`**、CLI command は **`packages/cli/src/commands/<feature>/`**（いずれも `src/` あり）。少数派の `src` なし実装 (skills-sync / internal) は #984 で `src/` 配下へ移送する。本 ADR 内に残る `src` なしのパス例は `src/` 付きで読み替える。

### `packages/core/src/<feature>/schema.ts`

```typescript
import { z } from "zod";

export const FeatureInput = z.object({
  // snake_case JSON 入力 (config / API レスポンス互換) を declare
  channel_id: z.string(),
  start_date: z.string(),
}).strict().transform(snakeToCamel);

export const FeatureOutput = z.object({
  metrics: z.array(z.object({
    date: z.string(),
    value: z.number(),
  })),
}).strict();

export type FeatureInput = z.infer<typeof FeatureInput>;
export type FeatureOutput = z.infer<typeof FeatureOutput>;
```

### `packages/core/src/<feature>/service.ts`

```typescript
import { createService } from "../service-frame.ts";
import { FeatureInput, FeatureOutput } from "./schema.ts";
import type { youtube_v3 } from "googleapis";

export const featureService = createService(
  FeatureInput,
  FeatureOutput,
  async (input, deps: { youtube: youtube_v3.Youtube }) => {
    // 重い依存 (googleapis 経由) はここでのみ使う
    const raw = await deps.youtube.someApi.list({ ... });
    return transform(raw.data);
  }
);
```

### `packages/cli/src/commands/<feature>/cli.ts` (citty + 引数 parse → service)

```typescript
import { defineCommand } from "citty";
import { getYouTubeClient } from "../../lib/oauth.ts";
import { featureService, FeatureInput } from "@youtube-automation/core/<feature>";

export default defineCommand({
  meta: { name: "<feature>", description: "..." },
  args: {
    channelId: { type: "string", required: true },
    startDate: { type: "string", required: true },
  },
  async run({ args }) {
    const youtube = await getYouTubeClient();
    const input = FeatureInput.parse({
      channel_id: args.channelId,
      start_date: args.startDate,
    });
    const r = await featureService(input, { youtube });
    if (!r.ok) {
      console.error(`[${r.error.domain}] ${r.error.message}`);
      process.exit(r.error.domain === "quota" ? 75 : 1);
    }
    console.log(JSON.stringify(r.value, null, 2));
  },
});
```

### 将来 `packages/mcp/src/tools/<feature>.ts`

```typescript
import { featureService, FeatureInput, FeatureOutput } from "@youtube-automation/core/<feature>";
import { buildYouTubeClient } from "@youtube-automation/core/oauth/client";
import { refreshTokenService } from "@youtube-automation/core/oauth/refresh";
// import { interactiveAuthService } from ".../interactive";  ← oxlint error (MCP は interactive 禁止)

export const featureTool = {
  name: "<feature>",
  description: "...",
  inputSchema: FeatureInput,
  outputSchema: FeatureOutput,
  async handler(input: z.infer<typeof FeatureInput>, ctx) {
    const youtube = buildYouTubeClient(ctx.tokenJson);
    const r = await featureService(input, { youtube });
    if (!r.ok) {
      throw new McpError(/* r.error を JSON-RPC error にそのまま渡す */ r.error);
    }
    return r.value;
  },
};
```

## Enforcement

### Mechanical (oxlint)

`oxlint.config.ts` の per-file overrides に追加:

- `packages/cli/**` および `packages/mcp/**` から **`packages/core/src/oauth/interactive*`** の import を `no-restricted-imports` で **error** (MCP 側のみ。CLI は許可)
- `packages/core/**/config/internal*` への import を `no-restricted-imports` で **deprecated** 扱いし、新規 import を warn (撤廃完了で rule 削除)

ローカル `bun run lint` と CI の `ts-lint` ジョブで fail する。

### Review (子 issue PR self-review チェック)

- [ ] service export が `createService(InputSchema, OutputSchema, async (...) => rawOutput)` で定義され、公開面が `Promise<Result<T, ServiceError>>` を返しているか (throw 漏れなし)
- [ ] service 作者が `ok` / `err` / `toServiceError` frame を手書きせず、境界変換を `createService` に集約しているか
- [ ] schema を zod で declare し `z.infer` で型を導出しているか (`interface` 並書なし)
- [ ] 入力 JSON 形式 (snake_case) を schema で受け、camelCase は `.transform()` で導出しているか
- [ ] `isRecord` / 手書き `parseX` を新規に書いていないか
- [ ] credentials / secret を core で fetch していないか (CLI 経由で string in)

## Consequences

- **#734 (errors.ts) の retrofit**: 既に merge された `errors.ts` (190 LOC、8 class) を本 ADR の shape (Result + ServiceError + 3 class + toServiceError) に書き換える child issue が新規に要る。Phase 1B として 1 PR
- **#735 (secrets.ts) の移動**: `packages/core/src/secrets.ts` を `packages/cli/lib/secrets.ts` に移動、`SECRET_REFS` も同移動。`packages/core` から secrets module export を除去。Phase 1B として 1 PR
- **#736 (config) の zod 化**: 16 config + 5 metadata file を zod schema に書き換え (構造は維持)。`#1` (4-bucket 再編成) は別 PR で後続。Phase 1B として 1-2 PR
- **#738 (image_provider) の Result 化**: 既に merge された image provider service を `Promise<Result>` 化。Phase 1B として 1 PR
- **Phase 2 以降の新規 service 全件**: 本 ADR の canonical template に従う。acceptance に「ADR 0003 準拠」を明記
- **`zod` バージョンの確定**: zod 4 (`z.discriminatedUnion` / `.strict()` / `z.toJSONSchema()` が安定) を採用。`packages/core/package.json` で `"zod": "^4.0.0"` を pin
- **既存 PoC との関係**: `poc/ts-rewrite/` は本 ADR の対象外 (撤退判定用 PoC、本番コードではない)

## Related

- ADR 0001: Python → TypeScript(bun) big-bang 移行 (本 ADR の前提)
- ADR 0002: Service-first architecture (本 ADR が canonical template を上書き)
- Epic #727: TS rewrite (本 ADR の対象)
- S5-S8 自律 loop (#732 / #734-#738): drift 観測の出所
- Future epics (ADR 0002 で起票済み): subscription / queue / multi-tenancy — 本 ADR の service contract に乗る形で後付け可能
