// distrokid.com/new（実 DOM ミラー）に対する注入スモーク（#813 / #877 / #888）。
//
// jsdom では再現できない以下を実 Chromium で固定する:
//   1. id ベースセレクタが実 DOM 構造（SELECT / track 別 file input / 隠し入力）と一致すること
//   2. <input type=file> への DataTransfer 経由の File セット
//   3. React 互換ネイティブ setter によるテキスト/SELECT 注入での change 発火
//   4. トラック数 select（#howManySongsOnThisAlbum）の change で track 行が生成されること（#888）
//   5. AI 開示 radio「はい」→ modal mount → 録音範囲 full で persona radio が dynamic inject されること（#888）
//   6. Apple Music「クレジットを追加」click で全 track の credit 入力欄が visible 化すること（#888）
// あわせて「続ける」ボタンが押されないこと（規約遵守）を担保する。
//
// ここで使う注入手法は lib/distrokid-injector.ts が実装すべき技法と同一。
// （実拡張ロードによる full E2E は WXT 基盤整備後のフォローアップ）

import { test, expect } from "@playwright/test";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const fixtureUrl = "file://" + join(here, "fixtures", "distrokid-new.html");

// ネイティブ setter + bubbling イベントで SELECT / text を React 互換に注入する（page 内で実行）。
async function setNativeValue(
  page: import("@playwright/test").Page,
  selector: string,
  value: string,
): Promise<void> {
  await page.evaluate(
    ({ selector, value }) => {
      const el = document.querySelector<HTMLInputElement | HTMLSelectElement>(selector)!;
      const proto =
        el instanceof HTMLSelectElement
          ? HTMLSelectElement.prototype
          : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, "value")!.set!;
      setter.call(el, value);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    },
    { selector, value },
  );
}

test("トラック数 select でアルバム構造になり、SELECT/file 注入が成立する (#888)", async ({
  page,
}) => {
  // Given: 実 DOM ミラーのモックフォーム（既定はシングル = 1 track）
  await page.goto(fixtureUrl);
  await page.evaluate(() => {
    (window as unknown as { __changed: string[] }).__changed = [];
    document.addEventListener(
      "change",
      (e) => {
        const el = e.target as HTMLElement;
        (window as unknown as { __changed: string[] }).__changed.push(
          el.getAttribute("id") ?? el.getAttribute("name") ?? "",
        );
      },
      true,
    );
  });

  // Then: artistName は type=hidden（可視入力欄なし → 注入対象外）
  await expect(page.locator("#artistName")).toHaveAttribute("type", "hidden");

  // When: トラック数 select に 2 を set + change（アルバムモードへ）
  await setNativeValue(page, "#howManySongsOnThisAlbum", "2");

  // Then: プロファイル系 SELECT と各種欄が存在する
  for (const id of ["#language", "#genrePrimary", "#genreSecondary"]) {
    await expect(page.locator(id)).toHaveCount(1);
  }
  await expect(page.locator("#albumTitleInput")).toHaveCount(1);
  await expect(page.locator("#release-date-dp")).toHaveCount(1);
  await expect(page.locator("#artwork")).toHaveCount(1);

  // Then: 2 track 分の file input が 1-indexed で生成される
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
  await setNativeValue(page, "#language", "ja");
  await setNativeValue(page, '[name="songwriter_real_name_first1"]', "Jane");
  await page.evaluate(() => {
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
  expect(changed).toContain("howManySongsOnThisAlbum");
  expect(changed).toContain("language");
  expect(changed).toContain("js-track-upload-1");

  // Then: 送信系ボタンは拡張から押されない
  const continueClicked = await page.evaluate(
    () => (window as unknown as { __continueClicked: boolean }).__continueClicked,
  );
  expect(continueClicked).toBe(false);
});

test("AI 開示 modal は full check で persona radio を dynamic inject し、保存で全 track へ伝播する (#888)", async ({
  page,
}) => {
  // Given: 2 track（アルバム）に設定し、各 track の ai_gate radio を出す
  await page.goto(fixtureUrl);
  await setNativeValue(page, "#howManySongsOnThisAlbum", "2");
  await expect(page.locator('[name="ai_gate_uuid-track-1"]')).toHaveCount(2); // yes/no
  await expect(page.locator('[name="ai_gate_uuid-track-2"]')).toHaveCount(2);
  await expect(page.locator(".ai-credits-swal-modal")).toHaveCount(0);

  // When: 1st track の「はい」を click する (送信系ではない)
  await page.locator('[name="ai_gate_uuid-track-1"][value="1"]').click();

  // Then: modal が 1 つ mount し、modal 内に各フィールドが揃う（persona は未表示）
  const modal = page.locator(".ai-credits-swal-modal");
  await expect(modal).toHaveCount(1);
  await expect(modal.locator('[name="ai_lyrics_uuid-track-1"]')).toHaveCount(1);
  await expect(modal.locator('[name="ai_music_uuid-track-1"]')).toHaveCount(1);
  await expect(
    modal.locator('.distroAiRecordingScope[track="1"][value="full"]'),
  ).toHaveCount(1);
  await expect(modal.locator("#ai-apply-all-1")).toHaveCount(1);
  await expect(modal.locator(".distroAiArtistPersona")).toHaveCount(0); // 未 inject

  // When: 録音範囲 full を check（change 発火）→ persona radio が dynamic inject される（#888）
  await modal.locator('.distroAiRecordingScope[track="1"][value="full"]').check();
  await expect(modal.locator(".distroAiArtistPersona")).toHaveCount(2); // 人間/AI

  // When: AI ペルソナ + apply-all を入れて「保存する」を click する
  await modal.locator('.distroAiArtistPersona[value="1"]').check();
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

test("配信先ストア全 check + upsell uncheck + credits 可視化 + areyousure check (#923)", async ({
  page,
}) => {
  // Given: fixture（初期状態: ストア全 unchecked、credits hidden）
  await page.goto(fixtureUrl);
  await setNativeValue(page, "#howManySongsOnThisAlbum", "2");

  // storesが全部 unchecked であることを確認（最悪ケース再現）
  await expect(page.locator("#chkspotify")).not.toBeChecked();
  await expect(page.locator("#chkapplemusic")).not.toBeChecked();

  // credits section は hidden（Apple Music unchecked なので）
  await expect(page.locator(".requirements-item")).toBeHidden();

  // When: 配信先ストアを全 check（checkAllStores の模擬）
  for (const id of ["chkspotify", "chkapplemusic", "chkitunes", "chkgoogle", "chksnap", "chktiktok"]) {
    await page.locator(`#${id}`).check();
  }

  // Then: 配信先 chk* は全 checked
  await expect(page.locator("#chkspotify")).toBeChecked();
  await expect(page.locator("#chkapplemusic")).toBeChecked();

  // Then: credits section が visible 化（Apple Music checked → trigger 表示）
  await expect(page.locator(".requirements-item")).toBeVisible();

  // When: upsell uncheck（shazam / audiomack は name=store だが id なし）
  await page.evaluate(() => {
    document.querySelectorAll<HTMLInputElement>('input[type="checkbox"][name="store"]:not([id^="chk"])').forEach(cb => { if (cb.checked) cb.click(); });
    document.querySelectorAll<HTMLInputElement>('input[type="checkbox"][name="extras"]').forEach(cb => { if (cb.checked) cb.click(); });
  });

  // Then: shazam / audiomack は unchecked、配信先は維持
  const shazamChecked = await page.evaluate(() => document.querySelector<HTMLInputElement>('input[name="store"][value="shazam"]')?.checked);
  expect(shazamChecked).toBe(false);
  await expect(page.locator("#chkspotify")).toBeChecked(); // 配信先は維持

  // When: 「クレジットを追加」click → credit 入力欄 visible
  await page.getByText("クレジットを追加").click();
  await expect(page.locator("#track-1-performer-1-name")).toBeVisible();

  // When: areyousure required 4 個を check
  for (const id of ["areyousurepromoservices", "areyousurerecorded", "areyousureotherartist", "areyousuretandc"]) {
    await page.locator(`#${id}`).check();
  }
  // Then: required 4 個が checked
  for (const id of ["areyousurepromoservices", "areyousurerecorded", "areyousureotherartist", "areyousuretandc"]) {
    await expect(page.locator(`#${id}`)).toBeChecked();
  }

  // Then: 送信ボタンは押されていない
  const continueClicked = await page.evaluate(() => (window as unknown as { __continueClicked: boolean }).__continueClicked);
  expect(continueClicked).toBe(false);
});

test("Apple Music「クレジットを追加」click で全 track の credit 入力欄が visible 化し、注入できる (#888)", async ({
  page,
}) => {
  // Given: 2 track（アルバム）。credit 入力欄は事前生成済みだが初期は hidden
  await page.goto(fixtureUrl);
  await setNativeValue(page, "#howManySongsOnThisAlbum", "2");
  for (const n of [1, 2]) {
    await expect(page.locator(`#track-${n}-performer-1-name`)).toHaveCount(1);
    await expect(page.locator(`#track-${n}-producer-1-name`)).toHaveCount(1);
    await expect(page.locator(`#track-${n}-performer-1-name`)).toBeHidden();
  }

  // Given: Apple Music checkbox を check して credit section を visible 化する（#923 fixture 変更対応）。
  // 初期は unchecked のため、credit trigger も hidden になっている。
  await page.locator("#chkapplemusic").check();
  await expect(page.locator(".requirements-item")).toBeVisible();

  // When: 「クレジットを追加」を 1 回 click → 全 track の入力欄が visible 化する
  await page.getByText("クレジットを追加").click();
  for (const n of [1, 2]) {
    await expect(page.locator(`#track-${n}-performer-1-name`)).toBeVisible();
    await expect(page.locator(`#track-${n}-producer-1-name`)).toBeVisible();
  }

  // When: 全 track の performer / producer に artist 名（#artistName）を注入する
  const artist = await page.locator("#artistName").inputValue();
  for (const n of [1, 2]) {
    await setNativeValue(page, `#track-${n}-performer-1-name`, artist);
    await setNativeValue(page, `#track-${n}-producer-1-name`, artist);
  }

  // Then: 全 track に artist 名が入る
  for (const n of [1, 2]) {
    await expect(page.locator(`#track-${n}-performer-1-name`)).toHaveValue(artist);
    await expect(page.locator(`#track-${n}-producer-1-name`)).toHaveValue(artist);
  }

  // Then: 送信系ボタンは押されていない
  const continueClicked = await page.evaluate(
    () => (window as unknown as { __continueClicked: boolean }).__continueClicked,
  );
  expect(continueClicked).toBe(false);
});
