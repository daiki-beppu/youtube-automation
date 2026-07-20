import {
  Alert,
  AlertDescription,
  Button,
  buttonVariants,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  cn,
  FieldLabel,
} from "@youtube-automation/ui";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

const variantMarkers = {
  default: ["bg-primary", "text-primary-foreground"],
  destructive: ["bg-destructive/10", "text-destructive"],
  outline: ["border", "bg-background"],
  secondary: ["bg-secondary", "text-secondary-foreground"],
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

  it("FieldLabel はnative label semanticsを保つ", () => {
    const html = renderToStaticMarkup(
      createElement(
        FieldLabel,
        null,
        createElement("input", { type: "checkbox" })
      )
    );

    expect(html.startsWith("<label ")).toBe(true);
    expect(html).toContain('data-slot="field-label"');
    expect(html).not.toContain('role="button"');
  });

  it("Alert は variant、追加 class、標準 DOM props と description slot を反映する", () => {
    const html = renderToStaticMarkup(
      createElement(
        Alert,
        {
          variant: "destructive",
          className: "border-red-200",
          role: "alert",
          "aria-label": "失敗",
        },
        createElement(AlertDescription, null, "処理に失敗しました")
      )
    );

    expect(html).toContain('data-slot="alert"');
    expect(html).toContain('data-variant="destructive"');
    expect(html).toContain('data-appearance="subtle"');
    expect(html).toContain('role="alert"');
    expect(html).toContain('aria-label="失敗"');
    expect(html).toContain("text-destructive");
    expect(html).toContain("border-red-200");
    expect(html).toContain('data-slot="alert-description"');
    expect(html).toContain("処理に失敗しました");
  });

  it("Card は追加 class・標準 DOM props と header/title/content slot を反映する", () => {
    const html = renderToStaticMarkup(
      createElement(
        Card,
        { className: "gap-2", id: "release-review" },
        createElement(
          CardHeader,
          null,
          createElement(CardTitle, null, "アルバム")
        ),
        createElement(CardContent, null, "メタデータ")
      )
    );

    expect(html).toContain('data-slot="card"');
    expect(html).toContain('id="release-review"');
    expect(html).toContain("gap-2");
    expect(html).toContain('data-slot="card-header"');
    expect(html).toContain('data-layout="grid"');
    expect(html).toContain('data-slot="card-title"');
    expect(html).toContain('data-slot="card-content"');
    expect(html).toContain("アルバム");
    expect(html).toContain("メタデータ");
  });
});
