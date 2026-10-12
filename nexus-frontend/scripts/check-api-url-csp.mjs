/**
 * check-api-url-csp.mjs — gerbang build: NEXT_PUBLIC_API_URL HARUS diizinkan CSP.
 *
 * KENAPA GERBANG INI ADA (insiden nyata 2026-10-12)
 * -------------------------------------------------
 * Build produksi `katalir.de5.net` di-compile dengan
 *   NEXT_PUBLIC_API_URL=https://web-production-dc90b.up.railway.app
 * (backend Railway LAMA, kini 404). Dua kerusakan sekaligus:
 *   1. host itu mati (404) -> tidak ada data yang bisa dimuat;
 *   2. `public/_headers` TIDAK mengizinkan host itu di `connect-src`, jadi
 *      browser memblokir setiap fetch SEBELUM keluar.
 * Hasil uji pengguna nyata: chat, template, insight, builder, riwayat, dan
 * kredensial SEMUANYA gagal dengan satu gejala konsol yang sama:
 *   "Connecting to 'https://web-production-dc90b.up.railway.app/chat'
 *    violates the following Content Security Policy directive: connect-src ..."
 * Pengguna hanya melihat "Koneksi lambat. Cek internetmu." — menyesatkan,
 * karena masalahnya konfigurasi build, bukan internet pengguna.
 *
 * `NEXT_PUBLIC_*` di-INLINE saat build, jadi kesalahan ini tidak terlihat
 * sampai ada orang membuka produksi. Gerbang ini membuat build GAGAL LEBIH
 * DULU, bukan menunggu laporan pengguna.
 *
 * Aturan: origin dari NEXT_PUBLIC_API_URL harus cocok dengan salah satu
 * sumber di direktif `connect-src` pada `public/_headers` (wildcard `*.`
 * didukung). Dijalankan di `prebuild`.
 */

import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const HEADERS = join(root, "public", "_headers");

const RED = "\u001b[31m", YEL = "\u001b[33m", DIM = "\u001b[2m", OFF = "\u001b[0m";

/**
 * Muat `NEXT_PUBLIC_*` dari berkas env dengan urutan prioritas Next.js
 * (tinggi -> rendah):
 *   .env.production.local > .env.local > .env.production > .env
 *
 * KENAPA perlu: `prebuild` dijalankan npm SEBELUM Next.js memuat `.env`,
 * sehingga `process.env.NEXT_PUBLIC_API_URL` KOSONG saat gerbang dipanggil
 * lewat `npm run build`. Tanpa pemuatan ini gerbang akan lolos diam-diam
 * (lubang yang justru membuat insiden terulang). Nilai yang SUDAH ada di
 * `process.env` (mis. dari CI/dashboard) selalu menang.
 */
function loadEnvFiles() {
  const files = [".env.production.local", ".env.local", ".env.production", ".env"];
  const found = {};
  const sources = [];
  for (const f of files) {
    const p = join(root, f);
    if (!existsSync(p)) continue;
    for (const raw of readFileSync(p, "utf8").split(/\r?\n/)) {
      const line = raw.trim().replace(/^\uFEFF/, "");
      if (!line || line.startsWith("#") || !line.includes("=")) continue;
      const i = line.indexOf("=");
      const k = line.slice(0, i).trim();
      let v = line.slice(i + 1).trim();
      if ((v.startsWith('"') && v.endsWith('"')) ||
          (v.startsWith("'") && v.endsWith("'"))) v = v.slice(1, -1);
      if (!k) continue;
      if (!(k in found)) found[k] = v; // berkas pertama menang
      if (!sources.includes(f)) sources.push(f);
    }
  }
  return { found, sources };
}

const { found, sources } = loadEnvFiles();
// process.env menang atas berkas (CI/dashboard menyetel variabel asli).
const apiUrl = (process.env.NEXT_PUBLIC_API_URL || found.NEXT_PUBLIC_API_URL || "").trim();
const apiUrlSource = process.env.NEXT_PUBLIC_API_URL
  ? "process.env"
  : (found.NEXT_PUBLIC_API_URL ? `berkas env (${sources.join(", ")})` : "(tidak ada)");

function fail(msg, hint) {
  console.error(`\n${RED}✖ check-api-url-csp: ${msg}${OFF}`);
  if (hint) console.error(`${YEL}  → ${hint}${OFF}`);
  console.error(`${DIM}  (gerbang ini mencegah insiden CSP 2026-10-12 terulang)${OFF}\n`);
  process.exit(1);
}

if (!apiUrl) {
  // Tanpa nilai, src/lib/api.ts jatuh ke http://localhost:8000 — hanya boleh
  // untuk build lokal. Build produksi wajib menyetelnya.
  console.error(
    `${YEL}⚠ check-api-url-csp: NEXT_PUBLIC_API_URL kosong — ` +
    `bundle akan memakai http://localhost:8000.${OFF}\n` +
    `${DIM}  Setel NEXT_PUBLIC_API_URL di .env.production (atau process.env) ` +
    `sebelum build.${OFF}`
  );
  process.exit(0);
}

let origin;
try {
  origin = new URL(apiUrl).origin;
} catch {
  fail(`NEXT_PUBLIC_API_URL bukan URL yang valid: ${apiUrl}`);
}

let headersSrc;
try {
  headersSrc = readFileSync(HEADERS, "utf8");
} catch {
  fail(`tidak bisa membaca ${HEADERS}`);
}

// Ambil baris Content-Security-Policy (bukan komentar).
const cspLine = headersSrc
  .split(/\r?\n/)
  .find((l) => /^\s*Content-Security-Policy:/i.test(l));
if (!cspLine) fail("tidak menemukan header Content-Security-Policy di public/_headers");

const directives = {};
for (const part of cspLine.replace(/^\s*Content-Security-Policy:/i, "").split(";")) {
  const toks = part.trim().split(/\s+/).filter(Boolean);
  if (toks.length) directives[toks[0].toLowerCase()] = toks.slice(1);
}
const connectSrc = directives["connect-src"] || [];

const host = new URL(apiUrl).hostname;
const allowed = connectSrc.some((src) => {
  if (src === "'self'") return false; // 'self' tidak menutup host eksternal
  let s = src.replace(/^https?:\/\//, "").replace(/\/.*$/, "");
  if (s.startsWith("*.")) {
    const base = s.slice(2);
    return host === base || host.endsWith("." + base);
  }
  return s === host;
});

if (!allowed) {
  fail(
    `NEXT_PUBLIC_API_URL (${origin}) TIDAK diizinkan oleh CSP connect-src.\n` +
    `     connect-src saat ini: ${connectSrc.join(" ") || "(kosong)"}\n` +
    `     Browser akan memblokir SEMUA fetch ke host ini sebelum keluar.`,
    `Tambahkan ${origin} ke direktif connect-src di public/_headers, ` +
    `atau arahkan NEXT_PUBLIC_API_URL ke host yang sudah diizinkan.`
  );
}

console.log(
  `${DIM}✔ check-api-url-csp: ${origin} diizinkan oleh connect-src ` +
  `(sumber: ${apiUrlSource})${OFF}`
);
