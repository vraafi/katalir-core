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
  avatarUrl: string | null;
  displayName: string | null;
  loading: boolean;
  signInWithGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
  getToken: () => Promise<string | null>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [email, setEmail] = useState<string | null>(null);
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState<string | null>(null);
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
        setAvatarUrl(data.session?.user?.user_metadata?.avatar_url ?? data.session?.user?.user_metadata?.picture ?? null);
        setDisplayName(data.session?.user?.user_metadata?.full_name ?? data.session?.user?.user_metadata?.name ?? null);
        resolved = true;
        if (isHydrated()) commit();
      })
      .catch(() => {
        resolvedEmail = null;
        setAvatarUrl(null);
        setDisplayName(null);
        resolved = true;
        if (isHydrated()) commit();
      });

    // Dengarkan perubahan auth (login/logout dari tab lain / provider flow)
    const { data: sub } = supabase.auth.onAuthStateChange((event, session) => {
      // Login/logout saat runtime BUKAN hidrasi -> boleh langsung, tetapi tetap
      // lewat `commit()` agar urutan email/loading konsisten.
      resolvedEmail = session?.user?.email ?? null;
      setAvatarUrl(session?.user?.user_metadata?.avatar_url ?? session?.user?.user_metadata?.picture ?? null);
      setDisplayName(session?.user?.user_metadata?.full_name ?? session?.user?.user_metadata?.name ?? null);
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
    // Preserve the user's intended destination across the external OAuth
    // round-trip. The landing page has no useful post-login destination, so
    // it defaults to /chat; all other pages retain their path and query.
    const currentPath = `${window.location.pathname}${window.location.search}`;
    const returnTo = currentPath === "/" || currentPath === "" ? "/chat" : currentPath;
    await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${window.location.origin}${returnTo}` },
    });
  }

  /**
   * FASE 4: pantulkan keadaan autentikasi ke DOM (`html[data-auth]`).
   *
   * Kenapa: perilaku aplikasi BERGANTUNG pada sesi (composer, daftar model,
   * riwayat chat) dan perubahan itu baru diterapkan SETELAH hidrasi — jadi
   * markup awal terlihat sama pada keadaan "belum login" dan "sudah login".
   * Tanpa penanda yang bisa diamati, tes E2E mengisi form selagi handler React
   * belum terpasang: DOM berubah tetapi state React tidak, tombol kirim tetap
   * `disabled`, dan gejalanya terbaca "composer rusak" padahal tesnya balapan
   * dengan hidrasi. Ini akar kegagalan `model-filter BUG 2/VALID` (2 dari 3 tes
   * merah di FASE 3) dan sekelas dengan bug hidrasi kanvas FASE 3.
   *
   * Nilai: "loading" | "in" | "out". Tidak ada perubahan tampilan.
   */
  useEffect(() => {
    const state = loading ? "loading" : email ? "in" : "out";
    try {
      document.documentElement.dataset.auth = state;
    } catch {
      /* abaikan */
    }
  }, [loading, email]);

  async function signOut() {
    await supabase.auth.signOut();
    setEmail(null);
    setAvatarUrl(null);
    setDisplayName(null);
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
      value={{ email, avatarUrl, displayName, loading, signInWithGoogle, signOut, getToken }}
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