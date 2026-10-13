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
import { createBrotliCompress, createGzip } from "node:zlib";
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

  // Rute tanpa ekstensi -> coba `.html` DULU, baru `<dir>/index.html`.
  //
  // JEBAKAN YANG TERBUKTI (2026-10-13, BUG-10): urutan sebaliknya (direktori
  // dulu) membuat `/integrations` 404 di server lokal. Penyebabnya: static
  // export menghasilkan `out/integrations.html` UNTUK rute `/integrations`
  // sekaligus folder `out/integrations/` untuk rute anak `/integrations/catalog`.
  // Deteksi "ada direktori bernama sama" menang, `integrations/index.html` tidak
  // ada, dan permintaan dijawab 404 — padahal Cloudflare Pages (produksi) dan
  // Next.js memakai `integrations.html`. Akibatnya audit a11y `/integrations`
  // mengukur HALAMAN 404, bukan halaman aslinya (temuan palsu
  // `document-title`/`html-has-lang`/`landmark-one-main`). Urutan yang benar
  // adalah yang dipakai produksi: `foo.html` menang atas `foo/index.html`.
  if (!extname(filePath)) {
    for (const cand of [`${filePath}.html`, join(filePath, "index.html")]) {
      if (existsSync(cand) && statSync(cand).isFile()) {
        filePath = cand;
        break;
      }
    }
  }
  // Sisa kasus: path memang direktori (mis. `/`) -> sajikan index.html-nya.
  if (existsSync(filePath) && statSync(filePath).isDirectory()) {
    filePath = join(filePath, "index.html");
  }

  if (!filePath.startsWith(ROOT) || !existsSync(filePath)) {
    res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    res.end("404");
    return;
  }

  const type = TYPES[extname(filePath).toLowerCase()] || "application/octet-stream";
  // KOMPRESI (FASE 6 lanjutan): sebelumnya server ini mengirim JS apa adanya,
  // sehingga Lighthouse mengukur ~1,38 MB script untuk halaman yang hanya
  // menampilkan hero login. Cloudflare Pages (produksi sebenarnya) mengompres
  // otomatis (gzip/brotli), jadi TANPA kompresi di sini pengukurannya tidak
  // mewakili produk -- dan keputusan optimasi bisa salah sasaran.
  const compressible = /^(text\/|application\/(javascript|json|xml)|image\/svg)/.test(type);
  const accept = String(req.headers["accept-encoding"] || "");
  const headers = { "Content-Type": type, "Cache-Control": "no-store", Vary: "Accept-Encoding" };
  let body = createReadStream(filePath);
  if (compressible && /\bbr\b/.test(accept)) {
    headers["Content-Encoding"] = "br";
    body = body.pipe(createBrotliCompress());
  } else if (compressible && /\bgzip\b/.test(accept)) {
    headers["Content-Encoding"] = "gzip";
    body = body.pipe(createGzip());
  }
  res.writeHead(200, headers);
  body.pipe(res);
});

server.listen(PORT, () => {
  console.log(`[serve-out] produksi statis di http://127.0.0.1:${PORT} (root: ${ROOT})`);
});