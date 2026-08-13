import { expect, test } from "@playwright/test";

import { PHASE } from "../../../shared/constants";
import {
  beginRunTiming,
  finalizeRunTiming,
  formatRunTiming,
  transitionRunTiming,
} from "../../lib/run-timing";

test("mock Suno run の canonical phase 順と timing receipt を reload 後も表示する", async ({
  page,
}) => {
  let receipt = beginRunTiming(PHASE.INJECTING, 1_000);
  receipt = transitionRunTiming(receipt, PHASE.GENERATING, 1_100);
  receipt = transitionRunTiming(receipt, PHASE.WAITING_GENERATION, 1_200);
  receipt = transitionRunTiming(receipt, PHASE.ADDING_TO_PLAYLIST, 1_500);
  receipt = transitionRunTiming(receipt, PHASE.DOWNLOADING, 1_600);
  receipt = transitionRunTiming(receipt, PHASE.PLACING_ARCHIVE, 1_900);
  receipt = finalizeRunTiming(receipt, "finished", 2_000);
  const formatted = formatRunTiming(receipt);

  await page.route("http://suno.test/", (route) =>
    route.fulfill({
      body: "<main id='timing'></main>",
      contentType: "text/html",
    })
  );
  await page.goto("http://suno.test/");
  await page.evaluate(
    ({ receipt, lines }) => {
      localStorage.setItem("sunoRunTimingReceipt", JSON.stringify(receipt));
      document.querySelector("#timing")!.textContent = lines.join("\n");
    },
    { receipt, lines: formatted.lines }
  );

  await expect(page.locator("#timing")).toContainText("waiting-generation #1");
  await expect(page.locator("#timing")).toContainText("placing-archive #1");

  await page.reload();
  await page.evaluate(() => {
    const stored = localStorage.getItem("sunoRunTimingReceipt");
    if (!stored) throw new Error("timing receipt is missing after reload");
    const receipt = JSON.parse(stored) as { events: Array<{ phase: string }> };
    document.querySelector("#timing")!.textContent = receipt.events
      .map((event) => event.phase)
      .join(" > ");
  });

  await expect(page.locator("#timing")).toHaveText(
    "injecting > generating > waiting-generation > adding-to-playlist > downloading > placing-archive"
  );
});
