"use client";

import { useState, type FormEvent } from "react";
import { Github, Loader2 } from "lucide-react";
import { Dialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import * as authActions from "@/lib/auth-actions";
import { useI18n } from "@/i18n/context";
/**
 * Sign-in modal: GitHub, Google, or email + password.
 *
 * The three providers are not interchangeable from the caller's point of view,
 * and that difference is the whole reason this is a modal rather than three
 * separate redirects:
 *   - OAuth leaves the page and comes back to `redirectTo`, so the user is
 *     briefly gone and the dialog is torn down by the navigation itself.
 *   - Email/password stays on the page, so the modal owns the result: it must
 *     render the error inline and must NOT close on a null error alone, because
 *     sign-up can succeed without producing a session (email confirmation).
 *
 * All copy goes through `t()`. This app ships id + en and the landing page is
 * Indonesian by default, so hardcoded English here would be a visible
 * regression on the primary market.
 */
export function LoginModal({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useI18n();
  // Deliberately NOT useAuth(): the landing page mounts this modal without an
  // AuthProvider so supabase-js stays out of the landing bundle, and the modal
  // never needs session state anyway - it only starts auth flows. Shared calls
  // come from @/lib/auth-actions, the same module the context delegates to.

  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [pending, setPending] = useState<"github" | "google" | "email" | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Reset transient state on dismiss so a failed attempt does not greet the
  // user again on the next open.
  const close = (next: boolean) => {
    if (!next) {
      setError(null);
      setNotice(null);
      setPending(null);
      setPassword("");
      setMode("signin");
    }
    onOpenChange(next);
  };

  const handleOAuth = async (provider: "github" | "google") => {
    setPending(provider);
    setError(null);
    try {
      await authActions.signInWithProvider(provider);
      // On success the browser navigates away. If the provider is unreachable
      // signInWithProvider throws; if it resolves without navigating the
      // spinner must be released here or the modal locks on "signing in".
      setPending(null);
    } catch {
      setError(t("auth.genericError"));
      setPending(null);
    }
  };

  const handleEmail = async (e: FormEvent) => {
    e.preventDefault();
    setPending("email");
    setError(null);
    setNotice(null);
    try {
      if (mode === "signin") {
        const { error: err } = await authActions.signInWithEmail(email, password);
        if (err) setError(err);
        else close(false);
      } else {
        const { error: err, needsConfirmation } = await authActions.signUpWithEmail(email, password);
        if (err) setError(err);
        else if (needsConfirmation) setNotice(t("auth.checkInbox"));
        else close(false);
      }
    } catch {
      setError(t("auth.genericError"));
    } finally {
      setPending(null);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={close}
      title={t("auth.title")}
      description={t("auth.subtitle")}
      closeLabel={t("auth.close")}
    >
      <div className="grid gap-3">
        <Button
          variant="secondary"
          size="lg"
          className="w-full"
          onClick={() => handleOAuth("github")}
          disabled={pending !== null}
          data-testid="login-github"
          aria-label={t("auth.githubButtonLabel")}
        >
          {pending === "github" ? <Loader2 className="animate-spin" aria-hidden /> : <Github aria-hidden />}
          {t("auth.withGithub")}
        </Button>

        <Button
          variant="secondary"
          size="lg"
          className="w-full"
          onClick={() => handleOAuth("google")}
          disabled={pending !== null}
          data-testid="login-google"
          aria-label={t("auth.googleButtonLabel")}
        >
          {pending === "google" ? (
            <Loader2 className="animate-spin" aria-hidden />
          ) : (
            <svg viewBox="0 0 24 24" aria-hidden focusable="false">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
            </svg>
          )}
          {t("auth.withGoogle")}
        </Button>

        <div className="relative my-1 flex items-center">
          <span className="h-px w-full bg-border" aria-hidden />
          <span className="bg-surface px-2 text-footnote text-fg-subtle">{t("auth.or")}</span>
          <span className="h-px w-full bg-border" aria-hidden />
        </div>

        <form onSubmit={handleEmail} className="grid gap-3" data-testid="login-email-form">
          <Input
            label={t("auth.email")}
            type="email"
            name="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            data-testid="login-email"
          />
          <Input
            label={t("auth.password")}
            type="password"
            name="password"
            autoComplete={mode === "signin" ? "current-password" : "new-password"}
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            data-testid="login-password"
          />

          {error && (
            <p role="alert" data-testid="login-error" className="text-footnote text-danger">
              {error}
            </p>
          )}
          {notice && (
            <p role="status" data-testid="login-notice" className="text-footnote text-fg-muted">
              {notice}
            </p>
          )}

          <Button
            type="submit"
            size="lg"
            className="w-full"
            disabled={pending !== null}
            data-testid="login-submit"
            aria-label={t("auth.emailSubmitLabel")}
          >
            {pending === "email" && <Loader2 className="animate-spin" aria-hidden />}
            {mode === "signin" ? t("auth.signIn") : t("auth.signUp")}
          </Button>
        </form>

        <p className="text-center text-footnote text-fg-muted">
          {mode === "signin" ? t("auth.noAccount") : t("auth.haveAccount")}{" "}
          <button
            type="button"
            onClick={() => {
              setMode(mode === "signin" ? "signup" : "signin");
              setError(null);
              setNotice(null);
            }}
            className="font-medium text-accent underline-offset-2 hover:underline focus-visible:shadow-focus"
            data-testid="login-toggle-mode"
          >
            {mode === "signin" ? t("auth.signUp") : t("auth.signIn")}
          </button>
        </p>
      </div>
    </Dialog>
  );
}
