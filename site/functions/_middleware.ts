type SiteEnvironment = "preview" | "production";

export interface OnboardingGateEnv {
  readonly SITE_ENVIRONMENT?: SiteEnvironment;
  readonly ONBOARDING_KEY?: string;
}

interface OnboardingGateContext {
  readonly request: Request;
  readonly env: OnboardingGateEnv;
  next(): Promise<Response>;
}

const PROTECTED_PATHS: readonly string[] = [
  "/onboarding",
  "/onboarding/",
  "/onboarding.md",
  "/onboarding.mdx",
];

async function keysMatch(provided: string, expected: string): Promise<boolean> {
  const encoder = new TextEncoder();
  const [providedHash, expectedHash] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(provided)),
    crypto.subtle.digest("SHA-256", encoder.encode(expected)),
  ]);
  const providedBytes = new Uint8Array(providedHash);
  const expectedBytes = new Uint8Array(expectedHash);
  let difference = 0;
  for (let index = 0; index < providedBytes.length; index += 1) {
    difference |= providedBytes[index] ^ expectedBytes[index];
  }
  return difference === 0;
}

export async function onRequest(context: OnboardingGateContext): Promise<Response> {
  if (context.env.SITE_ENVIRONMENT === "preview") {
    return context.next();
  }

  const url = new URL(context.request.url);
  if (!PROTECTED_PATHS.includes(url.pathname)) {
    return context.next();
  }

  const expectedKey = context.env.ONBOARDING_KEY;
  const providedKey = url.searchParams.get("key");
  if (
    expectedKey !== undefined &&
    expectedKey.length > 0 &&
    providedKey !== null &&
    providedKey.length > 0 &&
    (await keysMatch(providedKey, expectedKey))
  ) {
    return context.next();
  }

  return Response.redirect(new URL("/", url.origin), 302);
}
