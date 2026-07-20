// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  attachImage,
  cancelCommunityPostForm,
  clickPost,
  openCommunityPostForm,
  openSchedulePicker,
  resolveCommunityTextField,
  resolveImageUploadInput,
  resolvePostButton,
  setScheduleDateTime,
  setCommunityText,
} from "../../shared/community-dom";

const VISIBLE_RECT = {
  bottom: 100,
  height: 100,
  left: 0,
  right: 100,
  toJSON: () => ({}),
  top: 0,
  width: 100,
  x: 0,
  y: 0,
} as DOMRect;

function markVisible(element: Element): void {
  Object.defineProperty(element, "getBoundingClientRect", {
    configurable: true,
    value: () => VISIBLE_RECT,
  });
}

function renderTextFixture(): {
  editor: HTMLDivElement;
  submit: HTMLButtonElement;
} {
  document.body.innerHTML = `
    <ytd-backstage-post-dialog-renderer>
      <ytd-commentbox id="commentbox">
        <div id="creation-box">
          <div id="contenteditable-root" contenteditable="true"></div>
        </div>
        <div id="buttons">
          <ytd-button-renderer id="submit-button">
            <button aria-disabled="true" disabled>投稿</button>
          </ytd-button-renderer>
        </div>
      </ytd-commentbox>
    </ytd-backstage-post-dialog-renderer>`;

  const form = document.querySelector("ytd-backstage-post-dialog-renderer");
  const commentbox = document.querySelector("ytd-commentbox#commentbox");
  const editor = document.querySelector<HTMLDivElement>(
    "#contenteditable-root"
  );
  const submit = document.querySelector<HTMLButtonElement>(
    "#submit-button button"
  );
  if (!(form && commentbox && editor && submit)) {
    throw new Error("fixture の構築に失敗しました");
  }
  markVisible(form);
  markVisible(commentbox);
  markVisible(editor);
  editor.addEventListener("input", () => {
    setTimeout(() => {
      submit.disabled = editor.textContent?.length === 0;
      submit.setAttribute("aria-disabled", String(submit.disabled));
    }, 0);
  });
  return { editor, submit };
}

describe("community DOM text seam", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("resolves the active contenteditable and updates Polymer state", async () => {
    const { editor, submit } = renderTextFixture();

    expect(resolveCommunityTextField()).toBe(editor);
    await setCommunityText("次の動画を公開しました");

    expect(editor.textContent).toBe("次の動画を公開しました");
    expect(submit.disabled).toBe(false);
  });

  it("walks an open shadow root and updates a textarea through its native value", async () => {
    document.body.innerHTML = `
      <ytd-backstage-post-dialog-renderer>
        <ytd-commentbox id="commentbox"></ytd-commentbox>
      </ytd-backstage-post-dialog-renderer>`;
    const form = document.querySelector("ytd-backstage-post-dialog-renderer");
    const commentbox = document.querySelector("ytd-commentbox");
    if (!(form && commentbox)) {
      throw new Error("shadow fixture の構築に失敗しました");
    }
    const shadow = commentbox.attachShadow({ mode: "open" });
    shadow.innerHTML = `
      <textarea aria-label="community text"></textarea>
      <ytd-button-renderer id="submit-button">
        <button aria-disabled="true" disabled>投稿</button>
      </ytd-button-renderer>`;
    const textarea = shadow.querySelector("textarea");
    const submit = shadow.querySelector<HTMLButtonElement>(
      "#submit-button button"
    );
    if (!(textarea && submit)) {
      throw new Error("shadow textarea がありません");
    }
    markVisible(form);
    markVisible(commentbox);
    markVisible(textarea);
    let observed = "";
    textarea.addEventListener("input", () => {
      observed = textarea.value;
      setTimeout(() => {
        submit.disabled = false;
        submit.setAttribute("aria-disabled", "false");
      }, 0);
    });

    expect(resolveCommunityTextField()).toBe(textarea);
    await setCommunityText("Shadow DOM の投稿");

    expect(textarea.value).toBe("Shadow DOM の投稿");
    expect(observed).toBe("Shadow DOM の投稿");
    expect(submit.disabled).toBe(false);
  });

  it("emits the deletion input type when clearing text", async () => {
    const { editor, submit } = renderTextFixture();
    await setCommunityText("下書き");
    let inputType = "";
    editor.addEventListener("input", (event) => {
      inputType = (event as InputEvent).inputType;
    });

    await setCommunityText("");

    expect(inputType).toBe("deleteContentBackward");
    expect(submit.disabled).toBe(true);
  });

  it("opens a collapsed post form and waits for its editor", async () => {
    document.body.innerHTML = `
      <ytd-backstage-post-dialog-renderer>
        <div id="commentbox-placeholder" role="button">投稿を作成</div>
        <ytd-commentbox id="commentbox" style="display: none">
          <div id="contenteditable-root" contenteditable="true"></div>
        </ytd-commentbox>
      </ytd-backstage-post-dialog-renderer>`;
    const form = document.querySelector("ytd-backstage-post-dialog-renderer");
    const placeholder = document.querySelector<HTMLElement>(
      "#commentbox-placeholder"
    );
    const commentbox = document.querySelector<HTMLElement>(
      "ytd-commentbox#commentbox"
    );
    const editor = document.querySelector<HTMLElement>("#contenteditable-root");
    if (!(form && placeholder && commentbox && editor)) {
      throw new Error("collapsed fixture の構築に失敗しました");
    }
    for (const element of [form, placeholder, editor]) {
      markVisible(element);
    }
    placeholder.addEventListener("click", () => {
      setTimeout(() => {
        commentbox.style.display = "block";
        markVisible(commentbox);
      }, 0);
    });

    await openCommunityPostForm();

    expect(resolveCommunityTextField()).toBe(editor);
  });

  it("cancels and resets a dirty composer before a safe retry", async () => {
    document.body.innerHTML = `
      <ytd-backstage-post-dialog-renderer>
        <ytd-commentbox id="commentbox">
          <div id="contenteditable-root" contenteditable="true">dirty draft</div>
          <div id="thumbnail-images-container">
            <ytd-backstage-multi-image-thumbnail-renderer selected>
              <img class="thumbnail-image" src="data:image/png;base64,b2xk">
            </ytd-backstage-multi-image-thumbnail-renderer>
          </div>
          <div id="footer"><div id="cancel-button"><button>取消</button></div></div>
        </ytd-commentbox>
      </ytd-backstage-post-dialog-renderer>`;
    const form = document.querySelector("ytd-backstage-post-dialog-renderer");
    const commentbox = document.querySelector<HTMLElement>(
      "ytd-commentbox#commentbox"
    );
    const editor = document.querySelector<HTMLElement>("#contenteditable-root");
    const cancel = document.querySelector<HTMLButtonElement>(
      "#footer #cancel-button button"
    );
    if (!(form && commentbox && editor && cancel)) {
      throw new Error("cancel fixture の構築に失敗しました");
    }
    for (const element of [form, commentbox, editor, cancel]) {
      markVisible(element);
    }
    cancel.addEventListener("click", () => {
      setTimeout(() => {
        editor.textContent = "";
        commentbox.querySelector("#thumbnail-images-container")?.remove();
        commentbox.style.display = "none";
      }, 0);
    });

    await cancelCommunityPostForm();

    expect(editor.textContent).toBe("");
    expect(document.querySelector("img.thumbnail-image[src]")).toBeNull();
  });
});

describe("community DOM schedule seam", () => {
  // Fixture wiring intentionally models the coupled Polymer controls in one setup.
  // fallow-ignore-next-line complexity
  beforeEach(() => {
    document.body.innerHTML = `
      <ytd-backstage-post-dialog-renderer>
        <ytd-commentbox id="commentbox">
          <div id="contenteditable-root" contenteditable="true"></div>
          <div id="option-menu"><button type="button">menu</button></div>
          <ytd-button-renderer id="submit-button">
            <button type="button" aria-disabled="false">submit</button>
          </ytd-button-renderer>
          <div id="scheduling-panel" style="display: none">
            <ytd-date-time-picker-renderer>
              <ytd-calendar-date-picker>
                <div id="date-label-text">Jul 19, 2026</div>
                <button id="date-picker" type="button">date</button>
                <div id="month-controller">
                  <yt-icon-button id="prev-month"><button type="button">prev</button></yt-icon-button>
                  <yt-icon-button id="next-month"><button type="button">next</button></yt-icon-button>
                </div>
                <div class="calendar-container" style="display: none">
                  <div class="calendar-month" role="listitem">
                    <span class="calendar-day today">18</span>
                    <span class="calendar-day selected">19</span>
                    <span class="calendar-day">20</span>
                  </div>
                </div>
              </ytd-calendar-date-picker>
              <button id="time-picker" type="button">time</button>
              <div id="time-label-text">12:00 AM</div>
              <div id="time-listbox" role="listbox"></div>
              <div id="timezone-picker">(GMT+0900) Local time</div>
            </ytd-date-time-picker-renderer>
          </div>
        </ytd-commentbox>
      </ytd-backstage-post-dialog-renderer>
      <ytd-menu-popup-renderer style="display: none">
        <ytd-menu-service-item-renderer>投稿のスケジュールを設定</ytd-menu-service-item-renderer>
        <ytd-menu-service-item-renderer>Delete draft</ytd-menu-service-item-renderer>
      </ytd-menu-popup-renderer>`;
    const form = document.querySelector("ytd-backstage-post-dialog-renderer");
    const commentbox = document.querySelector<HTMLElement>(
      "ytd-commentbox#commentbox"
    );
    const menu = document.querySelector<HTMLButtonElement>(
      "#option-menu button"
    );
    const popup = document.querySelector<HTMLElement>(
      "ytd-menu-popup-renderer"
    );
    const items = [
      ...document.querySelectorAll<HTMLElement>(
        "ytd-menu-service-item-renderer"
      ),
    ];
    const item = items[0];
    const panel = document.querySelector<HTMLElement>("#scheduling-panel");
    const editor = document.querySelector<HTMLElement>("#contenteditable-root");
    const submit = document.querySelector<HTMLButtonElement>(
      "#submit-button button"
    );
    const month = document.querySelector<HTMLElement>(".calendar-month");
    const timePicker =
      document.querySelector<HTMLButtonElement>("#time-picker");
    const timeList = document.querySelector<HTMLElement>("#time-listbox");
    const calendar = document.querySelector<HTMLElement>(".calendar-container");
    const datePicker =
      document.querySelector<HTMLButtonElement>("#date-picker");
    const timezone = document.querySelector<HTMLElement>("#timezone-picker");
    const nextMonth =
      document.querySelector<HTMLButtonElement>("#next-month button");
    if (
      !(
        form &&
        commentbox &&
        menu &&
        popup &&
        item &&
        panel &&
        submit &&
        editor
      )
    ) {
      throw new Error("schedule fixture の構築に失敗しました");
    }
    if (
      !(
        month &&
        timePicker &&
        timeList &&
        calendar &&
        nextMonth &&
        datePicker &&
        timezone
      )
    ) {
      throw new Error("date-time fixture の構築に失敗しました");
    }
    for (const element of [
      form,
      commentbox,
      menu,
      item,
      ...items,
      panel,
      editor,
      month,
      timePicker,
      submit,
      calendar,
      nextMonth,
      datePicker,
      timezone,
    ]) {
      markVisible(element);
    }
    menu.addEventListener("click", () => {
      popup.style.display = "block";
    });
    item.addEventListener("click", () => {
      panel.style.display = "block";
    });
    datePicker.addEventListener("click", () => {
      calendar.style.display = "block";
    });
    submit.addEventListener("click", () => {
      submit.disabled = true;
      submit.setAttribute("aria-disabled", "true");
      const commentbox = document.querySelector("ytd-commentbox#commentbox");
      const editor = document.querySelector("#contenteditable-root");
      if (editor) {
        editor.textContent = "";
      }
      commentbox?.setAttribute("hidden", "");
    });
    for (const day of month.querySelectorAll<HTMLElement>(".calendar-day")) {
      markVisible(day);
      day.addEventListener("click", () => {
        setTimeout(() => {
          month.querySelector(".selected")?.classList.remove("selected");
          day.classList.add("selected");
          const label = document.querySelector("#date-label-text");
          if (label) {
            label.textContent = `Jul ${day.textContent}, 2026`;
          }
        }, 0);
      });
    }
    nextMonth.addEventListener("click", () => {
      calendar.innerHTML = `
        <div class="calendar-month" role="listitem">
          <span class="calendar-day">20</span>
        </div>`;
      const next = calendar.querySelector<HTMLElement>(".calendar-month");
      const day = calendar.querySelector<HTMLElement>(".calendar-day");
      if (!(next && day)) {
        throw new Error("next month fixture の構築に失敗しました");
      }
      markVisible(next);
      markVisible(day);
      day.addEventListener("click", () => {
        setTimeout(() => {
          day.classList.add("selected");
          const label = document.querySelector("#date-label-text");
          if (label) {
            label.textContent = "Aug 20, 2026";
          }
        }, 0);
      });
    });
    for (let index = 0; index < 96; index += 1) {
      const option = document.createElement("button");
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", String(index === 0));
      option.textContent = String(index);
      markVisible(option);
      option.addEventListener("click", () => {
        setTimeout(() => {
          timeList
            .querySelector('[aria-selected="true"]')
            ?.setAttribute("aria-selected", "false");
          option.setAttribute("aria-selected", "true");
          const label = document.querySelector("#time-label-text");
          if (label) {
            label.textContent = index === 37 ? "9:15 AM" : String(index);
          }
        }, 0);
      });
      timeList.append(option);
    }
  });

  it("opens the only safe operation-menu action and waits for the picker", async () => {
    await openSchedulePicker();

    expect(
      getComputedStyle(document.querySelector("#scheduling-panel") as Element)
        .display
    ).toBe("block");
  });

  it("sets the wall-clock date and 15-minute time through custom controls", async () => {
    await openSchedulePicker();
    await setScheduleDateTime(
      "2026-07-20T09:15:00+09:00",
      document,
      new Date("2026-07-18T00:00:00+09:00")
    );

    expect(document.querySelector("#date-label-text")?.textContent).toBe(
      "Jul 20, 2026"
    );
    expect(document.querySelector("#time-label-text")?.textContent).toBe(
      "9:15 AM"
    );
    expect(
      document.querySelectorAll('#time-listbox [aria-selected="true"]')
    ).toHaveLength(1);
    expect(
      [...document.querySelectorAll("#time-listbox [role=option]")].findIndex(
        (option) => option.getAttribute("aria-selected") === "true"
      )
    ).toBe(37);
  });

  it("navigates to a target month outside the initial virtualized window", async () => {
    await openSchedulePicker();
    await setScheduleDateTime(
      "2026-08-20T09:15:00+09:00",
      document,
      new Date("2026-07-18T00:00:00+09:00")
    );

    expect(
      document.querySelector(".calendar-month .calendar-day.selected")
        ?.textContent
    ).toBe("20");
  });

  it("resolves the stable submit id and waits until the form resets", async () => {
    await setCommunityText("予約投稿本文");
    await openSchedulePicker();
    await setScheduleDateTime(
      "2026-07-20T09:15:00+09:00",
      document,
      new Date("2026-07-18T00:00:00+09:00")
    );
    const button = resolvePostButton();

    await clickPost({
      imageFilename: null,
      scheduledAt: "2026-07-20T09:15:00+09:00",
      text: "予約投稿本文",
    });

    expect(button.disabled).toBe(true);
    expect(
      document
        .querySelector("ytd-commentbox#commentbox")
        ?.hasAttribute("hidden")
    ).toBe(true);
  });

  it("does not report success when the form only collapses", async () => {
    await setCommunityText("予約投稿本文");
    await openSchedulePicker();
    await setScheduleDateTime(
      "2026-07-20T09:15:00+09:00",
      document,
      new Date("2026-07-18T00:00:00+09:00")
    );
    const button = resolvePostButton();
    button.addEventListener("click", () => {
      button.disabled = false;
      button.setAttribute("aria-disabled", "false");
    });

    await expect(
      clickPost(
        {
          imageFilename: null,
          scheduledAt: "2026-07-20T09:15:00+09:00",
          text: "予約投稿本文",
        },
        document,
        20
      )
    ).rejects.toThrow("タイムアウト");
  });

  it("rejects a schedule offset that differs from the picker timezone", async () => {
    await openSchedulePicker();

    await expect(
      setScheduleDateTime(
        "2026-07-20T09:15:00-04:00",
        document,
        new Date("2026-07-18T00:00:00+09:00")
      )
    ).rejects.toThrow("timezone");
  });

  it("uses the picker timezone when the runtime date crosses a month boundary", async () => {
    const nextMonth =
      document.querySelector<HTMLButtonElement>("#next-month button");
    if (!nextMonth) {
      throw new Error("next month button がありません");
    }
    let navigationCount = 0;
    nextMonth.addEventListener("click", () => {
      navigationCount += 1;
    });
    await openSchedulePicker();
    await setScheduleDateTime(
      "2026-08-20T09:15:00+09:00",
      document,
      new Date("2026-07-31T16:00:00Z")
    );

    expect(navigationCount).toBe(0);
  });

  it("accepts a target offset that changes after crossing a DST boundary", async () => {
    const timezone = document.querySelector<HTMLElement>("#timezone-picker");
    const nextMonth =
      document.querySelector<HTMLButtonElement>("#next-month button");
    if (!(timezone && nextMonth)) {
      throw new Error("DST fixture の構築に失敗しました");
    }
    timezone.textContent = "(GMT-0400) New York";
    nextMonth.addEventListener("click", () => {
      timezone.textContent = "(GMT-0500) New York";
    });
    await openSchedulePicker();

    await expect(
      setScheduleDateTime(
        "2026-11-20T09:15:00-05:00",
        document,
        new Date("2026-10-31T16:00:00Z")
      )
    ).resolves.toBeUndefined();
  });

  it("rejects the same day and time from a different month before clicking", async () => {
    await setCommunityText("予約投稿本文");
    await openSchedulePicker();
    await setScheduleDateTime(
      "2026-07-20T09:15:00+09:00",
      document,
      new Date("2026-07-18T00:00:00+09:00")
    );

    await expect(
      clickPost({
        imageFilename: null,
        scheduledAt: "2026-08-20T09:15:00+09:00",
        text: "予約投稿本文",
      })
    ).rejects.toThrow("予約日");
  });

  it("does not treat a detached form as a successful reset", async () => {
    await setCommunityText("予約投稿本文");
    await openSchedulePicker();
    await setScheduleDateTime(
      "2026-07-20T09:15:00+09:00",
      document,
      new Date("2026-07-18T00:00:00+09:00")
    );
    const button = resolvePostButton();
    button.addEventListener("click", () => {
      document.querySelector("ytd-backstage-post-dialog-renderer")?.remove();
    });

    await expect(
      clickPost(
        {
          imageFilename: null,
          scheduledAt: "2026-07-20T09:15:00+09:00",
          text: "予約投稿本文",
        },
        document,
        20
      )
    ).rejects.toThrow("タイムアウト");
  });
});

describe("community DOM image seam", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <input type="file" name="Filedata" accept="image/*">
      <ytd-backstage-post-dialog-renderer>
        <ytd-commentbox id="commentbox">
          <ytd-backstage-multi-image-select-renderer>
            <div id="dropzone">
              <input type="file" name="Filedata" accept="image/*" tabindex="-1">
            </div>
          </ytd-backstage-multi-image-select-renderer>
        </ytd-commentbox>
      </ytd-backstage-post-dialog-renderer>`;
    const form = document.querySelector("ytd-backstage-post-dialog-renderer");
    const commentbox = document.querySelector("ytd-commentbox#commentbox");
    if (!(form && commentbox)) {
      throw new Error("image fixture の構築に失敗しました");
    }
    markVisible(form);
    markVisible(commentbox);
    class FakeDataTransfer {
      readonly files: File[] = [];
      readonly items = {
        add: (file: File) => {
          this.files.push(file);
        },
      };
    }
    Object.defineProperty(globalThis, "DataTransfer", {
      configurable: true,
      value: FakeDataTransfer,
    });
  });

  afterEach(() => {
    Reflect.deleteProperty(globalThis, "DataTransfer");
  });

  it("attaches the image and waits for its preview", async () => {
    const input = document.querySelector<HTMLInputElement>(
      "ytd-commentbox #dropzone input"
    );
    if (!input) {
      throw new Error("file input がありません");
    }
    Object.defineProperty(input, "files", {
      configurable: true,
      value: null,
      writable: true,
    });
    let changedFile: File | undefined;
    input.addEventListener("change", () => {
      changedFile = input.files?.[0];
      setTimeout(() => {
        const thumbnails = document.createElement("div");
        thumbnails.id = "thumbnail-images-container";
        thumbnails.innerHTML = `
          <ytd-backstage-multi-image-thumbnail-renderer selected>
            <img class="thumbnail-image" src="data:image/png;base64,cG5n">
          </ytd-backstage-multi-image-thumbnail-renderer>`;
        input.closest("ytd-commentbox")?.append(thumbnails);
      }, 0);
    });

    expect(resolveImageUploadInput()).toBe(input);
    await attachImage(new Blob(["png"], { type: "image/png" }), "main.png");

    expect(changedFile?.name).toBe("main.png");
    expect(changedFile?.type).toBe("image/png");
  });

  it("rejects a stale thumbnail that does not identify the new file", async () => {
    const input = resolveImageUploadInput();
    Object.defineProperty(input, "files", {
      configurable: true,
      value: null,
      writable: true,
    });
    const thumbnails = document.createElement("div");
    thumbnails.id = "thumbnail-images-container";
    thumbnails.innerHTML = `
      <ytd-backstage-multi-image-thumbnail-renderer selected>
        <img class="thumbnail-image" src="data:image/png;base64,b2xk">
      </ytd-backstage-multi-image-thumbnail-renderer>`;
    input.closest("ytd-commentbox")?.append(thumbnails);

    await expect(
      attachImage(
        new Blob(["png"], { type: "image/png" }),
        "main.png",
        document,
        20
      )
    ).rejects.toThrow("タイムアウト");
  });
});
