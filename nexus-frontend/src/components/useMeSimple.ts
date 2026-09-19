"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

/** Profil minimal untuk halaman akun — tanpa TanStack (aman untuk prerender statis). */
export function useMeSimple(enabled: boolean): { email: string; tier: string } | null {
  const [me, setMe] = useState<{ email: string; tier: string } | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch("/me");
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled) setMe({ email: data?.email ?? "", tier: data?.tier ?? "free" });
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
