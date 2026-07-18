import { SERVER_HOST_PERMISSIONS } from "../../shared/constants";

export const MANIFEST_PERMISSIONS = ["activeTab"] as const;

export const MANIFEST_HOST_PERMISSIONS = [...SERVER_HOST_PERMISSIONS] as const;

export const MANIFEST_CONTENT_SCRIPT_MATCHES = [
  "https://www.youtube.com/channel/*/posts*",
] as const;
