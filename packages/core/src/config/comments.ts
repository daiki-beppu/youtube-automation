// コメント自動返信設定（Python `utils/config/comments.py` + loader の移植・optional）。

import { asRecord, isRecord } from "./internal.ts";

const PROVIDER_CODEX = "codex";
const PROVIDER_GEMINI = "gemini";
const VALID_PROVIDERS = [PROVIDER_GEMINI, PROVIDER_CODEX];

const FALLBACK_SKIP = "skip";
const FALLBACK_RETRY = "retry";
const VALID_FALLBACK_VALUES = [FALLBACK_SKIP, FALLBACK_RETRY];

// CommentRule.scope: コメント階層（top-level / reply）でマッチ対象を絞る (#524)。
const SCOPE_TOP_LEVEL = "top_level";
const SCOPE_REPLY = "reply";
const SCOPE_ANY = "any";
const VALID_SCOPES = [SCOPE_TOP_LEVEL, SCOPE_REPLY, SCOPE_ANY];

const MAX_LENGTH_DEFAULT = 280;
const CHANNEL_PERSONA_DEFAULT = "";
const REQUESTS_PER_MINUTE_DEFAULT = 30;

/** `comments.generator` セクション。 */
interface GeneratorConfig {
  readonly provider: string;
  readonly model: string | null;
  readonly channelPersona: string;
  readonly maxLength: number;
  readonly fallbackOnError: string;
  readonly requestsPerMinute: number;
}

/** コメント返信ルール 1 件。 */
interface CommentRule {
  readonly name: string;
  readonly keywords: readonly string[];
  readonly pattern: string | null;
  readonly language: string | null;
  readonly priority: number;
  readonly provider: string | null;
  readonly scope: string;
}

/** `comments` セクション（optional）。 */
export interface Comments {
  readonly enabled: boolean;
  readonly rules: readonly CommentRule[];
  readonly ngWords: readonly string[];
  readonly maxRepliesPerRun: number;
  readonly delayBetweenRepliesSec: number;
  readonly historyFile: string;
  readonly skipHeldForReview: boolean;
  readonly generator: GeneratorConfig;
}

const defaultGenerator = (): GeneratorConfig => ({
  channelPersona: CHANNEL_PERSONA_DEFAULT,
  fallbackOnError: FALLBACK_SKIP,
  maxLength: MAX_LENGTH_DEFAULT,
  model: null,
  provider: PROVIDER_CODEX,
  requestsPerMinute: REQUESTS_PER_MINUTE_DEFAULT,
});

const parseGeneratorConfig = (
  raw: Record<string, unknown>
): GeneratorConfig => {
  if ("type" in raw) {
    throw new Error(
      "config: comments.generator.type は廃止されました。comments.generator.provider を使用してください"
    );
  }
  const provider = (raw.provider as string | undefined) ?? PROVIDER_CODEX;
  if (!VALID_PROVIDERS.includes(provider)) {
    throw new Error(
      `config: comments.generator.provider は ${VALID_PROVIDERS.join(" / ")} のいずれかでなければなりません: ${provider}`
    );
  }
  const model = (raw.model as string | undefined) ?? null;
  if (provider === PROVIDER_GEMINI && !model) {
    throw new Error(
      "config: comments.generator.provider='gemini' の場合 model は必須です"
    );
  }
  const fallback =
    (raw.fallback_on_error as string | undefined) ?? FALLBACK_SKIP;
  if (!VALID_FALLBACK_VALUES.includes(fallback)) {
    throw new Error(
      `config: comments.generator.fallback_on_error は ${VALID_FALLBACK_VALUES.join(" / ")} のいずれかでなければなりません: ${fallback}`
    );
  }
  return {
    channelPersona:
      (raw.channel_persona as string | undefined) ?? CHANNEL_PERSONA_DEFAULT,
    fallbackOnError: fallback,
    maxLength: (raw.max_length as number | undefined) ?? MAX_LENGTH_DEFAULT,
    model,
    provider,
    requestsPerMinute:
      (raw.requests_per_minute as number | undefined) ??
      REQUESTS_PER_MINUTE_DEFAULT,
  };
};

const parseRule = (raw: unknown, index: number): CommentRule => {
  if (!isRecord(raw)) {
    throw new Error(
      `config: comments.rules[${index}] は object でなければなりません`
    );
  }
  const { name } = raw;
  if (!name) {
    throw new Error(`config: comments.rules[${index}].name が必須です`);
  }
  if ("template_key" in raw) {
    throw new Error(
      `config: comments.rules[${index}].template_key は廃止されました`
    );
  }
  if ("generator" in raw) {
    throw new Error(
      `config: comments.rules[${index}].generator は廃止されました。provider を使用してください`
    );
  }
  const ruleProvider = (raw.provider as string | undefined) ?? null;
  if (ruleProvider !== null && !VALID_PROVIDERS.includes(ruleProvider)) {
    throw new Error(
      `config: comments.rules[${index}].provider は ${VALID_PROVIDERS.join(" / ")} のいずれかでなければなりません: ${ruleProvider}`
    );
  }
  const ruleScope = (raw.scope as string | undefined) ?? SCOPE_ANY;
  if (!VALID_SCOPES.includes(ruleScope)) {
    throw new Error(
      `config: comments.rules[${index}].scope は ${VALID_SCOPES.join(" / ")} のいずれかでなければなりません: ${ruleScope}`
    );
  }
  return {
    keywords: [...((raw.keywords as string[] | undefined) ?? [])],
    language: (raw.language as string | undefined) ?? null,
    name: name as string,
    pattern: (raw.pattern as string | undefined) ?? null,
    priority: (raw.priority as number | undefined) ?? 0,
    provider: ruleProvider,
    scope: ruleScope,
  };
};

export const parseComments = (merged: Record<string, unknown>): Comments => {
  const cm = asRecord(merged.comments, "comments");
  if ("templates" in cm) {
    throw new Error(
      "config: comments.templates は廃止されました。LLM provider で返信を生成してください"
    );
  }

  const rulesRaw = (cm.rules as unknown[] | undefined) ?? [];
  const rules = rulesRaw.map((raw, i) => parseRule(raw, i));

  const genRaw = cm.generator;
  let generator = defaultGenerator();
  if (genRaw !== undefined && genRaw !== null) {
    if (!isRecord(genRaw)) {
      throw new Error(
        "config: comments.generator は object でなければなりません"
      );
    }
    generator = parseGeneratorConfig(genRaw);
  }

  return {
    delayBetweenRepliesSec:
      (cm.delay_between_replies_sec as number | undefined) ?? 2,
    enabled: (cm.enabled as boolean | undefined) ?? false,
    generator,
    historyFile:
      (cm.history_file as string | undefined) ?? "comment_reply_history.json",
    maxRepliesPerRun: (cm.max_replies_per_run as number | undefined) ?? 20,
    ngWords: [...((cm.ng_words as string[] | undefined) ?? [])],
    rules,
    skipHeldForReview: (cm.skip_held_for_review as boolean | undefined) ?? true,
  };
};
