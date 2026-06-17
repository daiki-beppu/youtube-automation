import {
  COLLECTIONS_ROUTE,
  DISTROKID_COLLECTIONS_ROUTE,
  DISTROKID_RELEASE_ROUTE,
  PLAYLISTS_CAPTURE_ROUTE,
  PROMPTS_ROUTE,
  VERSION_ROUTE,
} from "../../../../extensions/shared/constants.ts";
import type { ChannelConfig } from "../config/index.ts";
import { createCollectionServeFetchHandler } from "./router.ts";
import type { CollectionServeInput } from "./schema.ts";

type CollectionServeMode = "dir" | "single";

export const buildCollectionServeRoutes = (
  input: CollectionServeInput,
  distrokidEnabled: boolean,
  mode: CollectionServeMode
): string[] => {
  const playlistRoutes =
    input.playlistCaptureRoot === undefined ? [] : [PLAYLISTS_CAPTURE_ROUTE];
  const distrokidRoutes = distrokidEnabled
    ? [mode === "dir" ? DISTROKID_COLLECTIONS_ROUTE : DISTROKID_RELEASE_ROUTE]
    : [];
  return [
    VERSION_ROUTE,
    COLLECTIONS_ROUTE,
    PROMPTS_ROUTE,
    ...playlistRoutes,
    ...distrokidRoutes,
  ];
};

export { createCollectionServeFetchHandler };

export type { CollectionServeMode };
