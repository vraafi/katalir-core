"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { supabase } from "@/lib/supabase";

/** Profil minimal untuk halaman akun — tanpa TanStack (aman untuk prerender statis). */
export function useMeSimple(enabled: boolean): { email: string; tier: string } | null {
  const [me, setMe] = useState<{ email: string; tier: string } | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    (async () => {
      try {
        const { data } = await supabase.auth.getSession();
        if (!data.session?.access_token) return;
        const res = await apiFetch("/me");
        if (!res.ok) return;
        const payload = await res.json();
        if (!cancelled) setMe({ email: payload?.email ?? "", tier: payload?.tier ?? "free" });
      } catch {
        /* offline — halaman tetap render dengan default */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [enabled]);
  return me;
}
