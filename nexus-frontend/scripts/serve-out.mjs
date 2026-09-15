/**
 * Server statis minimal untuk `out/` (hasil `next build` dengan `output: "export"`).
 *
 * KENAPA BUKAN `next start`: app ini di-build sebagai static export (Cloudflare
 * Pages), sehingga `next start` tidak berlaku — Next.js menolaknya dan tidak ada
 * server Node yang merender halaman. Build produksi yang setara untuk app ini
 * adalah "out/ disajikan statis", itulah yang direplikasi di sini.
 *
 * Tujuan: Playwright bisa menguji PRODUCTION BUILD (bundle ter-minify, env
 * NEXT_PUBLIC_* yang sudah ter-inline saat build) — bukan `next dev`. Dev server
 * menyajikan data/perilaku berbeda, dan itulah yang membuat bug filter/badge
 * lolos dari tes sebelumnya.
 *
 * Tanpa dependensi eksternal supaya tidak menambah paket hanya untuk tes.
 */
import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize } from "node:path";

const ROOT = join(process.cwd(), "out");
const PORT = Number(process.env.PORT || 3000);

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".webp": "image/webp",
  ".ico": "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".txt": "text/plain; charset=utf-8",
};

if (!existsSync(ROOT)) {
  console.error(`out/ tidak ada — jalankan "npm run build" dulu (dicari: ${ROOT})`);
  process.exit(1);
}

const server = createServer((req, res) => {
  const urlPath = decodeURIComponent((req.url || "/").split("?")[0]);
  // Cegah path traversal: normalisasi lalu pastikan tetap di dalam ROOT.
  const safe = normalize(urlPath).replace(/^(\.\.[/\\])+/, "");
  let filePath = join(ROOT, safe);

  // Direktori -> index.html; rute tanpa ekstensi -> coba .html lalu .txt
  // (Next.js static export memakai pola ini untuk /foo -> foo.html).
  if (existsSync(filePath) && statSync(filePath).isDirectory()) {
    filePath = join(filePath, "index.html");
  } else if (!existsSync(filePath) && !extname(filePath)) {
    for (const cand of [`${filePath}.html`, join(filePath, "index.html")]) {
      if (existsSync(cand)) {
        filePath = cand;
        break;
      }
    }
  }

  if (!filePath.startsWith(ROOT) || !existsSync(filePath)) {
    res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    res.end("404");
    return;
  }

  res.writeHead(200, {
    "Content-Type": TYPES[extname(filePath).toLowerCase()] || "application/octet-stream",
    "Cache-Control": "no-store",
  });
  createReadStream(filePath).pipe(res);
});

server.listen(PORT, () => {
  console.log(`[serve-out] produksi statis di http://127.0.0.1:${PORT} (root: ${ROOT})`);
});