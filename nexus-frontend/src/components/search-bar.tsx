"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Loader2, Search, X } from "lucide-react";

/**
 * Search katalog integrasi: mengetik langsung memfilter, tanpa Enter.
 *
 * Debounce 250 ms bukan gaya-gayaan. Tanpa itu, mengetik "slack"
 * menembak 5 request ke registry dalam ~1 detik, dan setiap request
 * itu consultar 23K entri di sisi server. Kolom `minChars` menjaga
 * agar 1 huruf tidak memicu fetch sia-sia.
 *
 * Enter tetap berfungsi sebagai fallback eksplisit, dan tombol Cari
 * juga ada — jadi tidak ada jalur yang hilang bagi user yang Habits
 * menekan Enter.
 */
export function SearchBar({
  onSearch,
  initialValue = "",
  minChars = 1,
  debounceMs = 250,
  loading = false,
  placeholder = "Cari 23.474+ integrasi…",
  label = "Cari integrasi",
}: {
  onSearch: (q: string) => void;
  initialValue?: string;
  minChars?: number;
  debounceMs?: number;
  loading?: boolean;
  placeholder?: string;
  label?: string;
}) {
  const [input, setInput] = useState(initialValue);
  const id = useId();
  // onSearch biasanya closure yang berubah setiap render. Disimpan di
  // ref supaya efek debounce tidak di-restart tiap render, yang membuat
  // timer-nya tidak pernah sempat selesai.
  const cb = useRef(onSearch);
  cb.current = onSearch;

  // Nilai terakhir yang sudah dikirim, supaya menghapus input (string kosong)
  // tetap meneruskan "" dan mengembalikan daftar penuh.
  const lastSent = useRef<string | null>(null);

  useEffect(() => {
    const q = input.trim();
    if (q.length < minChars) {
      // Hanya kirim ulang ke state penuh kalau sebelumnya memang sudah
      // aktif mencari; jangan pistolkan request saat halaman baru dibuka.
      if (lastSent.current !== null && lastSent.current !== "") {
        lastSent.current = "";
        cb.current("");
      }
      return;
    }
    if (q === lastSent.current) return;
    const t = setTimeout(() => {
      lastSent.current = q;
      cb.current(q);
    }, debounceMs);
    return () => clearTimeout(t);
  }, [input, debounceMs, minChars]);

  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-col gap-2 sm:flex-row">
        <div className="relative flex-1">
          <label htmlFor={id} className="sr-only">
            {label}
          </label>
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-muted"
            aria-hidden
          />
          <input
            id={id}
            data-testid="integrations-search"
            type="search"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              // Fallback eksplisit: Enter langsung kirim, tanpa menunggu
              // sisa debounce.
              if (e.key === "Enter") {
                e.preventDefault();
                const q = input.trim();
                lastSent.current = q;
                cb.current(q);
              }
            }}
            placeholder={placeholder}
            autoComplete="off"
            className="w-full rounded-lg border border-border bg-surface py-2 pl-10 pr-9 text-sm text-fg outline-none focus-visible:border-primary"
          />
          {loading ? (
            <Loader2
              data-testid="integrations-search-loading"
              className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-fg-muted"
              aria-hidden
            />
          ) : input ? (
            <button
              type="button"
              onClick={() => setInput("")}
              data-testid="integrations-search-clear"
              aria-label="Bersihkan pencarian"
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-fg-muted hover:text-fg"
            >
              <X className="h-4 w-4" aria-hidden />
            </button>
          ) : null}
        </div>
        <button
          type="button"
          onClick={() => {
            const q = input.trim();
            lastSent.current = q;
            cb.current(q);
          }}
          data-testid="integrations-search-submit"
          className="rounded-lg border border-border bg-surface px-3 py-2 text-sm font-medium text-fg hover:bg-bg-subtle"
        >
          Cari
        </button>
      </div>
      <p className="text-xs text-fg-muted" data-testid="integrations-search-hint">
        Ketik untuk mencari otomatis — atau tekan Enter.
      </p>
    </div>
  );
}
