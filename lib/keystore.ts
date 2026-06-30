/**
 * The backend returns an `ak-...` keychain key in plaintext exactly once (on
 * create / regenerate). We persist the primary key locally so the dashboard can
 * reveal it later. Keys are scoped to the gateway URL they were minted against
 * so a key from localhost is never sent to production by mistake.
 */
function storageKey(userId: string): string {
  return `ak_key_${userId}`;
}

function metaStorageKey(userId: string): string {
  return `ak_key_meta_${userId}`;
}

function currentApiBase(): string {
  return normalizeApiBase(
    process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
  );
}

function normalizeApiBase(url: string): string {
  try {
    const parsed = new URL(url.includes("://") ? url : `https://${url}`);
    return `${parsed.protocol}//${parsed.host}`;
  } catch {
    return url.replace(/\/$/, "");
  }
}

function isLocalApi(url: string): boolean {
  return /localhost|127\.0\.0\.1/.test(url);
}

interface KeyMeta {
  apiBaseUrl: string;
}

function readMeta(userId: string): KeyMeta | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(metaStorageKey(userId));
    if (!raw) return null;
    return JSON.parse(raw) as KeyMeta;
  } catch {
    return null;
  }
}

/** True when a key is stored but was minted for a different gateway host. */
export function hasStalePrimaryKey(userId: string): boolean {
  if (typeof window === "undefined") return false;
  const key = window.localStorage.getItem(storageKey(userId));
  if (!key) return false;
  const meta = readMeta(userId);
  const current = currentApiBase();
  if (!meta) {
    // Legacy entries (pre gateway tag): only trust on local dev.
    return !isLocalApi(current);
  }
  return normalizeApiBase(meta.apiBaseUrl) !== current;
}

export function savePrimaryKey(userId: string, apiKey: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(storageKey(userId), apiKey);
    window.localStorage.setItem(
      metaStorageKey(userId),
      JSON.stringify({ apiBaseUrl: currentApiBase() } satisfies KeyMeta)
    );
  } catch {
    /* ignore quota / privacy-mode errors */
  }
}

export function loadPrimaryKey(userId: string): string | null {
  if (typeof window === "undefined") return null;
  if (hasStalePrimaryKey(userId)) return null;
  try {
    return window.localStorage.getItem(storageKey(userId));
  } catch {
    return null;
  }
}

export function clearPrimaryKey(userId: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(storageKey(userId));
    window.localStorage.removeItem(metaStorageKey(userId));
    window.localStorage.removeItem(playgroundKeyStorageKey(userId));
  } catch {
    /* ignore */
  }
}

function playgroundKeyStorageKey(userId: string): string {
  return `ak_playground_key_${userId}`;
}

export function clearPlaygroundCustomKey(userId: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(playgroundKeyStorageKey(userId));
  } catch {
    /* ignore */
  }
}

export function loadPlaygroundCustomKey(userId: string): string | null {
  if (typeof window === "undefined" || hasStalePrimaryKey(userId)) return null;
  try {
    return window.localStorage.getItem(playgroundKeyStorageKey(userId));
  } catch {
    return null;
  }
}

export function savePlaygroundCustomKey(userId: string, apiKey: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(playgroundKeyStorageKey(userId), apiKey.trim());
  } catch {
    /* ignore */
  }
}
