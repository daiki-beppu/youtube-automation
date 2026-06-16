// 固定コメント（オーナーコメント）自動投稿設定（merged の `pinned_comment`・optional）。
//
// `templates` は `{言語コード: テンプレート文字列}` の map。言語コードを camel 化しないため
// snakeToCamel は適用せず verbatim 保持する。

import { z } from "zod";

/** `pinned_comment` セクション（optional・オプトイン）。 */
export const PinnedComment = z
  .object({
    pinned_comment: z
      .object({
        default_language: z.string().default("en"),
        delay_between_posts_sec: z.number().default(2.5),
        enabled: z.boolean().default(false),
        history_file: z.string().default("pinned_comment_history.json"),
        templates: z.record(z.string(), z.string()).default({}),
      })
      .strict()
      .prefault({}),
  })
  .transform((o) => ({
    defaultLanguage: o.pinned_comment.default_language,
    delayBetweenPostsSec: o.pinned_comment.delay_between_posts_sec,
    enabled: o.pinned_comment.enabled,
    historyFile: o.pinned_comment.history_file,
    templates: o.pinned_comment.templates,
  }));

export type PinnedComment = z.infer<typeof PinnedComment>;
