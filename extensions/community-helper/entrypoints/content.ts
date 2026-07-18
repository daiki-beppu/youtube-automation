import { checkServerCompatibility } from "../../shared/api";
import { COMMUNITY_PHASE } from "../../shared/constants";
import { MANIFEST_CONTENT_SCRIPT_MATCHES } from "../lib/manifest";
import { onMessage, sendMessage } from "../lib/messaging";

export default defineContentScript({
  matches: [...MANIFEST_CONTENT_SCRIPT_MATCHES],
  main() {
    onMessage("checkCompatibility", ({ data }) =>
      checkServerCompatibility(data.baseUrl, data.extensionVersion)
    );
    onMessage("run", async () => {
      // CH-08 replaces this scaffold with fetch + DOM injection.
      await Promise.all(
        ([0, 1, 2] as const).map((index) =>
          sendMessage("contentProgress", {
            index,
            phase: COMMUNITY_PHASE.INJECTING,
            message: "投稿を準備中",
          })
        )
      );
    });
    onMessage("stop", () => undefined);
  },
});
