import { supabase } from "@/lib/supabase";

/**
 * Auth actions that do not need React state.
 *
 * These live outside `context/auth.tsx` on purpose. The landing page
 * deliberately omits `AuthProvider` so that supabase-js never enters the
 * landing bundle, yet it still has to offer a sign-in modal - and that modal
 * only ever needs to *start* an auth flow, never to *read* a session. Keeping
 * the calls here gives the context and the modal one implementation without
 * forcing a provider onto a page that opted out of it.
 */

export type OAuthProvider = "github" | "google";

/**
 * Where to send the user once an external provider round-trip finishes.
 *
 * The landing page has no useful post-login destination, so it defaults to
 * /chat; every other page keeps its own path and query string. GitHub and
 * Google must agree on this - computed separately they can drift, sending a
 * user who started at /settings to /chat after one provider and back to
 * /settings after the other.
 */
export function returnToAfterAuth(): string {
  const currentPath = `${window.location.pathname}${window.location.search}`;
  return currentPath === "/" || currentPath === "" ? "/chat" : currentPath;
}

const RETURN_KEY = "katalir:auth-return";

/**
 * OAuth leaves the app entirely and returns to `redirectTo`, so the intended
 * destination has to survive a full page unload. React state and the query
 * string are both gone by then, hence sessionStorage.
 */
export function rememberReturnTo(): string {
  const next = returnToAfterAuth();
  try {
    sessionStorage.setItem(RETURN_KEY, next);
  } catch {
    /* private mode: redirectTo still carries the path */
  }
  return next;
}

/** Read and clear the remembered destination. */
export function consumeReturnTo(fallback = "/chat"): string {
  try {
    const stored = sessionStorage.getItem(RETURN_KEY);
    if (stored) {
      sessionStorage.removeItem(RETURN_KEY);
      return stored;
    }
  } catch {
    /* ignore */
  }
  return fallback;
}

/**
 * Only same-origin, absolute paths are honoured from `?next=`. Without that
 * check the callback would honour `//evil.example` (protocol-relative) and turn
 * a post-login redirect into an open redirect.
 */
export function sanitizeNext(raw: string | null | undefined): string | null {
  if (!raw) return null;
  if (!raw.startsWith("/") || raw.startsWith("//")) return null;
  return raw;
}

export async function signInWithProvider(provider: OAuthProvider): Promise<void> {
  const next = rememberReturnTo();
  const { error } = await supabase.auth.signInWithOAuth({
    provider,
    options: { redirectTo: `${window.location.origin}${next}` },
  });
  // signInWithOAuth resolves rather than throws, and an error here means the
  // browser never navigated - the caller has to surface it or the spinner spins
  // forever on a modal that will never close.
  if (error) throw new Error(error.message);
}

/**
 * Returns the error instead of throwing so the caller can render it inline.
 * Supabase reports every failure (bad password, unconfirmed email, unknown
 * user) as a resolved `{ error }`, so throwing here would never fire.
 */
export async function signInWithEmail(
  email: string,
  password: string
): Promise<{ error: string | null }> {
  const { error } = await supabase.auth.signInWithPassword({ email, password });
  return { error: error?.message ?? null };
}

/**
 * Sign-up. When Supabase requires email confirmation this succeeds WITHOUT a
 * session, so callers must not treat a null error as "signed in" - they have to
 * distinguish the two via `needsConfirmation`.
 */
export async function signUpWithEmail(
  email: string,
  password: string
): Promise<{ error: string | null; needsConfirmation: boolean }> {
  const { data, error } = await supabase.auth.signUp({ email, password });
  return { error: error?.message ?? null, needsConfirmation: !error && !data.session };
}
