import {
  Alert,
  alertVariants,
  Button,
  buttonVariants,
  Card,
  CardContent,
  CardHeader,
  Checkbox,
  cn,
  Field,
  FieldContent,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSeparator,
  FieldSet,
  FieldTitle,
  Select,
  SelectTrigger,
  SelectValue,
  ScrollArea,
} from "@youtube-automation/ui";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

const variantMarkers = {
  default: ["bg-primary", "text-primary-foreground"],
  destructive: ["bg-destructive/10", "text-destructive"],
  info: ["border-info-border", "bg-info-background", "text-info-foreground"],
  outline: ["border", "bg-background"],
  secondary: ["bg-secondary", "text-secondary-foreground"],
  success: [
    "border-success-border",
    "bg-success-background",
    "text-success-foreground",
  ],
  warning: [
    "border-warning-border",
    "bg-warning-background",
    "text-warning-foreground",
  ],
  ghost: ["hover:bg-muted"],
  link: ["underline-offset-4", "hover:underline"],
} as const;

const sizeMarkers = {
  default: ["h-9", "px-2.5"],
  xs: ["h-6", "text-xs"],
  sm: ["h-8", "px-2.5"],
  lg: ["h-10", "px-2.5"],
  icon: ["size-9"],
  "icon-xs": ["size-6"],
  "icon-sm": ["size-8"],
  "icon-lg": ["size-10"],
} as const;

describe("shadcn/ui foundation", () => {
  it("ScrollArea は Base UI viewport を公開し、viewport class を反映する", () => {
    const html = renderToStaticMarkup(
      createElement(
        ScrollArea,
        { viewportClassName: "max-h-48" },
        createElement("div", null, "content")
      )
    );

    expect(html).toContain('data-slot="scroll-area"');
    expect(html).toContain('data-slot="scroll-area-viewport"');
    expect(html).toContain("max-h-48");
  });

  it("cn は条件付き class を連結し、競合する Tailwind class は後勝ちで統合する", () => {
    expect(
      cn("px-2", { hidden: false }, ["font-medium", { block: true }], "px-4")
    ).toBe("font-medium block px-4");
  });

  it.each(Object.entries(variantMarkers))(
    "Button variant %s は対応する class を生成する",
    (variant, markers) => {
      const classes = buttonVariants({
        variant: variant as keyof typeof variantMarkers,
      }).split(" ");
      expect(classes).toEqual(expect.arrayContaining([...markers]));
    }
  );

  it.each(Object.entries(sizeMarkers))(
    "Button size %s は対応する class を生成する",
    (size, markers) => {
      const classes = buttonVariants({
        size: size as keyof typeof sizeMarkers,
      }).split(" ");
      expect(classes).toEqual(expect.arrayContaining([...markers]));
    }
  );

  it("Button は default variant/size と追加 class・button props を反映する", () => {
    const html = renderToStaticMarkup(
      createElement(Button, { className: "w-full", disabled: true }, "保存")
    );

    expect(html).toContain('data-slot="button"');
    expect(html).toContain('data-variant="default"');
    expect(html).toContain('data-size="default"');
    for (const marker of variantMarkers.default) expect(html).toContain(marker);
    expect(html).toContain("h-9 gap-1.5 px-2.5");
    expect(html).toContain("w-full");
    expect(html).toContain("disabled");
    expect(html).toContain(">保存</button>");
  });

  it("link は buttonVariants を plain anchor に適用してnative semanticsを保つ", () => {
    const html = renderToStaticMarkup(
      createElement(
        "a",
        { href: "#review", className: buttonVariants({ variant: "link" }) },
        "確認"
      )
    );

    expect(html.startsWith("<a ")).toBe(true);
    expect(html).toContain('href="#review"');
    expect(html).not.toContain('role="button"');
    for (const marker of variantMarkers.link) expect(html).toContain(marker);
    expect(html).toContain(">確認</a>");
  });

  it("Button render は nested interactive element を作らず非button要素へ button semantics を付与する", () => {
    const html = renderToStaticMarkup(
      createElement(
        Button,
        { render: createElement("div"), nativeButton: false },
        "詳細"
      )
    );

    expect(html.startsWith("<div ")).toBe(true);
    expect(html).toContain('role="button"');
    expect(html).toContain('tabindex="0"');
    expect(html).not.toContain("<button");
    expect(html).toContain(">詳細</div>");
  });

  it("FieldLabel は checkbox cardをnested buttonなしで構成する", () => {
    const html = renderToStaticMarkup(
      createElement(
        FieldLabel,
        { className: buttonVariants({ variant: "outline" }) },
        createElement("input", { type: "checkbox" }),
        "選択"
      )
    );

    expect(html.startsWith("<label ")).toBe(true);
    expect(html).toContain('data-slot="field-label"');
    expect(html).not.toContain("<button");
  });

  it("Field は公式の set/group/content/description/error composition を公開する", () => {
    const html = renderToStaticMarkup(
      createElement(
        FieldSet,
        null,
        createElement(FieldLegend, null, "通知"),
        createElement(
          FieldGroup,
          null,
          createElement(
            Field,
            null,
            createElement(FieldLabel, null, "メール"),
            createElement(
              FieldContent,
              null,
              createElement(FieldTitle, null, "配信先"),
              createElement(FieldDescription, null, "受信先を選択")
            ),
            createElement(FieldSeparator, null, "または"),
            createElement(FieldError, { errors: [{ message: "必須です" }] })
          )
        )
      )
    );

    for (const slot of [
      "field-set",
      "field-legend",
      "field-group",
      "field",
      "field-label",
      "field-content",
      "field-title",
      "field-description",
      "field-separator",
      "field-error",
    ]) {
      expect(html).toContain(`data-slot="${slot}"`);
    }
    expect(html).toContain('role="alert"');
    expect(html).toContain("必須です");
  });

  it("Checkbox は indeterminate と invalid の Base UI state を保持する", () => {
    const html = renderToStaticMarkup(
      createElement(Checkbox, {
        indeterminate: true,
        "aria-invalid": true,
        "aria-label": "一部選択",
      })
    );

    expect(html).toContain('data-slot="checkbox"');
    expect(html).toContain("data-indeterminate");
    expect(html).toContain('aria-invalid="true"');
    expect(html).toContain('aria-label="一部選択"');
  });

  it("Card は shell/header/content の slot と追加 props を実 DOM に反映する", () => {
    const html = renderToStaticMarkup(
      createElement(
        Card,
        { className: "w-[360px]", "aria-label": "Suno Helper" },
        createElement(
          CardHeader,
          { className: "cursor-grab", layout: "stack" },
          "header"
        ),
        createElement(CardContent, { className: "p-0" }, "content")
      )
    );

    expect(html.startsWith("<div ")).toBe(true);
    expect(html).toContain('data-slot="card"');
    expect(html).toContain('aria-label="Suno Helper"');
    expect(html).toContain("w-[360px]");
    expect(html).toContain('data-slot="card-header"');
    expect(html).toContain('data-layout="stack"');
    expect(html).toContain("cursor-grab");
    expect(html).toContain('data-slot="card-content"');
    expect(html).toContain("p-0");
  });

  it("Select は native wrapper ではなく shadcn/Base UI の root・trigger・value を構成する", () => {
    const html = renderToStaticMarkup(
      createElement(
        Select,
        { value: "mp3" },
        createElement(
          SelectTrigger,
          { "aria-label": "DL 形式" },
          createElement(SelectValue)
        )
      )
    );

    expect(html).toContain('data-slot="select-trigger"');
    expect(html).toContain('role="combobox"');
    expect(html).toContain('aria-label="DL 形式"');
    expect(html).not.toContain('data-slot="select"');
  });

  it.each([
    ["default", ["bg-card", "text-card-foreground"]],
    [
      "info",
      ["border-info-border", "bg-info-background", "text-info-foreground"],
    ],
    [
      "warning",
      [
        "border-warning-border",
        "bg-warning-background",
        "text-warning-foreground",
      ],
    ],
    [
      "success",
      [
        "border-success-border",
        "bg-success-background",
        "text-success-foreground",
      ],
    ],
    [
      "destructive",
      [
        "border-destructive-border",
        "bg-destructive-background",
        "text-destructive-foreground",
      ],
    ],
  ] as const)(
    "Alert variant %s は対応する class を生成する",
    (variant, markers) => {
      const classes = alertVariants({
        variant,
        appearance: variant === "destructive" ? "filled" : "subtle",
      }).split(" ");
      expect(classes).toEqual(expect.arrayContaining([...markers]));
    }
  );

  it("Alert は role を暗黙追加せず、指定された semantic role と props を透過する", () => {
    const html = renderToStaticMarkup(
      createElement(
        Alert,
        {
          variant: "destructive",
          appearance: "filled",
          role: "status",
          "aria-live": "polite",
        },
        "失敗"
      )
    );

    expect(html).toContain('data-slot="alert"');
    expect(html).toContain('data-variant="destructive"');
    expect(html).toContain('data-appearance="filled"');
    expect(html).toContain('role="status"');
    expect(html).toContain('aria-live="polite"');
    expect(html).toContain(">失敗</div>");
  });
});
