import { describe, expect, it, vi } from "vitest";

import type { CommunityPost } from "../../shared/api";
import { CommunitySubmissionUncertainError } from "../../shared/community-dom";
import { COMMUNITY_PHASE } from "../../shared/constants";
import {
  runCommunityPosts,
  type CommunityRunnerDependencies,
} from "../lib/runner";

const POSTS: CommunityPost[] = [
  {
    text: "first",
    scheduled_at: "2026-07-20T09:15:00+09:00",
    image_path: "collections/demo/main.png",
  },
  {
    text: "second",
    scheduled_at: "2026-07-21T09:15:00+09:00",
    image_path: null,
  },
  {
    text: "third",
    scheduled_at: "2026-07-22T09:15:00+09:00",
    image_path: "collections/demo/third.jpg",
  },
];

function createDependencies(events: string[]): CommunityRunnerDependencies {
  return {
    attachImage: vi.fn(async (_blob, filename) => {
      events.push(`image:${filename}`);
    }),
    cancelPostForm: vi.fn(async () => {
      events.push("cancel");
    }),
    clickPost: vi.fn(async ({ text }) => {
      events.push(`post:${text}`);
    }),
    fetchImage: vi.fn(async (_baseUrl, index) => {
      events.push(`fetch-image:${index}`);
      return new Blob([String(index)], {
        type: index === 0 ? "image/png" : "image/jpeg",
      });
    }),
    fetchPosts: vi.fn(async () => POSTS),
    openPostForm: vi.fn(async () => {
      events.push("open");
    }),
    openSchedulePicker: vi.fn(async () => {
      events.push("schedule-open");
    }),
    reportProgress: vi.fn(async ({ index, phase, total }) => {
      events.push(`progress:${index}:${total}:${phase}`);
    }),
    setCommunityText: vi.fn(async (text) => {
      events.push(`text:${text}`);
    }),
    setScheduleDateTime: vi.fn(async (scheduledAt) => {
      events.push(`schedule:${scheduledAt}`);
    }),
  };
}

describe("community runner", () => {
  it("processes exactly three posts sequentially and skips a missing image", async () => {
    const events: string[] = [];
    const dependencies = createDependencies(events);

    await runCommunityPosts("http://localhost:7873", dependencies);

    expect(events).toEqual([
      "fetch-image:0",
      "fetch-image:2",
      "open",
      `progress:0:3:${COMMUNITY_PHASE.INJECTING}`,
      "text:first",
      `progress:0:3:${COMMUNITY_PHASE.UPLOADING_IMAGE}`,
      "image:main.png",
      `progress:0:3:${COMMUNITY_PHASE.SCHEDULING}`,
      "schedule-open",
      "schedule:2026-07-20T09:15:00+09:00",
      `progress:0:3:${COMMUNITY_PHASE.POSTING}`,
      "post:first",
      `progress:0:3:${COMMUNITY_PHASE.DONE}`,
      "open",
      `progress:1:3:${COMMUNITY_PHASE.INJECTING}`,
      "text:second",
      `progress:1:3:${COMMUNITY_PHASE.SCHEDULING}`,
      "schedule-open",
      "schedule:2026-07-21T09:15:00+09:00",
      `progress:1:3:${COMMUNITY_PHASE.POSTING}`,
      "post:second",
      `progress:1:3:${COMMUNITY_PHASE.DONE}`,
      "open",
      `progress:2:3:${COMMUNITY_PHASE.INJECTING}`,
      "text:third",
      `progress:2:3:${COMMUNITY_PHASE.UPLOADING_IMAGE}`,
      "image:third.jpg",
      `progress:2:3:${COMMUNITY_PHASE.SCHEDULING}`,
      "schedule-open",
      "schedule:2026-07-22T09:15:00+09:00",
      `progress:2:3:${COMMUNITY_PHASE.POSTING}`,
      "post:third",
      `progress:2:3:${COMMUNITY_PHASE.DONE}`,
    ]);
  });

  it("fails before DOM mutation when the server does not return three posts", async () => {
    const dependencies = createDependencies([]);
    dependencies.fetchPosts = vi.fn(async () => POSTS.slice(0, 2));

    await expect(
      runCommunityPosts("http://localhost:7873", dependencies)
    ).rejects.toThrow("exactly 3");
    expect(dependencies.openPostForm).not.toHaveBeenCalled();
  });

  it("stops at the first failed step without retrying later posts", async () => {
    const events: string[] = [];
    const dependencies = createDependencies(events);
    dependencies.setScheduleDateTime = vi.fn(async () => {
      throw new Error("picker drift");
    });

    await expect(
      runCommunityPosts("http://localhost:7873", dependencies)
    ).rejects.toThrow("picker drift");
    expect(dependencies.clickPost).not.toHaveBeenCalled();
    expect(dependencies.setCommunityText).toHaveBeenCalledTimes(1);
    expect(dependencies.cancelPostForm).toHaveBeenCalledOnce();
  });

  it("honors cancellation between steps", async () => {
    const controller = new AbortController();
    const dependencies = createDependencies([]);
    dependencies.setCommunityText = vi.fn(async () => controller.abort());

    await expect(
      runCommunityPosts(
        "http://localhost:7873",
        dependencies,
        controller.signal
      )
    ).rejects.toThrow("停止");
    expect(dependencies.openSchedulePicker).not.toHaveBeenCalled();
    expect(dependencies.cancelPostForm).toHaveBeenCalledOnce();
  });

  it("prefetches every image before the first destructive DOM mutation", async () => {
    const dependencies = createDependencies([]);
    dependencies.fetchImage = vi.fn(async (_baseUrl, index) => {
      if (index === 2) {
        throw new Error("image server down");
      }
      return new Blob(["image"], { type: "image/png" });
    });

    await expect(
      runCommunityPosts("http://localhost:7873", dependencies)
    ).rejects.toThrow("image server down");
    expect(dependencies.openPostForm).not.toHaveBeenCalled();
    expect(dependencies.clickPost).not.toHaveBeenCalled();
  });

  it("reports partial completion and cleans the current draft after a later failure", async () => {
    const dependencies = createDependencies([]);
    vi.mocked(dependencies.setScheduleDateTime)
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new Error("second picker drift"));

    const result = runCommunityPosts("http://localhost:7873", dependencies);

    await expect(result).rejects.toMatchObject({
      completedCount: 1,
      requiresReconciliation: true,
    });
    expect(dependencies.clickPost).toHaveBeenCalledOnce();
    expect(dependencies.cancelPostForm).toHaveBeenCalledOnce();
  });

  it("cleans a clickPost preflight rejection and keeps a first-post retry safe", async () => {
    const dependencies = createDependencies([]);
    dependencies.clickPost = vi.fn(async () => {
      throw new Error("payload readback mismatch");
    });

    const result = runCommunityPosts("http://localhost:7873", dependencies);

    await expect(result).rejects.toMatchObject({
      completedCount: 0,
      requiresReconciliation: false,
    });
    expect(dependencies.cancelPostForm).toHaveBeenCalledOnce();
  });

  it("does not cancel when failure occurs after the destructive click boundary", async () => {
    const dependencies = createDependencies([]);
    dependencies.clickPost = vi.fn(async () => {
      throw new CommunitySubmissionUncertainError("reset timeout");
    });

    const result = runCommunityPosts("http://localhost:7873", dependencies);

    await expect(result).rejects.toMatchObject({
      completedCount: 0,
      requiresReconciliation: true,
    });
    expect(dependencies.cancelPostForm).not.toHaveBeenCalled();
  });
});
