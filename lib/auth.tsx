"use client";

import * as React from "react";
import type { Session, User } from "@supabase/supabase-js";

import { getSupabase, supabaseConfigured } from "@/lib/supabase/client";
import { apiFetch } from "@/lib/api";
import { savePrimaryKey, loadPrimaryKey, hasStalePrimaryKey, clearPrimaryKey } from "@/lib/keystore";
import type {
  CreatedKeychainKey,
  InitUserResponse,
  ListKeychainKeysResponse,
} from "@/lib/types";

interface AuthContextValue {
  loading: boolean;
  configured: boolean;
  session: Session | null;
  user: User | null;
  userId: string | null;
  email: string | null;
  /** True once /users/init + primary-key bootstrap has completed. */
  ready: boolean;
  signOut: () => Promise<void>;
}

const AuthContext = React.createContext<AuthContextValue | undefined>(undefined);

/**
 * Idempotently onboard the user on the backend: create the user row, then make
 * sure a primary ak- key exists and is cached locally for later reveal.
 */
async function bootstrapUser(userId: string, token: string): Promise<void> {
  await apiFetch<InitUserResponse>("/users/init", {
    method: "POST",
    token,
  });

  const existing = await apiFetch<ListKeychainKeysResponse>(
    `/users/${userId}/keychain-keys`,
    { token }
  );
  const hasPrimary = existing.keys.some((k) => k.is_primary && !k.revoked);

  if (hasStalePrimaryKey(userId)) {
    clearPrimaryKey(userId);
  }
  const hasCached = Boolean(loadPrimaryKey(userId));

  if (!hasPrimary || !hasCached) {
    // Mint (or rotate to) a primary key so the user always has a usable,
    // revealable ak- key. regenerate-key creates the primary if absent.
    const created = await apiFetch<CreatedKeychainKey>(
      `/users/${userId}/regenerate-key`,
      { method: "POST", token }
    );
    savePrimaryKey(userId, created.api_key);
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [loading, setLoading] = React.useState(true);
  const [session, setSession] = React.useState<Session | null>(null);
  const [ready, setReady] = React.useState(false);
  const bootstrappedFor = React.useRef<string | null>(null);

  React.useEffect(() => {
    if (!supabaseConfigured) {
      setLoading(false);
      return;
    }
    const supabase = getSupabase();

    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setLoading(false);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, newSession) => {
      setSession(newSession);
      setLoading(false);
      if (!newSession) {
        bootstrappedFor.current = null;
        setReady(false);
      }
    });

    return () => subscription.unsubscribe();
  }, []);

  // Run the one-time backend bootstrap whenever we have a fresh session.
  React.useEffect(() => {
    const userId = session?.user?.id;
    const token = session?.access_token;
    if (!userId || !token) return;
    if (bootstrappedFor.current === userId) {
      setReady(true);
      return;
    }
    bootstrappedFor.current = userId;
    let cancelled = false;
    (async () => {
      try {
        await bootstrapUser(userId, token);
      } catch (err) {
        // Reset so a later navigation can retry; surface in console for debug.
        bootstrappedFor.current = null;
        // eslint-disable-next-line no-console
        console.error("User bootstrap failed:", err);
      } finally {
        if (!cancelled) setReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [session]);

  const signOut = React.useCallback(async () => {
    if (supabaseConfigured) {
      await getSupabase().auth.signOut();
    }
    setSession(null);
    bootstrappedFor.current = null;
    setReady(false);
  }, []);

  const value: AuthContextValue = {
    loading,
    configured: supabaseConfigured,
    session,
    user: session?.user ?? null,
    userId: session?.user?.id ?? null,
    email: session?.user?.email ?? null,
    ready,
    signOut,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = React.useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
