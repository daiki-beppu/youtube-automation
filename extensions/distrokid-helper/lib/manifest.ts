export const MANIFEST_PERMISSIONS = ["storage", "activeTab"] as const;

export const MANIFEST_HOST_PERMISSIONS = ["*://*.distrokid.com/*"] as const;

export const MANIFEST_CONTENT_SCRIPT_MATCHES = [
  "*://*.distrokid.com/new*",
] as const;
