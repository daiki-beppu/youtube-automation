// @vitest-environment jsdom

import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
  Checkbox,
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Field,
  FieldContent,
  FieldDescription,
  FieldError,
  FieldLabel,
  FieldTitle,
  Input,
  Label,
  RadioGroup,
  RadioGroupItem,
  ScrollArea,
  Switch,
} from "@youtube-automation/ui";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("shared UI runtime primitives", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.restoreAllMocks();
  });

  it("mounts Card sm/stack and every public slot with native props", async () => {
    await act(async () =>
      root.render(
        <Card size="sm" id="card" aria-label="release card">
          <CardHeader layout="stack">
            <CardTitle>Title</CardTitle>
            <CardDescription>Description</CardDescription>
            <CardAction>Action</CardAction>
          </CardHeader>
          <CardContent>Content</CardContent>
          <CardFooter>Footer</CardFooter>
        </Card>
      )
    );

    const card = container.querySelector<HTMLElement>("#card")!;
    expect(card.dataset.size).toBe("sm");
    expect(card.getAttribute("aria-label")).toBe("release card");
    expect(
      card.querySelector<HTMLElement>('[data-slot="card-header"]')!.dataset
        .layout
    ).toBe("stack");
    for (const slot of [
      "card-title",
      "card-description",
      "card-action",
      "card-content",
      "card-footer",
    ]) {
      expect(card.querySelector(`[data-slot="${slot}"]`)).not.toBeNull();
    }
  });

  it("mounts Empty media/slots and Field orientation/error branches", async () => {
    await act(async () =>
      root.render(
        <>
          <Empty data-probe="empty">
            <EmptyHeader>
              <EmptyMedia variant="icon">◎</EmptyMedia>
              <EmptyTitle>Nothing here</EmptyTitle>
              <EmptyDescription>Description</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>Action</EmptyContent>
          </Empty>
          <Field orientation="horizontal" data-invalid="true">
            <FieldLabel htmlFor="native-input">Label</FieldLabel>
            <FieldContent>
              <FieldTitle>Field title</FieldTitle>
              <FieldDescription>Field description</FieldDescription>
              <FieldError
                errors={[
                  { message: "Required" },
                  { message: "Required" },
                  { message: "Invalid" },
                ]}
              />
            </FieldContent>
          </Field>
        </>
      )
    );

    const empty = container.querySelector<HTMLElement>('[data-slot="empty"]')!;
    expect(empty.dataset.probe).toBe("empty");
    expect(
      empty.querySelector<HTMLElement>('[data-slot="empty-icon"]')!.dataset
        .variant
    ).toBe("icon");
    for (const slot of [
      "empty-header",
      "empty-title",
      "empty-description",
      "empty-content",
    ]) {
      expect(empty.querySelector(`[data-slot="${slot}"]`)).not.toBeNull();
    }
    const field = container.querySelector<HTMLElement>('[data-slot="field"]')!;
    expect(field.dataset.orientation).toBe("horizontal");
    expect(field.dataset.invalid).toBe("true");
    expect(field.querySelector('[role="alert"]')?.textContent).toBe(
      "RequiredInvalid"
    );
  });

  it("passes native Input and Label props and preserves label association", async () => {
    await act(async () =>
      root.render(
        <>
          <Label htmlFor="email" title="Email label" className="custom-label">
            Email
          </Label>
          <Input
            id="email"
            type="email"
            disabled
            aria-invalid="true"
            maxLength={32}
            data-probe="input"
          />
        </>
      )
    );
    const label = container.querySelector<HTMLLabelElement>("label")!;
    const input = container.querySelector<HTMLInputElement>("input")!;
    expect(label.htmlFor).toBe("email");
    expect(label.title).toBe("Email label");
    expect(label.classList).toContain("custom-label");
    expect(input.type).toBe("email");
    expect(input.disabled).toBe(true);
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(input.maxLength).toBe(32);
    expect(input.dataset.probe).toBe("input");
  });

  it("mounts Checkbox checked/indeterminate/disabled states and indicator", async () => {
    await act(async () =>
      root.render(
        <>
          <Checkbox aria-label="normal checkbox" />
          <Checkbox aria-label="mixed checkbox" indeterminate disabled />
        </>
      )
    );
    const normal = container.querySelector<HTMLElement>(
      '[aria-label="normal checkbox"]'
    )!;
    const mixed = container.querySelector<HTMLElement>(
      '[aria-label="mixed checkbox"]'
    )!;
    await act(async () => normal.click());
    expect(normal.hasAttribute("data-checked")).toBe(true);
    expect(
      normal.querySelector('[data-slot="checkbox-indicator"]')
    ).not.toBeNull();
    expect(mixed.hasAttribute("data-indeterminate")).toBe(true);
    expect(mixed.hasAttribute("data-disabled")).toBe(true);
    await act(async () => mixed.click());
    expect(mixed.hasAttribute("data-indeterminate")).toBe(true);
  });

  it("opens and closes Collapsible through its mounted trigger and panel", async () => {
    await act(async () =>
      root.render(
        <Collapsible>
          <CollapsibleTrigger>Toggle details</CollapsibleTrigger>
          <CollapsibleContent>Panel content</CollapsibleContent>
        </Collapsible>
      )
    );
    const trigger = container.querySelector<HTMLButtonElement>(
      '[data-slot="collapsible-trigger"]'
    )!;
    expect(
      container.querySelector('[data-slot="collapsible-content"]')
    ).toBeNull();
    await act(async () => trigger.click());
    expect(
      container.querySelector('[data-slot="collapsible-content"]')?.textContent
    ).toBe("Panel content");
    await act(async () => trigger.click());
    expect(
      container.querySelector('[data-slot="collapsible-content"]')
    ).toBeNull();
  });

  it("mounts RadioGroup selection/disabled/invalid/indicator states", async () => {
    const onValueChange = vi.fn();
    await act(async () =>
      root.render(
        <RadioGroup
          defaultValue="a"
          onValueChange={onValueChange}
          aria-invalid="true"
        >
          <RadioGroupItem value="a" aria-label="A" />
          <RadioGroupItem value="b" aria-label="B" disabled />
          <RadioGroupItem value="c" aria-label="C" />
        </RadioGroup>
      )
    );
    const a = container.querySelector<HTMLElement>('[aria-label="A"]')!;
    const b = container.querySelector<HTMLElement>('[aria-label="B"]')!;
    const c = container.querySelector<HTMLElement>('[aria-label="C"]')!;
    expect(a.hasAttribute("data-checked")).toBe(true);
    expect(
      a.querySelector('[data-slot="radio-group-indicator"]')
    ).not.toBeNull();
    expect(b.hasAttribute("data-disabled")).toBe(true);
    await act(async () => b.click());
    expect(a.hasAttribute("data-checked")).toBe(true);
    await act(async () => c.click());
    expect(c.hasAttribute("data-checked")).toBe(true);
    expect(onValueChange).toHaveBeenLastCalledWith(
      "c",
      expect.objectContaining({ reason: expect.anything() })
    );
    expect(
      container
        .querySelector('[data-slot="radio-group"]')
        ?.getAttribute("aria-invalid")
    ).toBe("true");
  });

  it("mounts ScrollArea viewport, vertical/horizontal scrollbars, thumbs, and corner", async () => {
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(100);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(100);
    vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockReturnValue(200);
    vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(200);
    await act(async () =>
      root.render(
        <ScrollArea
          scrollbars="both"
          viewportClassName="viewport-probe"
          aria-label="scroll area"
        >
          <div style={{ width: 1000, height: 1000 }}>Scrollable</div>
        </ScrollArea>
      )
    );
    await act(async () => {
      await Promise.resolve();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(
      container.querySelector('[data-slot="scroll-area-viewport"]')?.classList
    ).toContain("viewport-probe");
    expect(
      container.querySelectorAll('[data-slot="scroll-area-scrollbar"]')
    ).toHaveLength(2);
    expect(
      container.querySelector(
        '[data-slot="scroll-area-scrollbar"][data-orientation="vertical"]'
      )
    ).not.toBeNull();
    expect(
      container.querySelector(
        '[data-slot="scroll-area-scrollbar"][data-orientation="horizontal"]'
      )
    ).not.toBeNull();
    expect(
      container.querySelectorAll('[data-slot="scroll-area-thumb"]')
    ).toHaveLength(2);
    expect(
      container.querySelector('[data-slot="scroll-area-corner"]')
    ).not.toBeNull();
  });

  it("mounts Switch checked/disabled/size/thumb and toggles only enabled state", async () => {
    await act(async () =>
      root.render(
        <>
          <Switch aria-label="normal switch" size="sm" />
          <Switch aria-label="disabled switch" checked disabled />
        </>
      )
    );
    const normal = container.querySelector<HTMLElement>(
      '[aria-label="normal switch"]'
    )!;
    const disabled = container.querySelector<HTMLElement>(
      '[aria-label="disabled switch"]'
    )!;
    expect(normal.dataset.size).toBe("sm");
    expect(normal.querySelector('[data-slot="switch-thumb"]')).not.toBeNull();
    await act(async () => normal.click());
    expect(normal.hasAttribute("data-checked")).toBe(true);
    expect(disabled.hasAttribute("data-checked")).toBe(true);
    expect(disabled.hasAttribute("data-disabled")).toBe(true);
    await act(async () => disabled.click());
    expect(disabled.hasAttribute("data-checked")).toBe(true);
  });
});
