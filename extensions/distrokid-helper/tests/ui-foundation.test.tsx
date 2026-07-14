import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Button, ButtonSlot, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const variantMarkers = {
  default: ["bg-primary", "text-primary-foreground"],
  destructive: ["bg-destructive", "text-white"],
  outline: ["border", "bg-background"],
  secondary: ["bg-secondary", "text-secondary-foreground"],
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
    expect(cn("px-2", { hidden: false }, ["font-medium", { block: true }], "px-4")).toBe("font-medium block px-4");
  });

  it.each(Object.entries(variantMarkers))("Button variant %s は対応する class を生成する", (variant, markers) => {
    const classes = buttonVariants({ variant: variant as keyof typeof variantMarkers }).split(" ");
    expect(classes).toEqual(expect.arrayContaining([...markers]));
  });

  it.each(Object.entries(sizeMarkers))("Button size %s は対応する class を生成する", (size, markers) => {
    const classes = buttonVariants({ size: size as keyof typeof sizeMarkers }).split(" ");
    expect(classes).toEqual(expect.arrayContaining([...markers]));
  });

  it("Button は default variant/size と追加 class・button props を反映する", () => {
    const html = renderToStaticMarkup(createElement(Button, { className: "w-full", disabled: true }, "保存"));

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
      createElement(ButtonSlot, { variant: "link" }, createElement("a", { href: "#review" }, "確認")),
    );

    expect(html.startsWith("<a ")).toBe(true);
    expect(html).toContain('href="#review"');
    expect(html).toContain('data-variant="link"');
    for (const marker of variantMarkers.link) expect(html).toContain(marker);
    expect(html).toContain(">確認</a>");
  });
});
