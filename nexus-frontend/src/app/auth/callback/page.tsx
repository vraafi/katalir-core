"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase";
import { consumeReturnTo, sanitizeNext } from "@/lib/auth-actions";
import { useI18n } from "@/i18n/context";
import { I18nProvider } from "@/i18n/context";
import { HydrationReady } from "@/i18n/HydrationReady";

/**
 * OAuth landing route.
 *
 * WHY THIS IS NOT JUST `getSession()`:
 * the obvious implementation calls `supabase.auth.getSession()` once on mount
 * and redirects to `/?error=auth_failed` when it returns null. That races the
 * SDK. Supabase parses the `#access_token=...` fragment and exchanges it for a
 * session asynchronously, and that work has not necessarily finished by the
 * time the first `getSession()` resolves - so a perfectly successful sign-in
 * bounces the user back to an error page. The symptom is intermittent and looks
 * like "GitHub login randomly fails", which is close to undebuggable.
 *
 * Instead: subscribe to `onAuthStateChange` first (Supabase fires INITIAL_SESSION
 * with the established session), and poll as a backstop for the case where the
 * event was missed. Only after a real timeout do we call it a failure.
 */
export default function AuthCallbackPage() {
  // This route stands alone: the root layout does not mount I18nProvider, and
  // `useI18n` throws without it. Same split every other standalone route uses.
  return (
    <I18nProvider>
      <HydrationReady />
      <AuthCallback />
    </I18nProvider>
  );
}

function AuthCallback() {
  const router = useRouter();
  const { t } = useI18n();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const finish = (session: unknown) => {
      if (cancelled) return;
      if (session) {
        // Prefer the path remembered before the provider redirect; `?next=`
        // wins when present, but only after being checked for a same-origin
        // absolute path so this cannot be used as an open redirect.
        const params = new URLSearchParams(window.location.search);
        const fromQuery = sanitizeNext(params.get("next"));
        const next = fromQuery ?? consumeReturnTo("/chat");
        router.replace(next);
      }
    };

    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => {
      finish(session);
    });

    // Backstop + the path when the session already existed.
    supabase.auth.getSession().then(({ data }) => {
      if (!cancelled && data.session) finish(data.session);
    });

    const timer = setTimeout(() => {
      if (!cancelled) setFailed(true);
    }, 8000);

    return () => {
      cancelled = true;
      clearTimeout(timer);
      sub.subscription.unsubscribe();
    };
  }, [router]);

  return (
    <main className="flex min-h-dvh items-center justify-center px-6" data-testid="auth-callback">
      <div className="text-center">
        {failed ? (
          <>
            <p role="alert" className="text-body text-danger">
              {t("auth.genericError")}
            </p>
            <button
              type="button"
              onClick={() => router.replace("/")}
              className="mt-4 font-medium text-accent underline-offset-2 hover:underline"
            >
              {t("common.back")}
            </button>
          </>
        ) : (
          <p className="text-body text-fg-muted">{t("auth.working")}</p>
        )}
      </div>
    </main>
  );
}
