export const MANIFEST_PERMISSIONS = ["activeTab"] as const;

export const MANIFEST_HOST_PERMISSIONS = ["*://studio.youtube.com/*"] as const;

export const MANIFEST_CONTENT_SCRIPT_MATCHES = [
  "*://studio.youtube.com/*",
] as const;
