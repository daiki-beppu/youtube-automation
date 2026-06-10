// distrokid.com/new（実 DOM ミラー）に対する注入スモーク（#813）。
//
// jsdom では再現できない以下を実 Chromium で固定する:
//   1. id ベースセレクタが実 DOM 構造（SELECT / track 別 file input / 隠し入力）と一致すること
//   2. <input type=file> への DataTransfer 経由の File セット
//   3. React 互換ネイティブ setter によるテキスト/SELECT 注入での change 発火
//   4. AI 開示 radio「はい」→ モーダルが MutationObserver で待機可能なこと
//   5. 全 track（複数 #js-track-upload-N）が DOM order で解決できること
// あわせて「続ける」ボタンが押されないこと（規約遵守）を担保する。
//
// ここで使う注入手法は lib/distrokid-injector.ts が実装すべき技法と同一。
// （実拡張ロードによる full E2E は WXT 基盤整備後のフォローアップ）

import { test, expect } from "@playwright/test";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const fixtureUrl = "file://" + join(here, "fixtures", "distrokid-new.html");

test("id ベースの実 DOM 構造に一致し、SELECT/file 注入が成立する", async ({ page }) => {
  // Given: 実 DOM ミラーのモックフォームを開き、change を監視する
  await page.goto(fixtureUrl);
  await page.evaluate(() => {
    (window as unknown as { __changed: string[] }).__changed = [];
    for (const el of Array.from(
      document.querySelectorAll<HTMLElement>("input, select"),
    )) {
      el.addEventListener("change", () => {
        (window as unknown as { __changed: string[] }).__changed.push(
          el.getAttribute("id") ?? el.getAttribute("name") ?? "",
        );
      });
    }
  });

  // Then: artistName は type=hidden（可視入力欄なし → 注入対象外）
  await expect(page.locator("#artistName")).toHaveAttribute("type", "hidden");

  // Then: プロファイル系は id ベースの SELECT が存在する
  for (const id of ["#language", "#genrePrimary", "#genreSecondary"]) {
    await expect(page.locator(id)).toHaveCount(1);
  }
  await expect(page.locator("#albumTitleInput")).toHaveCount(1);
  await expect(page.locator("#release-date-dp")).toHaveCount(1);
  await expect(page.locator("#artwork")).toHaveCount(1);

  // Then: 複数 track の file input が 1-indexed で存在する
  await expect(page.locator("#js-track-upload-1")).toHaveCount(1);
  await expect(page.locator("#js-track-upload-2")).toHaveCount(1);

  // Then: track タイトルは [name^="title_"] の DOM order で解決できる
  const uuids = await page.evaluate(() =>
    Array.from(document.querySelectorAll<HTMLInputElement>('[name^="title_"]')).map(
      (el) => el.getAttribute("name"),
    ),
  );
  expect(uuids).toEqual(["title_uuid-track-1", "title_uuid-track-2"]);

  // Then: previouslyReleased は value="0"（いいえ）が checked（新規リリース前提の assert 対象）
  const noChecked = await page.evaluate(
    () =>
      document.querySelector<HTMLInputElement>(
        '[name="previouslyReleased_uuid-track-1"][value="0"]',
      )?.checked,
  );
  expect(noChecked).toBe(true);

  // When: SELECT とテキストを native setter、ファイルを DataTransfer で注入する
  await page.evaluate(() => {
    const setNativeValue = (
      el: HTMLInputElement | HTMLSelectElement,
      value: string,
    ) => {
      const proto =
        el instanceof HTMLSelectElement
          ? HTMLSelectElement.prototype
          : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, "value")!.set!;
      setter.call(el, value);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    };
    setNativeValue(
      document.querySelector<HTMLSelectElement>("#language")!,
      "ja",
    );
    setNativeValue(
      document.querySelector<HTMLInputElement>(
        '[name="songwriter_real_name_first1"]',
      )!,
      "Jane",
    );

    const file = new File(["audio-bytes"], "track-01.mp3", { type: "audio/mpeg" });
    const dt = new DataTransfer();
    dt.items.add(file);
    const upload = document.querySelector<HTMLInputElement>("#js-track-upload-1")!;
    upload.files = dt.files;
    upload.dispatchEvent(new Event("change", { bubbles: true }));
  });

  // Then: SELECT 値・テキスト・ファイル名がセットされ change が発火している
  await expect(page.locator("#language")).toHaveValue("ja");
  await expect(
    page.locator('[name="songwriter_real_name_first1"]'),
  ).toHaveValue("Jane");
  const songFileName = await page.evaluate(
    () =>
      document.querySelector<HTMLInputElement>("#js-track-upload-1")!.files?.[0]
        ?.name,
  );
  expect(songFileName).toBe("track-01.mp3");
  const changed = await page.evaluate(
    () => (window as unknown as { __changed: string[] }).__changed,
  );
  expect(changed).toContain("language");
  expect(changed).toContain("js-track-upload-1");

  // Then: 送信系ボタンは拡張から押されない
  const continueClicked = await page.evaluate(
    () => (window as unknown as { __continueClicked: boolean }).__continueClicked,
  );
  expect(continueClicked).toBe(false);
});

test("AI 開示は 1st track の ai_gate「はい」で swal2 modal が開き、保存で 25 track 相当へ伝播する (#877)", async ({
  page,
}) => {
  // Given: 各 track の ai_gate radio (yes/no) があり、初期は modal 未表示
  await page.goto(fixtureUrl);
  await expect(page.locator('[name="ai_gate_uuid-track-1"]')).toHaveCount(2); // yes/no
  await expect(page.locator('[name="ai_gate_uuid-track-2"]')).toHaveCount(2);
  await expect(page.locator(".ai-credits-swal-modal")).toHaveCount(0);

  // When: 1st track の「はい」を click する (送信系ではない)
  await page.locator('[name="ai_gate_uuid-track-1"][value="1"]').click();

  // Then: SweetAlert2 modal が 1 つ mount し、modal 内に各フィールドが揃う
  const modal = page.locator(".ai-credits-swal-modal");
  await expect(modal).toHaveCount(1);
  await expect(modal.locator('[name="ai_lyrics_uuid-track-1"]')).toHaveCount(1);
  await expect(modal.locator('[name="ai_music_uuid-track-1"]')).toHaveCount(1);
  await expect(modal.locator(".distroAiRecordingScope")).toHaveCount(2); // full/partial
  await expect(modal.locator(".distroAiArtistPersona")).toHaveCount(2); // 人間/AI
  await expect(modal.locator("#ai-apply-all-1")).toHaveCount(1);

  // When: modal 内で AI ペルソナ + apply-all を入れて「保存する」を click する
  await modal.locator(".distroAiArtistPersona[value='1']").check();
  await modal.locator("#ai-apply-all-1").check();
  await modal.locator("button.swal2-confirm.ai-modal-btn-save").click();

  // Then: modal は閉じ (1 回だけ開閉)、apply-all により全 track の ai_gate「はい」が checked になる
  await expect(page.locator(".ai-credits-swal-modal")).toHaveCount(0);
  await expect(
    page.locator('[name="ai_gate_uuid-track-1"][value="1"]'),
  ).toBeChecked();
  await expect(
    page.locator('[name="ai_gate_uuid-track-2"][value="1"]'),
  ).toBeChecked();

  // Then: 送信系ボタンは押されていない
  const continueClicked = await page.evaluate(
    () => (window as unknown as { __continueClicked: boolean }).__continueClicked,
  );
  expect(continueClicked).toBe(false);
});
