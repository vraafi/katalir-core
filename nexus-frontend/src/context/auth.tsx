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
    supabase.auth
      .getSession()
      .then(({ data }) => {
        setEmail(data.session?.user?.email ?? null);
      })
      .catch(() => {
        setEmail(null);
      })
      .finally(() => {
        setLoading(false);
      });

    // Dengarkan perubahan auth (login/logout dari tab lain / provider flow)
    const { data: sub } = supabase.auth.onAuthStateChange((event, session) => {
      setEmail(session?.user?.email ?? null);
      setLoading(false);
      // Invalideer chat-queries bij auth-wissel zodat sessions/messages
      // automatisch per user herladen (fix "history hilang" bug).
      if (event === "SIGNED_IN" || event === "SIGNED_OUT") {
        void invalidateChatQueries();
      }
    });

    return () => sub.subscription.unsubscribe();
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