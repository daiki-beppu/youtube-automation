// ワークフロー設定（Python `utils/config/workflow.py` + loader `_build_workflow` の移植）。

import { asRecord } from "./internal.ts";

/** `/wf-next` の承認ゲート設定（既定は両方 false で全自動進行）。 */
interface ApprovalGates {
  readonly audio: boolean;
  readonly upload: boolean;
}

/** `/wf-next` 関連設定（`wf_next` セクション）。 */
interface WfNext {
  readonly approvalGates: ApprovalGates;
}

/** ワークフロー責務の合成（`workflow` セクション）。 */
export interface Workflow {
  readonly wfNext: WfNext;
}

export const parseWorkflow = (merged: Record<string, unknown>): Workflow => {
  // 旧 top-level `post_upload` / `short` キーは必須登録していないため silently ignore。
  const wf = asRecord(merged.workflow, "workflow");
  const wfNext = asRecord(wf.wf_next, "workflow.wf_next");
  const gates = asRecord(
    wfNext.approval_gates,
    "workflow.wf_next.approval_gates"
  );
  return {
    wfNext: {
      approvalGates: {
        audio: (gates.audio as boolean | undefined) ?? false,
        upload: (gates.upload as boolean | undefined) ?? false,
      },
    },
  };
};
