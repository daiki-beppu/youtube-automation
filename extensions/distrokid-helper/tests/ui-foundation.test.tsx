import {
  Alert,
  AlertDescription,
  Button,
  buttonVariants,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  FieldLabel,
} from "@youtube-automation/ui";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

// Shared cn / variant / size matrices live in suno-helper/tests/ui-foundation.test.tsx.
// Keep this consumer's React rendering and DistroKid-specific props/slots here.
describe("DistroKid shared UI integration", () => {
  it("Button はこの consumer の React で追加 class・button props を反映する", () => {
    const html = renderToStaticMarkup(
      createElement(Button, { className: "w-full", disabled: true }, "保存")
    );

    expect(html).toContain('data-slot="button"');
    expect(html).toContain('data-variant="default"');
    expect(html).toContain('data-size="default"');
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
