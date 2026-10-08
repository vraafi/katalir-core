"use client";

/**
 * useKeyboardInset — publikasikan tinggi keyboard sebagai `--keyboard-inset`.
 *
 * MENGAPA PERLU, padahal sudah ada `100dvh` + `interactive-widget=resizes-content`:
 * Safari iOS **tidak mendukung** `interactive-widget`. Di sana, saat keyboard
 * terbuka, layout viewport TIDAK mengecil — `100dvh` tetap setinggi layar dan
 * `documentElement.clientHeight` tidak berubah. Jadi `dvh` saja hanya
 * menyelesaikan Android/Chrome; iOS masih bergantung pada browser yang
 * menggulir field ke dalam pandangan.
 *
 * Hook ini adalah lapis kedua yang bekerja di SEMUA mesin: ia mengukur apa yang
 * benar-benar terlihat dan menerbitkan selisihnya sebagai properti kustom CSS.
 *
 * RUMUS: `layoutHeight − visualViewport.height − visualViewport.offsetTop`
 *   - `offsetTop` WAJIB dikurangi: saat Safari menggeser visual viewport agar
 *     field yang difokus terlihat, tepi bawah area terlihat naik lebih sedikit
 *     daripada tinggi keyboard.
 *   - `window.innerHeight` SENGAJA tidak dipakai: di justru platform yang paling
 *     butuh (iOS), nilai itu tidak berubah saat keyboard muncul.
 *
 * KENAPA RUMUS INI AMAN DARI HITUNG GANDA di Android (`resizes-content`):
 * di sana layout viewport IKUT mengecil, sehingga
 * `clientHeight − vv.height − offsetTop ≈ 0`. Jadi inset = 0 dan tidak ada
 * dorongan tambahan. Rumusnya menyesuaikan diri sendiri per platform.
 *
 * Ambang 80px menyaring keriuhan beberapa frame pertama saat animasi keyboard
 * (dan pembulatan sub-piksel) supaya composer tidak "melompat" sekilas.
 */
import { useEffect } from "react";

/** Di bawah ini dianggap bukan keyboard (animasi transien / pembulatan). */
export const KEYBOARD_MIN_PX = 80;

export function useKeyboardInset(): void {
  useEffect(() => {
    if (typeof window === "undefined") return;
    const vv = window.visualViewport;
    // Tanpa API ini, biarkan fallback CSS (0px) berlaku — bukan galat.
    if (!vv) return;

    let frame = 0;

    const update = (): void => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const layoutH = document.documentElement.clientHeight;
        // Saat pinch-zoom, visual viewport kecil karena zoom — bukan keyboard.
        const mentah = vv.scale > 1.01
          ? 0
          : layoutH - vv.height - vv.offsetTop;
        const inset = mentah >= KEYBOARD_MIN_PX ? Math.round(mentah) : 0;
        document.documentElement.style.setProperty("--keyboard-inset", `${inset}px`);
      });
    };

    const ac = new AbortController();
    // `resize` saja TIDAK cukup: penggeseran visual viewport datang sebagai
    // `scroll`, dan mengabaikannya membuat composer salah tempat persis saat
    // Safari menggulir ke field yang difokus.
    vv.addEventListener("resize", update, { signal: ac.signal });
    vv.addEventListener("scroll", update, { signal: ac.signal });
    update();

    return () => {
      ac.abort();
      cancelAnimationFrame(frame);
      document.documentElement.style.removeProperty("--keyboard-inset");
    };
  }, []);
}

export default useKeyboardInset;
