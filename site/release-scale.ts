export type ReleaseScale = "major" | "minor";

export interface ReleaseForScale {
  released_at: Date;
  version: string;
}

export interface ReleaseScaleGroup<T extends ReleaseForScale> {
  label: string;
  releases: T[];
  scale: ReleaseScale;
}

export const releaseScaleLabels: Record<ReleaseScale, string> = {
  major: "大きいアップデート",
  minor: "小さいアップデート",
};

const releaseScales: readonly ReleaseScale[] = ["major", "minor"];
const supportedVersion = /^(?:ext-)?v\d+\.\d+\.(\d+)$/;

export function scaleFromVersion(version: string): ReleaseScale {
  const match = supportedVersion.exec(version);
  if (match === null) {
    throw new Error(`Unsupported release version: ${version}`);
  }

  return Number(match[1]) === 0 ? "major" : "minor";
}

export function groupReleasesByScale<T extends ReleaseForScale>(
  releases: readonly T[]
): ReleaseScaleGroup<T>[] {
  return releaseScales.flatMap((scale) => {
    const groupedReleases = releases
      .filter((release) => scaleFromVersion(release.version) === scale)
      .toSorted((left, right) => right.released_at.getTime() - left.released_at.getTime());

    return groupedReleases.length === 0
      ? []
      : [{ scale, label: releaseScaleLabels[scale], releases: groupedReleases }];
  });
}
