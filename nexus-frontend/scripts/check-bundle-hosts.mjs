/**
 * check-bundle-hosts.mjs — verifikasi ISI bundle `out/` setelah build.
 *
 * KENAPA ADA
 * ----------
 * `check-api-url-csp.mjs` menjaga SUMBER (env vs CSP). Skrip ini menjaga
 * HASILNYA: membuktikan bundle yang benar-benar akan di-deploy tidak lagi
 * memuat host mati, dan benar-benar memuat host produksi.
 *
 * Insiden 12 Okt 2026 lolos karena tidak ada satu pun langkah yang memeriksa
 * ISI `out/`. CSP sudah diperbaiki 11 Okt, tapi bundle-nya tidak pernah
 * di-build ulang — jadi selama sehari produksi tetap memanggil host mati.
 * Pemeriksaan ini menutup celah "sumber benar, hasil salah".
 *
 * Aturan:
 *   - HARAM  : host apa pun dari daftar terlarang muncul di out/
 *   - WAJIB  : host produksi (dari NEXT_PUBLIC_API_URL) MUNCUL di out/
 *
 * Pakai:
 *   node scripts/check-bundle-hosts.mjs
 */
import { readFileSync, existsSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, extname } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const OUT = join(root, "out");

const RED = "\u001b[31m", GRN = "\u001b[32m", YEL = "\u001b[33m", DIM = "\u001b[2m", OFF = "\u001b[0m";

// Host yang TERBUKTI mati/berbahaya. Menambah entri di sini = menambah
// pertahanan; jangan pernah mengosongkan daftar ini.
const FORBIDDEN = [
  "web-production-dc90b.up.railway.app", // backend Railway lama (404)
  "localhost:8000",                      // fallback dev di src/lib/api.ts
  "127.0.0.1:8000",
];

const SCAN_EXT = new Set([".js", ".mjs", ".html", ".json", ".txt", ".css"]);

function walk(dir, acc = []) {
  for (const e of readdirSync(dir)) {
    const p = join(dir, e);
    const st = statSync(p);
    if (st.isDirectory()) walk(p, acc);
    else if (SCAN_EXT.has(extname(p)) || e === "_headers") acc.push(p);
  }
  return acc;
}

// Muat NEXT_PUBLIC_API_URL dengan prioritas Next.js (sama seperti gerbang CSP).
function loadApiUrl() {
  for (const f of [".env.production.local", ".env.local", ".env.production", ".env"]) {
    const p = join(root, f);
    if (!existsSync(p)) continue;
    for (const raw of readFileSync(p, "utf8").split(/\r?\n/)) {
      const line = raw.trim().replace(/^\uFEFF/, "");
      const m = line.match(/^NEXT_PUBLIC_API_URL\s*=\s*(.+)$/);
      if (m) return m[1].trim().replace(/^["']|["']$/g, "");
    }
  }
  return (process.env.NEXT_PUBLIC_API_URL || "").trim();
}

if (!existsSync(OUT)) {
  console.error(`${RED}✖ check-bundle-hosts: ${OUT} tidak ada — jalankan build + export dulu.${OFF}`);
  process.exit(1);
}

const apiUrl = loadApiUrl();
if (!apiUrl) {
  console.error(`${YEL}⚠ check-bundle-hosts: NEXT_PUBLIC_API_URL tidak diketahui — `
    + `lewati pemeriksaan "WAJIB muncul".${OFF}`);
}
const expectHost = apiUrl ? new URL(apiUrl).hostname : null;

const files = walk(OUT);
const hits = {};   // forbidden host -> [berkas]
const found = {};  // expected host -> jumlah

/**
 * Ambil HANYA konten Fungsional.
 *
 * KENAPA: `_headers` memuat blok komentar dokumentasi yang SENGAJA menyebut
 * host Railway mati (untuk menjelaskan insiden 12 Okt 2026). Komentar bukan
 * target fetch — kalau ikut dipindai, gerbang memberi alarm palsu dan orang
 * akan mematikannya. Jadi untuk `_headers` komentar (`#`) dibuang lebih dulu.
 */
function functional(file, txt) {
  if (file.endsWith("_headers")) {
    return txt.split(/\r?\n/).filter((l) => !/^\s*#/.test(l)).join("\n");
  }
  return txt;
}

for (const f of files) {
  let txt;
  try { txt = readFileSync(f, "utf8"); } catch { continue; }
  const rel = f.slice(OUT.length + 1);
  const body = functional(rel, txt);
  for (const h of FORBIDDEN) {
    if (body.includes(h)) (hits[h] ||= []).push(rel);
  }
  if (expectHost && body.includes(expectHost)) {
    found[expectHost] = (found[expectHost] || 0) + 1;
  }
}

console.log(`${DIM}bundle   : ${OUT} (${files.length} berkas dipindai)${OFF}`);
console.log(`${DIM}harapan  : ${expectHost || "(tidak diketahui)"}${OFF}`);

let bad = false;

if (Object.keys(hits).length) {
  bad = true;
  console.error(`\n${RED}✖ check-bundle-hosts: host terlarang DITEMUKAN di out/${OFF}`);
  for (const [h, fs_] of Object.entries(hits)) {
    console.error(`${RED}  ${h}${OFF} -> ${fs_.length} berkas, mis. ${fs_.slice(0, 3).join(", ")}`);
  }
  console.error(`${YEL}  → build ulang setelah memperbaiki NEXT_PUBLIC_API_URL.${OFF}\n`);
} else {
  console.log(`${GRN}✔ tidak ada host terlarang di out/ (${FORBIDDEN.length} host diperiksa)${OFF}`);
}

if (expectHost && !found[expectHost]) {
  bad = true;
  console.error(`\n${RED}✖ check-bundle-hosts: host produksi "${expectHost}" TIDAK ADA di out/${OFF}`);
  console.error(`${YEL}  → bundle tidak akan bisa menghubungi backend. Periksa env saat build.${OFF}\n`);
} else if (expectHost) {
  console.log(`${GRN}✔ host produksi "${expectHost}" ditemukan di ${found[expectHost]} berkas${OFF}`);
}

process.exit(bad ? 1 : 0);
