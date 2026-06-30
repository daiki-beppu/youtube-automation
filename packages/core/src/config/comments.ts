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
  if (rulesRaw !== undefined && rulesRaw !== null && !Array.isArray(rulesRaw)) {
    add("comments.rules は list でなければなりません");
    return;
  }
  const { language } = cm;
  if (language !== undefined && language !== null) {
    if (typeof language !== "string") {
      add("comments.language は文字列でなければなりません");
      return;
    }
    if (!language.trim()) {
      add("comments.language は空文字にできません");
      return;
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

const buildComments = (cm: Record<string, unknown>) => {
  const genRaw = cm.generator as Record<string, unknown> | undefined;
  return {
    delayBetweenRepliesSec:
      (cm.delay_between_replies_sec as number | undefined) ?? 2,
    enabled: (cm.enabled as boolean | undefined) ?? false,
    generator: buildGenerator(genRaw),
    historyFile:
      (cm.history_file as string | undefined) ?? "comment_reply_history.json",
    language: (cm.language as string | undefined) ?? null,
    maxRepliesPerRun: (cm.max_replies_per_run as number | undefined) ?? 20,
    ngWords: [...((cm.ng_words as string[] | undefined) ?? [])],
    rules: [],
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
