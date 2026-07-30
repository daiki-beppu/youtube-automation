import { expect, test } from "@playwright/test";

import {
  pickInitialCollectionId,
  type CollectionSummary,
} from "../../../shared/api";

const MOCK_POPUP_HTML = `<!doctype html>
<html><body><select id="collection"></select></body></html>`;

test("collection ドロップダウンは populate され、needs_prompts は disabled・初期値は最初の有効 entry", async ({
  page,
}) => {
  await page.setContent(MOCK_POPUP_HTML);
  const collections: CollectionSummary[] = [
    {
      id: "c1",
      name: "midnight-mood",
      status: "needs_prompts",
      pattern_count: null,
      downloaded_count: 0,
    },
    {
      id: "c2",
      name: "sunset-drive",
      status: "ready",
      pattern_count: 12,
      downloaded_count: 0,
    },
    {
      id: "c3",
      name: "dawn-chorus",
      status: "downloaded",
      pattern_count: 8,
      downloaded_count: 8,
    },
  ];
  const initialId = pickInitialCollectionId(collections) ?? "";

  const result = await page.evaluate(
    ({ collections, initialId }) => {
      const select = document.getElementById("collection") as HTMLSelectElement;
      for (const collection of collections) {
        const option = document.createElement("option");
        option.value = collection.id;
        option.textContent = collection.name;
        option.disabled = collection.status === "needs_prompts";
        select.appendChild(option);
      }
      select.value = initialId;

      return {
        optionCount: select.options.length,
        firstDisabled: select.options[0].disabled,
        secondDisabled: select.options[1].disabled,
        selectedValue: select.value,
      };
    },
    { collections, initialId }
  );

  expect(result.optionCount).toBe(3);
  expect(result.firstDisabled).toBe(true);
  expect(result.secondDisabled).toBe(false);
  expect(result.selectedValue).toBe("c2");
});
