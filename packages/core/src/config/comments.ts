// コメント自動返信設定（merged の `comments`・optional）。
//
// 形状・enum・廃止キー・条件付き必須の検証は superRefine で行い、既存テストが期待する
// `config:` prefix のメッセージ（`comments.rules[0].name` 等、bracket 付き path を含む）を
// そのまま保持する。検証通過後に transform が camelCase 出力を組み立てる。

import { z } from "zod";

import { isPlainObject } from "./internal.ts";

const PROVIDER_CODEX = "codex";
const PROVIDER_GEMINI = "gemini";
const VALID_PROVIDERS = [PROVIDER_GEMINI, PROVIDER_CODEX];

const FALLBACK_SKIP = "skip";
const FALLBACK_RETRY = "retry";
const VALID_FALLBACK_VALUES = [FALLBACK_SKIP, FALLBACK_RETRY];

// CommentRule.scope: コメント階層（top-level / reply）でマッチ対象を絞る (#524)。
const SCOPE_ANY = "any";
const VALID_SCOPES = ["top_level", "reply", SCOPE_ANY];

const MAX_LENGTH_DEFAULT = 280;
const CHANNEL_PERSONA_DEFAULT = "";
const REQUESTS_PER_MINUTE_DEFAULT = 30;

type Issue = (message: string) => void;

const validateGenerator = (raw: Record<string, unknown>, add: Issue): void => {
  if ("type" in raw) {
    add(
      "comments.generator.type は廃止されました。comments.generator.provider を使用してください"
    );
    return;
  }
  const provider = (raw.provider as string | undefined) ?? PROVIDER_CODEX;
  if (!VALID_PROVIDERS.includes(provider)) {
    add(
      `comments.generator.provider は ${VALID_PROVIDERS.join(" / ")} のいずれかでなければなりません: ${provider}`
    );
    return;
  }
  const model = (raw.model as string | undefined) ?? null;
  if (provider === PROVIDER_GEMINI && !model) {
    add("comments.generator.provider='gemini' の場合 model は必須です");
    return;
  }
  const fallback =
    (raw.fallback_on_error as string | undefined) ?? FALLBACK_SKIP;
  if (!VALID_FALLBACK_VALUES.includes(fallback)) {
    add(
      `comments.generator.fallback_on_error は ${VALID_FALLBACK_VALUES.join(" / ")} のいずれかでなければなりません: ${fallback}`
    );
  }
};

const validateRule = (raw: unknown, index: number, add: Issue): void => {
  if (!isPlainObject(raw)) {
    add(`comments.rules[${index}] は object でなければなりません`);
    return;
  }
  if (!raw.name) {
    add(`comments.rules[${index}].name が必須です`);
    return;
  }
  if ("template_key" in raw) {
    add(`comments.rules[${index}].template_key は廃止されました`);
    return;
  }
  if ("generator" in raw) {
    add(
      `comments.rules[${index}].generator は廃止されました。provider を使用してください`
    );
    return;
  }
  const ruleProvider = (raw.provider as string | undefined) ?? null;
  if (ruleProvider !== null && !VALID_PROVIDERS.includes(ruleProvider)) {
    add(
      `comments.rules[${index}].provider は ${VALID_PROVIDERS.join(" / ")} のいずれかでなければなりません: ${ruleProvider}`
    );
    return;
  }
  const ruleScope = (raw.scope as string | undefined) ?? SCOPE_ANY;
  if (!VALID_SCOPES.includes(ruleScope)) {
    add(
      `comments.rules[${index}].scope は ${VALID_SCOPES.join(" / ")} のいずれかでなければなりません: ${ruleScope}`
    );
  }
};

const validateComments = (cm: unknown, add: Issue): void => {
  if (!isPlainObject(cm)) {
    add("comments セクションは object でなければなりません");
    return;
  }
  if ("templates" in cm) {
    add(
      "comments.templates は廃止されました。LLM provider で返信を生成してください"
    );
    return;
  }
  const rulesRaw = cm.rules;
  if (Array.isArray(rulesRaw)) {
    for (const [i, raw] of rulesRaw.entries()) {
      validateRule(raw, i, add);
    }
  }
  const genRaw = cm.generator;
  if (genRaw !== undefined && genRaw !== null) {
    if (!isPlainObject(genRaw)) {
      add("comments.generator は object でなければなりません");
      return;
    }
    validateGenerator(genRaw, add);
  }
};

const buildGenerator = (raw: Record<string, unknown> | undefined) => ({
  channelPersona:
    (raw?.channel_persona as string | undefined) ?? CHANNEL_PERSONA_DEFAULT,
  fallbackOnError:
    (raw?.fallback_on_error as string | undefined) ?? FALLBACK_SKIP,
  maxLength: (raw?.max_length as number | undefined) ?? MAX_LENGTH_DEFAULT,
  model: (raw?.model as string | undefined) ?? null,
  provider: (raw?.provider as string | undefined) ?? PROVIDER_CODEX,
  requestsPerMinute:
    (raw?.requests_per_minute as number | undefined) ??
    REQUESTS_PER_MINUTE_DEFAULT,
});

const buildRule = (raw: Record<string, unknown>) => ({
  keywords: [...((raw.keywords as string[] | undefined) ?? [])],
  language: (raw.language as string | undefined) ?? null,
  name: raw.name as string,
  pattern: (raw.pattern as string | undefined) ?? null,
  priority: (raw.priority as number | undefined) ?? 0,
  provider: (raw.provider as string | undefined) ?? null,
  scope: (raw.scope as string | undefined) ?? SCOPE_ANY,
});

const buildComments = (cm: Record<string, unknown>) => {
  const rulesRaw = (cm.rules as Record<string, unknown>[] | undefined) ?? [];
  const genRaw = cm.generator as Record<string, unknown> | undefined;
  return {
    delayBetweenRepliesSec:
      (cm.delay_between_replies_sec as number | undefined) ?? 2,
    enabled: (cm.enabled as boolean | undefined) ?? false,
    generator: buildGenerator(genRaw),
    historyFile:
      (cm.history_file as string | undefined) ?? "comment_reply_history.json",
    maxRepliesPerRun: (cm.max_replies_per_run as number | undefined) ?? 20,
    ngWords: [...((cm.ng_words as string[] | undefined) ?? [])],
    rules: rulesRaw.map(buildRule),
    skipHeldForReview: (cm.skip_held_for_review as boolean | undefined) ?? true,
  };
};

/** `comments` セクション（optional）。 */
export const Comments = z
  .object({
    comments: z.unknown().prefault({}),
  })
  .superRefine((o, ctx) => {
    validateComments(o.comments, (message) =>
      ctx.addIssue({ code: "custom", message })
    );
  })
  .transform((o) => buildComments(o.comments as Record<string, unknown>));

export type Comments = z.infer<typeof Comments>;
