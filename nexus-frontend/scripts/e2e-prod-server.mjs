/**
 * Jalankan PRODUCTION BUILD frontend untuk E2E, dengan API diarahkan ke backend LOKAL.
 *
 * KENAPA: `next dev` dan production build berperilaku berbeda (minifikasi, env
 * NEXT_PUBLIC_* yang di-inline saat build, hydration). Tes yang hanya jalan di
 * dev bisa lulus sementara user — yang memakai build produksi — tetap melihat
 * bug. Jadi E2E WAJIB memakai build produksi.
 *
 * MASALAH KEDUA YANG DITUTUP DI SINI: `.env.local` menetapkan
 * `NEXT_PUBLIC_API_URL` ke backend deploy (Railway). Bundle produksi hasil
 * build biasa karena itu memanggil backend LAMA, sehingga hasil tes tidak
 * mencerminkan kode di repo — persis penyebab "agent bilang PASS, user lihat
 * bug". `process.env` MENANG atas `.env.local` saat inlining `NEXT_PUBLIC_*`
 * (terverifikasi empiris: bundle berisi nilai dari env, bukan dari file), jadi
 * override di bawah memaksa build menembak backend lokal.
 *
 * Set `E2E_SKIP_BUILD=1` bila ingin menyajikan `out/` yang sudah ada tanpa
 * build ulang (mis. iterasi cepat di spec yang sama).
 */
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

const API_URL = process.env.E2E_API_URL || "http://127.0.0.1:8000";
const SKIP_BUILD = process.env.E2E_SKIP_BUILD === "1";

if (!SKIP_BUILD) {
  const nextBin = join(process.cwd(), "node_modules", "next", "dist", "bin", "next");
  if (!existsSync(nextBin)) {
    console.error(`[e2e-prod] next tidak ditemukan di ${nextBin} — jalankan "npm install" dulu.`);
    process.exit(1);
  }
  console.log(`[e2e-prod] next build (NEXT_PUBLIC_API_URL=${API_URL})`);
  const res = spawnSync(process.execPath, [nextBin, "build"], {
    stdio: "inherit",
    env: { ...process.env, NEXT_PUBLIC_API_URL: API_URL },
  });
  if (res.status !== 0) {
    console.error(`[e2e-prod] build gagal (exit ${res.status ?? "?"})`);
    process.exit(res.status ?? 1);
  }
} else {
  console.log("[e2e-prod] E2E_SKIP_BUILD=1 -> memakai out/ yang ada");
}

// `serve-out.mjs` membaca PORT. Teruskan override E2E_PORT supaya harness
// benar-benar listen di port yang diharapkan config, bukan selalu 3000.
if (process.env.E2E_PORT) process.env.PORT = process.env.E2E_PORT;

// serve-out.mjs memeriksa `out/` dan langsung listen saat di-import.
await import("./serve-out.mjs");
