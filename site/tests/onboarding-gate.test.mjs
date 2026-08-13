import assert from "node:assert/strict";
import test from "node:test";

import { readFile } from "node:fs/promises";

import { onRequest } from "../functions/_middleware.ts";

const ORIGIN = "https://docs.example.test";
const PROTECTED_PATHS = [
  "/onboarding",
  "/onboarding/",
  "/onboarding.md",
  "/onboarding.mdx",
];
const PUBLIC_OPERATOR_PATHS = [
  "/oauth-setup/",
  "/chrome-extension-install-guide/",
  "/features/",
  "/workflow-cheatsheet/",
  "/dashboard/",
  "/channel-workspace-migration/",
];

async function invoke({
  path = "/onboarding/",
  siteEnvironment = "production",
  onboardingKey = "correct-key",
} = {}) {
  let nextCount = 0;
  const nextResponse = new Response(`asset:${path}`, { status: 200 });
  const env = {};
  if (siteEnvironment !== null) env.SITE_ENVIRONMENT = siteEnvironment;
  if (onboardingKey !== null) env.ONBOARDING_KEY = onboardingKey;

  const response = await onRequest({
    request: new Request(`${ORIGIN}${path}`),
    env,
    next: async () => {
      nextCount += 1;
      return nextResponse;
    },
  });
  return { response, nextCount, nextResponse };
}

async function assertRedirect(result) {
  assert.equal(result.nextCount, 0);
  assert.equal(result.response.status, 302);
  assert.equal(result.response.headers.get("location"), `${ORIGIN}/`);
  assert.equal(await result.response.text(), "");
}

async function assertPassedThrough(result) {
  assert.equal(result.nextCount, 1);
  assert.equal(result.response, result.nextResponse);
  assert.match(await result.response.text(), /^asset:/);
}

test("production は保護対象4パスだけを正しいkeyで後段へ渡す", async () => {
  for (const path of PROTECTED_PATHS) {
    await assertPassedThrough(await invoke({ path: `${path}?key=correct-key` }));
  }
});

test("production は保護対象4パスの誤った・欠落・空keyを同一originのrootへredirectする", async () => {
  for (const path of PROTECTED_PATHS) {
    for (const suffix of ["", "?key=wrong-key", "?key="]) {
      await assertRedirect(await invoke({ path: `${path}${suffix}` }));
    }
  }
});

test("production はsecretが欠落または空なら正しい候補keyでもfail closedになる", async () => {
  for (const onboardingKey of [null, ""]) {
    await assertRedirect(
      await invoke({
        path: "/onboarding/?key=correct-key&return=https://attacker.example/",
        onboardingKey,
      }),
    );
  }
});

test("環境が欠落・未知・productionなら保護し、exact previewだけをkeyなしで通す", async () => {
  for (const siteEnvironment of [null, "staging", "Preview", "production"]) {
    await assertRedirect(await invoke({ siteEnvironment }));
  }
  await assertPassedThrough(await invoke({ siteEnvironment: "preview" }));
});

test("preview はsecretの状態や保護対象pathに関係なく後段へ一度だけ渡す", async () => {
  for (const path of PROTECTED_PATHS) {
    await assertPassedThrough(
      await invoke({ path, siteEnvironment: "preview", onboardingKey: null }),
    );
  }
});

test("公開operator 6 routeと大小文字・prefix・suffix境界は常に後段へ渡す", async () => {
  const boundaries = [
    "/Onboarding",
    "/ONBOARDING.md",
    "/onboarding.html",
    "/onboarding/child",
    "/onboarding-md",
    "/onboarding.mdx/child",
  ];
  for (const path of [...PUBLIC_OPERATOR_PATHS, ...boundaries]) {
    await assertPassedThrough(
      await invoke({ path, siteEnvironment: null, onboardingKey: null }),
    );
  }
});

test("deploy文書とADRはruntime binding・secret rotation・CF_PAGES_BRANCH非依存を固定する", async () => {
  const deployment = await readFile(
    new URL("../../docs/release-notes-deployment.md", import.meta.url),
    "utf8",
  );
  const adr = await readFile(
    new URL("../../docs/adr/0023-release-notes-site.md", import.meta.url),
    "utf8",
  );

  for (const contract of [deployment, adr]) {
    assert.match(contract, /SITE_ENVIRONMENT/);
    assert.match(contract, /CF_PAGES_BRANCH/);
    assert.match(contract, /runtime[^\n]*(?:使わない|判定)/i);
    assert.match(contract, /(?:retry|再 deployment|新規 deployment)/i);
    assert.match(contract, /commit (?:は?不要|なし)/i);
  }
  assert.match(deployment, /ONBOARDING_KEY/);
  assert.match(deployment, /Production と\nPreview の両 scope/);
  assert.match(deployment, /(?:漏えい|漏れる)/);
});
