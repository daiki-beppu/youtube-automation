// 固定コメント（オーナーコメント）自動投稿設定（Python `pinned_comment.py` + loader の移植）。

import { ConfigError } from "../errors.ts";
import { isRecord } from "./internal.ts";

const DEFAULT_HISTORY_FILE = "pinned_comment_history.json";
const DEFAULT_DELAY_SEC = 2.5;
const DEFAULT_LANGUAGE = "en";

/** `pinned_comment` セクション（optional・オプトイン）。 */
export interface PinnedComment {
  readonly enabled: boolean;
  readonly historyFile: string;
  readonly delayBetweenPostsSec: number;
  readonly defaultLanguage: string;
  readonly templates: Readonly<Record<string, string>>;
}

export const parsePinnedComment = (
  merged: Record<string, unknown>
): PinnedComment => {
  const raw = merged.pinned_comment;
  const pc = raw === undefined || raw === null ? {} : raw;
  if (!isRecord(pc)) {
    throw new ConfigError(
      "pinned_comment セクションは object でなければなりません"
    );
  }
  const templatesRaw = pc.templates;
  const templatesRoot =
    templatesRaw === undefined || templatesRaw === null ? {} : templatesRaw;
  if (!isRecord(templatesRoot)) {
    throw new ConfigError(
      "pinned_comment.templates は {言語: テンプレート文字列} の object でなければなりません"
    );
  }
  const templates: Record<string, string> = {};
  for (const [lang, text] of Object.entries(templatesRoot)) {
    templates[lang] = String(text);
  }
  return {
    defaultLanguage:
      (pc.default_language as string | undefined) ?? DEFAULT_LANGUAGE,
    delayBetweenPostsSec:
      (pc.delay_between_posts_sec as number | undefined) ?? DEFAULT_DELAY_SEC,
    enabled: (pc.enabled as boolean | undefined) ?? false,
    historyFile:
      (pc.history_file as string | undefined) ?? DEFAULT_HISTORY_FILE,
    templates,
  };
};
