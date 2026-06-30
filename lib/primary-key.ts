import { apiFetch } from "@/lib/api";
import { API_BASE_URL } from "@/lib/config";
import {
  clearPrimaryKey,
  hasStalePrimaryKey,
  loadPrimaryKey,
  savePrimaryKey,
} from "@/lib/keystore";
import type { CreatedKeychainKey, InitUserResponse } from "@/lib/types";

/** Lightweight check that an ak- key is accepted by the current gateway. */
export async function verifyKeychainKey(apiKey: string): Promise<boolean> {
  if (!apiKey.startsWith("ak-")) return false;
  try {
    const res = await fetch(`${API_BASE_URL}/v1/models`, {
      method: "GET",
      headers: { Authorization: `Bearer ${apiKey}` },
    });
    return res.ok;
  } catch {
    return false;
  }
}

/**
 * Return a working primary ak- key for this user on the current gateway.
 * Clears stale local keys, verifies the cache against /v1/models, and mints a
 * new primary via regenerate-key when the cache is missing or rejected.
 */
export async function ensurePrimaryKey(
  userId: string,
  jwtToken: string
): Promise<string> {
  if (hasStalePrimaryKey(userId)) {
    clearPrimaryKey(userId);
  }

  const cached = loadPrimaryKey(userId);
  if (cached && (await verifyKeychainKey(cached))) {
    return cached;
  }
  if (cached) clearPrimaryKey(userId);

  const created = await apiFetch<CreatedKeychainKey>(
    `/users/${userId}/regenerate-key`,
    { method: "POST", token: jwtToken }
  );
  savePrimaryKey(userId, created.api_key);
  return created.api_key;
}

/** Onboard the user row and guarantee a valid cached primary key. */
export async function bootstrapUser(
  userId: string,
  jwtToken: string
): Promise<void> {
  await apiFetch<InitUserResponse>("/users/init", {
    method: "POST",
    token: jwtToken,
  });
  await ensurePrimaryKey(userId, jwtToken);
}
