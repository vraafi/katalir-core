/**
 * check-payment-hidden.mjs — gerbang build: pembayaran yang "ditutup" harus
 * benar-benar tidak ada di bundle.
 *
 * KENAPA ADA (ditemukan 13 Okt 2026, saat mengerjakan FASE 7)
 * -----------------------------------------------------------
 * `.env.production` sudah mengomentari NEXT_PUBLIC_DODO_CHECKOUT_URL, tetapi
 * bundle tetap memuat URL checkout. Penyebabnya: Next.js memuat LEBIH DARI SATU
 * berkas env, dan `.env.local` (prioritas lebih tinggi dari `.env.production`)
 * masih memuat nilai itu. Yang penting dan mudah dilupakan:
 *
 *   Next meng-INLINE `process.env.NEXT_PUBLIC_*` secara TEKSTUAL saat build.
 *   Jadi "nilai tidak dipakai di runtime" TIDAK berarti "tidak ada di bundle".
 *   Logika seperti `PAYMENT_ENABLED ? URL : ""` tetap meninggalkan URL di
 *   bundle — dan siapa pun yang membacanya bisa membuka checkout langsung.
 *
 * Karena itu pemeriksaan ini menilai HASIL (isi `out/`), bukan niat di sumber:
 *   - pembayaran TUTUP  -> URL checkout HARAM ada di out/
 *   - pembayaran BUKA   -> URL checkout WAJIB ada di out/ (kalau tidak, CTA
 *                          akan tampil "segera hadir" padahal seharusnya jalan)
 *
 * Pakai:
 *   node scripts/check-payment-hidden.mjs
 */
import { readFileSync, existsSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, extname } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const OUT = join(root, "out");

const RED = "\u001b[31m", GRN = "\u001b[32m", YEL = "\u001b[33m", DIM = "\u001b[2m", OFF = "\u001b[0m";

/** Penanda URL checkout. Dua-duanya diperiksa: host dan id produk. */
const CHECKOUT_MARKERS = ["dodopayments.com", "checkout.dodopayments"];
const PRODUCT_ID_RE = /pdt_[A-Za-z0-9]{8,}/g;

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

/** Muat env dengan prioritas Next.js (berkas .local menang). */
function loadEnv(name) {
  for (const f of [".env.production.local", ".env.local", ".env.production", ".env"]) {
    const p = join(root, f);
    if (!existsSync(p)) continue;
    for (const raw of readFileSync(p, "utf8").split(/\r?\n/)) {
      const line = raw.trim().replace(/^\uFEFF/, "");
      const m = line.match(new RegExp(`^${name}\\s*=\\s*(.+)$`));
      if (m) return m[1].trim().replace(/^["']|["']$/g, "");
    }
  }
  return (process.env[name] || "").trim();
}

if (!existsSync(OUT)) {
  console.error(`${RED}✖ check-payment-hidden: ${OUT} tidak ada — jalankan build + export dulu.${OFF}`);
  process.exit(1);
}

const rawEnabled = loadEnv("NEXT_PUBLIC_PAYMENT_ENABLED").toLowerCase();
const enabled = rawEnabled === "true";

const files = walk(OUT);
const hits = [];

for (const f of files) {
  let txt;
  try { txt = readFileSync(f, "utf8"); } catch { continue; }
  const rel = f.slice(OUT.length + 1);
  const markers = CHECKOUT_MARKERS.filter((m) => txt.includes(m));
  const products = txt.match(PRODUCT_ID_RE) || [];
  if (markers.length || products.length) {
    hits.push({ rel, markers, products: [...new Set(products)].slice(0, 3) });
  }
}

console.log(`${DIM}bundle            : ${OUT} (${files.length} berkas dipindai)${OFF}`);
console.log(`${DIM}pembayaran        : ${enabled ? "BUKA (NEXT_PUBLIC_PAYMENT_ENABLED=true)" : "TUTUP"}${OFF}`);

let bad = false;

if (!enabled) {
  if (hits.length) {
    bad = true;
    console.error(`\n${RED}✖ check-payment-hidden: URL checkout MASIH ADA di bundle padahal pembayaran ditutup${OFF}`);
    for (const h of hits.slice(0, 8)) {
      console.error(`${RED}  out/${h.rel}${OFF}  markers=${JSON.stringify(h.markers)} products=${JSON.stringify(h.products)}`);
    }
    console.error(
      `${YEL}  → Periksa SEMUA berkas env, bukan hanya .env.production: Next memuat\n` +
      `${YEL}    .env.production.local > .env.local > .env.production > .env, dan\n` +
      `${YEL}    NEXT_PUBLIC_* di-INLINE ke bundle saat build.\n` +
      `${YEL}    Lalu HAPUS .next/cache sebelum build ulang (cache bisa menyimpan nilai lama).${OFF}\n`
    );
  } else {
    console.log(`${GRN}✔ URL checkout tidak ada di bundle — pembayaran benar-benar tertutup${OFF}`);
  }
} else {
  const found = hits.some((h) => h.markers.length);
  if (!found) {
    bad = true;
    console.error(`\n${RED}✖ check-payment-hidden: pembayaran DIBUKA tetapi URL checkout tidak ada di bundle${OFF}`);
    console.error(`${YEL}  → CTA akan tampil "segera hadir" padahal seharusnya bisa dibayar.${OFF}\n`);
  } else {
    console.log(`${GRN}✔ pembayaran dibuka dan URL checkout ada di bundle${OFF}`);
  }
}

process.exit(bad ? 1 : 0);
