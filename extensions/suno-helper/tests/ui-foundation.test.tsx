import {
  Alert,
  alertVariants,
  Button,
  ButtonSlot,
  buttonVariants,
  Card,
  CardContent,
  CardHeader,
  cn,
  Select,
  SelectTrigger,
  SelectValue,
} from "@youtube-automation/ui";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

const variantMarkers = {
  default: ["bg-primary", "text-primary-foreground"],
  destructive: ["bg-destructive", "text-white"],
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
  ghost: ["hover:bg-accent"],
  link: ["underline-offset-4", "hover:underline"],
} as const;

const sizeMarkers = {
  default: ["h-9", "px-4"],
  sm: ["h-8", "px-3"],
  lg: ["h-10", "px-6"],
  icon: ["size-9"],
} as const;

describe("shadcn/ui foundation", () => {
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
    expect(html).toContain("h-9 px-4 py-2");
    expect(html).toContain("w-full");
    expect(html).toContain("disabled");
    expect(html).toContain(">保存</button>");
  });

  it("ButtonSlot は Radix Slot 経由で子要素を描画する", () => {
    const html = renderToStaticMarkup(
      createElement(
        ButtonSlot,
        { variant: "link" },
        createElement("a", { href: "#review" }, "確認")
      )
    );

    expect(html.startsWith("<a ")).toBe(true);
    expect(html).toContain('href="#review"');
    expect(html).toContain('data-variant="link"');
    for (const marker of variantMarkers.link) expect(html).toContain(marker);
    expect(html).toContain(">確認</a>");
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

  it("Select は native wrapper ではなく shadcn/Radix の root・trigger・value を構成する", () => {
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
