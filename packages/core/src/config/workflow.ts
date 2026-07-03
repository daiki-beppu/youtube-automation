// ワークフロー設定（optional）。merged から `workflow` を取り出し camelCase へ。
//
// 旧 top-level `post_upload` / `short` キーは必須でないため strict にせず silently strip する
// （後方互換・#508）。検証対象は `wf_next.approval_gates` と
// `wf_next.skip_manual_mastering` のみ。

import { z } from "zod";

import { snakeToCamel } from "../../internal/case.ts";

/** `workflow` セクション（`/wf-next` の承認ゲートと raw=final 設定）。 */
export const Workflow = z
  .object({
    workflow: z
      .object({
        wf_next: z
          .object({
            approval_gates: z
              .object({
                audio: z.boolean().default(false),
                upload: z.boolean().default(false),
              })
              .strict()
              .prefault({}),
            skip_manual_mastering: z.boolean().default(false),
          })
          .strict()
          .prefault({}),
      })
      .prefault({}),
  })
  .transform((o) => snakeToCamel(o.workflow));

export type Workflow = z.infer<typeof Workflow>;
