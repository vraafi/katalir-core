"use client";

// /chat -> aplikasi chat. FASE 6 final: implementasinya DIPINDAH ke
// `./ChatApp` (dari `../page`) karena `/` kini halaman landing yang ringan.
// Alias ini dipertahankan supaya deep-link `/chat` tetap stabil dan hanya ada
// SATU implementasi chat (satu sumber kebenaran).
export { default } from "./ChatApp";

