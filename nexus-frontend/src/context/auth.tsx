"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  ReactNode,
} from "react";
import { supabase } from "@/lib/supabase";
import { invalidateChatQueries } from "@/lib/query-client";
import { isHydrated, onHydrated } from "@/i18n/hydration-signal";

interface AuthContextValue {
  email: string | null;
  loading: boolean;
  signInWithGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
  getToken: () => Promise<string | null>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [email, setEmail] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Ambil sesi yang sudah tersimpan (persistent session)
    // getSession kadang bisa gagal (token expired / offline saat boot).
    // Pastikan loading SELALU selesai agar UI tidak terkunci permanen.
    // HYDRATION (bug nyata): SSR SELALU merender keadaan "belum login" karena
    // server tidak bisa membaca localStorage. Bila hasil getSession diterapkan
    // SEBELUM subtree Suspense selesai dihidrasi, footer sidebar berubah dari
    // keadaan SSR sehingga React melaporkan hydration mismatch -- dan itu race
    // (gejala: mismatch muncul bergantian pada rute yang sama) karena
    // getSession() sering resolve di microtask. Karena itu sesi baru diterapkan
    // setelah sinyal hidrasi (lihat i18n/hydration-signal.ts).
    let alive = true;
    let resolvedEmail: string | null = null;
    let resolved = false;

    const commit = () => {
      if (!alive || !resolved) return;
      setEmail(resolvedEmail);
      setLoading(false);
    };

    const cancelHydrationWait = onHydrated(commit);

    supabase.auth
      .getSession()
      .then(({ data }) => {
        resolvedEmail = data.session?.user?.email ?? null;
        resolved = true;
        if (isHydrated()) commit();
      })
      .catch(() => {
        resolvedEmail = null;
        resolved = true;
        if (isHydrated()) commit();
      });

    // Dengarkan perubahan auth (login/logout dari tab lain / provider flow)
    const { data: sub } = supabase.auth.onAuthStateChange((event, session) => {
      // Login/logout saat runtime BUKAN hidrasi -> boleh langsung, tetapi tetap
      // lewat `commit()` agar urutan email/loading konsisten.
      resolvedEmail = session?.user?.email ?? null;
      resolved = true;
      if (isHydrated()) commit();
      // Invalideer chat-queries bij auth-wissel zodat sessions/messages
      // automatisch per user herladen (fix "history hilang" bug).
      if (event === "SIGNED_IN" || event === "SIGNED_OUT") {
        // Supabase Auth deadlock (DEV Community, 8/2026): JANGAN jalar async
        // auth-API (invalidateChatQueries -> refetch -> getSession) SINKRON di
        // dalam callback onAuthStateChange — bisa menghang query Supabase lain
        // (symptoom: /sessions lambat + timeout, tanpa error). Defer ke macrotask
        // setelah auth lock released hijsen (pattern setTimeout(fn, 0)).
        setTimeout(() => {
          void invalidateChatQueries();
        }, 0);
      }
    });

    return () => {
      alive = false;
      cancelHydrationWait();
      sub.subscription.unsubscribe();
    };
  }, []);

  async function signInWithGoogle() {
    await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: window.location.origin },
    });
  }

  async function signOut() {
    await supabase.auth.signOut();
    setEmail(null);
  }

  async function getToken(): Promise<string | null> {
    try {
      const { data } = await supabase.auth.getSession();
      return data.session?.access_token ?? null;
    } catch {
      return null;
    }
  }

  return (
    <AuthContext.Provider
      value={{ email, loading, signInWithGoogle, signOut, getToken }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}