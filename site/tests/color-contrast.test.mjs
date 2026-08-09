import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const TEXT_CONTRAST = 4.5;
const NON_TEXT_CONTRAST = 3;

const readStylesheetClosure = async () => {
  const html = await readFile(new URL("../dist/index.html", import.meta.url), "utf8");
  const inlineStyles = [...html.matchAll(/<style(?:\s[^>]*)?>([\s\S]*?)<\/style>/g)].map(
    (match) => match[1]
  );
  const linkedStyles = await Promise.all(
    [...html.matchAll(/<link[^>]+href=["']([^"']+\.css)["'][^>]*>/g)].map(
      (match) => readFile(new URL(`../dist${match[1]}`, import.meta.url), "utf8")
    )
  );
  return [...inlineStyles, ...linkedStyles].join("\n");
};

const rules = (css) =>
  [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((match) => ({
    selectors: match[1].split(",").map((selector) => selector.trim()),
    declarations: match[2],
  }));

const declarations = (text) =>
  Object.fromEntries(
    [...text.matchAll(/([\w-]+)\s*:\s*([^;]+)/g)].map((match) => [
      match[1],
      match[2].trim(),
    ])
  );

const declarationsFor = (cssRules, selector) =>
  Object.assign(
    {},
    ...cssRules
      .filter((rule) => rule.selectors.includes(selector))
      .map((rule) => declarations(rule.declarations))
  );

const customPropertiesFor = (cssRules, theme) => {
  const properties = {};
  for (const rule of cssRules) {
    const rootSelectors = rule.selectors.filter((selector) => selector.includes(":root"));
    const applies = rootSelectors.some((selector) => {
      const darkOnly = selector.includes("data-theme=dark");
      return theme === "dark" || !darkOnly;
    });
    if (!applies) continue;
    Object.assign(properties, declarations(rule.declarations));
  }
  return properties;
};

const parseHex = (value) => {
  const expanded = value.length <= 5
    ? [...value.slice(1)].map((digit) => digit.repeat(2)).join("")
    : value.slice(1);
  const channels = expanded.match(/.{2}/g).map((channel) => Number.parseInt(channel, 16) / 255);
  return [...channels.slice(0, 3), channels[3] ?? 1];
};

const linearToSrgb = (channel) =>
  channel <= 0.0031308 ? 12.92 * channel : 1.055 * channel ** (1 / 2.4) - 0.055;

const parseOklch = (value) => {
  const match = /^oklch\(([\d.]+)%\s+([\d.]+)\s+([\d.]+)(?:\s*\/\s*([\d.]+))?\)$/.exec(value);
  assert.notEqual(match, null, `未対応の OKLCH color: ${value}`);
  const lightness = Number(match[1]) / 100;
  const chroma = Number(match[2]);
  const hue = (Number(match[3]) * Math.PI) / 180;
  const a = chroma * Math.cos(hue);
  const b = chroma * Math.sin(hue);
  const l = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (lightness - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const linear = [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ];
  return [...linear.map((channel) => Math.min(1, Math.max(0, linearToSrgb(channel)))), Number(match[4] ?? 1)];
};

const mixWithTransparent = (color, percentage) => [
  color[0],
  color[1],
  color[2],
  color[3] * percentage,
];

const resolveColor = (value, properties) => {
  if (value === "transparent") return [0, 0, 0, 0];
  if (value.startsWith("#")) return parseHex(value);
  if (value.startsWith("oklch(")) return parseOklch(value);

  const variable = /^var\((--[\w-]+)\)$/.exec(value);
  if (variable) {
    assert.ok(properties[variable[1]], `未解決の CSS variable: ${variable[1]}`);
    return resolveColor(properties[variable[1]], properties);
  }

  const mix = /^color-mix\(in srgb,\s*(.+)\s+([\d.]+)%,\s*transparent\)$/.exec(value);
  assert.notEqual(mix, null, `未対応の CSS color: ${value}`);
  return mixWithTransparent(resolveColor(mix[1], properties), Number(mix[2]) / 100);
};

const composite = (foreground, background) => {
  const alpha = foreground[3] + background[3] * (1 - foreground[3]);
  return [
    ...foreground.slice(0, 3).map((channel, index) =>
      (channel * foreground[3] + background[index] * background[3] * (1 - foreground[3])) / alpha
    ),
    alpha,
  ];
};

const linearize = (channel) =>
  channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;

const luminance = (color) => {
  const [red, green, blue] = color.map(linearize);
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
};

const contrastRatio = (foreground, background) => {
  const foregroundLuminance = luminance(foreground);
  const backgroundLuminance = luminance(background);
  return (Math.max(foregroundLuminance, backgroundLuminance) + 0.05) /
    (Math.min(foregroundLuminance, backgroundLuminance) + 0.05);
};

const borderColor = (cssRules, selector) => {
  const rule = declarationsFor(cssRules, selector);
  if (rule["border-color"]) return rule["border-color"];
  const shorthand = /^1px solid (.+)$/.exec(rule.border);
  assert.notEqual(shorthand, null, `${selector} の border color を解決できません`);
  return shorthand[1];
};

const contrastPairs = (css, theme) => {
  const cssRules = rules(css);
  const properties = customPropertiesFor(cssRules, theme);
  const background = resolveColor(properties["--color-background"], properties);
  const main = resolveColor(properties["--release-main"], properties);
  const mainBackground = composite(resolveColor(properties["--release-main-bg"], properties), background);
  const extension = resolveColor(properties["--release-extension"], properties);
  const extensionBackground = composite(resolveColor(properties["--release-extension-bg"], properties), background);
  const defaultBorder = resolveColor(borderColor(cssRules, ".release-card"), properties);
  const hoverBorder = resolveColor(borderColor(cssRules, ".release-card:hover"), properties);

  return [
    { name: `${theme} body text`, foreground: resolveColor(properties["--color-foreground"], properties), background, threshold: TEXT_CONTRAST },
    { name: `${theme} muted text`, foreground: resolveColor(properties["--color-muted-foreground"], properties), background, threshold: TEXT_CONTRAST },
    { name: `${theme} accent`, foreground: main, background, threshold: TEXT_CONTRAST },
    { name: `${theme} link`, foreground: main, background, threshold: TEXT_CONTRAST },
    { name: `${theme} main badge`, foreground: main, background: mainBackground, threshold: TEXT_CONTRAST },
    { name: `${theme} extension badge`, foreground: extension, background: extensionBackground, threshold: TEXT_CONTRAST },
    { name: `${theme} card default border`, foreground: composite(defaultBorder, background), background, threshold: NON_TEXT_CONTRAST },
    { name: `${theme} card hover border`, foreground: composite(hoverBorder, background), background, threshold: NON_TEXT_CONTRAST },
  ];
};

const contrastFailures = (pairs) =>
  pairs.flatMap((pair) => {
    const ratio = contrastRatio(pair.foreground, pair.background);
    return ratio < pair.threshold
      ? [`${pair.name}: ${ratio.toFixed(2)}:1 (必要値 ${pair.threshold.toFixed(2)}:1)`]
      : [];
  });

test("production stylesheet の light / dark 配色が DADS contrast 基準を満たす", async () => {
  const css = await readStylesheetClosure();
  const pairs = ["light", "dark"].flatMap((theme) => contrastPairs(css, theme));

  assert.deepEqual(contrastFailures(pairs), []);
});

test("contrast 基準未達は pair 名・実測値・必要値で診断する", () => {
  const failures = contrastFailures([
    {
      name: "light sample text",
      foreground: [1, 1, 1, 1],
      background: [1, 1, 1, 1],
      threshold: TEXT_CONTRAST,
    },
  ]);

  assert.deepEqual(failures, ["light sample text: 1.00:1 (必要値 4.50:1)"]);
});
