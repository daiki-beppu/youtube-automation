import { describe, expect, it } from "vitest";

import { PHASE } from "../../shared/constants";
import { shouldReportLiveProgressStatus } from "../components/live-progress-status";

describe("shouldReportLiveProgressStatus: DONE live status 更新条件 (#1270)", () => {
  it("Given DONE without log When 判定 Then 従来どおり status 更新しない", () => {
    expect(shouldReportLiveProgressStatus({ phase: PHASE.DONE, index: 0, total: 3 })).toBe(false);
  });

  it("Given DONE with duration-check log When 判定 Then duration log を status 更新する", () => {
    expect(
      shouldReportLiveProgressStatus({
        phase: PHASE.DONE,
        index: 0,
        total: 3,
        log: { kind: "duration-check", entryName: "Night Groove", durationSec: 259, ok: true, maxSec: 300 },
      }),
    ).toBe(true);
  });

  it("Given non-DONE progress When 判定 Then status 更新する", () => {
    expect(shouldReportLiveProgressStatus({ phase: PHASE.WAITING_SLOT, index: 0, total: 3 })).toBe(true);
  });
});
