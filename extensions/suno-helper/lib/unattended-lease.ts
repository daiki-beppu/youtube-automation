export interface UnattendedLease {
  collectionId: string;
  requestId: string;
  token: string;
  tabId: number;
  expiresAt: number;
}

export const UNATTENDED_LEASE_TTL_MS = 2 * 60 * 1000;
const GLOBAL_LEASE_KEY = "__unattended_global__";

export function acquireUnattendedLease(
  leases: Record<string, UnattendedLease>,
  request: { collectionId: string; requestId: string; tabId: number },
  now: number,
  token: string
): {
  acquired: boolean;
  leases: Record<string, UnattendedLease>;
  lease?: UnattendedLease;
} {
  const current = leases[GLOBAL_LEASE_KEY];
  if (current && current.expiresAt > now) return { acquired: false, leases };
  const lease: UnattendedLease = {
    ...request,
    token,
    expiresAt: now + UNATTENDED_LEASE_TTL_MS,
  };
  return {
    acquired: true,
    leases: { ...leases, [GLOBAL_LEASE_KEY]: lease },
    lease,
  };
}

export function renewUnattendedLease(
  leases: Record<string, UnattendedLease>,
  collectionId: string,
  token: string,
  now: number
): Record<string, UnattendedLease> {
  const current = leases[GLOBAL_LEASE_KEY];
  if (
    !current ||
    current.collectionId !== collectionId ||
    current.token !== token ||
    current.expiresAt <= now
  )
    return leases;
  return {
    ...leases,
    [GLOBAL_LEASE_KEY]: {
      ...current,
      expiresAt: now + UNATTENDED_LEASE_TTL_MS,
    },
  };
}

export function releaseUnattendedLease(
  leases: Record<string, UnattendedLease>,
  collectionId: string,
  token: string
): Record<string, UnattendedLease> {
  if (
    leases[GLOBAL_LEASE_KEY]?.token !== token ||
    leases[GLOBAL_LEASE_KEY]?.collectionId !== collectionId
  ) {
    return leases;
  }
  const next = { ...leases };
  delete next[GLOBAL_LEASE_KEY];
  return next;
}
