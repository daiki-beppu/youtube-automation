import { PHASE, type ProgressPayload } from "../../shared/constants";

export function shouldReportLiveProgressStatus(progress: ProgressPayload): boolean {
  return progress.phase !== PHASE.DONE || Boolean(progress.log);
}
