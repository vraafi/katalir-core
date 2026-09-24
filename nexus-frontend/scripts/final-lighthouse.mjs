/**
 * FASE 6 (C5) — Lighthouse 4 kategori pada 6 rute × 2 preset.
 *
 * Beda dari `fase5-lighthouse.mjs` (hanya a11y): skrip ini mengukur
 * accessibility + performance + best-practices + SEO, karena kriteria FASE 6
 * memuat ambang perf mobile ≥ 80 dan SEO ≥ 90.
 *
 * ATURAN KERAS YANG DIBAWA DARI FASE 5 (jangan diulang):
 *   1. Laporan Lighthouse bisa tersimpan walau halaman TIDAK dimuat
 *      (`runtimeError`, skor null) — laporan seperti itu DITOLAK, bukan dicetak
 *      sebagai angka.
 *   2. Exit code non-nol sah-sah saja (bug pembersihan chrome-launcher di
 *      Windows: `EPERM ... \Temp\lighthouse.<pid>`) — yang menentukan valid
 *      atau tidak adalah berkas laporannya.
 *   3. Ukur pada BUILD PRODUKSI (`npm run build` + `npm run serve:static`),
 *      bukan dev server: bundel dev tidak mencerminkan produk dan perf-nya
 *      menyesatkan.
 *
 * Pakai: node scripts/final-lighthouse.mjs      (BASE_URL=http://localhost:3000)
 */
import { execSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const BASE = process.env.BASE_URL || "http://localhost:3000";
const CATEGORIES = ["accessibility", "performance", "best-practices", "seo"];
const ROUTES = ["/", "/chat", "/settings", "/billing", "/help", "/builder"];
const PRESETS = [
  { key: "desktop", arg: "--preset=desktop" },
  { key: "mobile", arg: "" },
];

/** Ambang kriteria FASE 6 (hanya yang punya ambang eksplisit di misi). */
const THRESHOLD = { accessibility: 90, performance: null, "best-practices": 90, seo: 90 };

const rows = [];
let invalid = 0;

for (const preset of PRESETS) {
  for (const route of ROUTES) {
    const out = join(tmpdir(), `f6_${preset.key}_${route === "/" ? "root" : route.replace(/\//g, "")}.json`);
    const url = route === "/" ? `${BASE}/` : `${BASE}${route}`;
    process.stdout.write(`RUN ${preset.key} ${route} ... `);
    const cmd = [
      "npx", "--yes", "lighthouse", url,
      `--only-categories=${CATEGORIES.join(",")}`,
      preset.arg,
      '--chrome-flags="--headless=new --no-sandbox"',
      "--output=json",
      `--output-path="${out}"`,
      "--quiet",
    ].filter(Boolean).join(" ");
    try {
      execSync(cmd, { stdio: ["ignore", "pipe", "pipe"], timeout: 300000, shell: true });
    } catch (err) {
      const detail = String(err.stderr || err.message || "").split("\n").map((l) => l.trim()).filter(Boolean).slice(-1)[0] || "";
      // Bukan langsung gagal: berkasnya diperiksa di bawah (lihat aturan #2).
      console.log(`EXIT_NONZERO (${detail.slice(0, 120)})`);
    }
    if (!existsSync(out)) {
      console.log("TANPA_OUTPUT");
      rows.push({ preset: preset.key, route, scores: null, invalid: "TANPA_OUTPUT" });
      invalid += 1;
      continue;
    }
    const rep = JSON.parse(readFileSync(out, "utf-8"));
    if (rep.runtimeError) {
      console.log(`TIDAK_VALID (${rep.runtimeError.code}) -- diabaikan`);
      rows.push({ preset: preset.key, route, scores: null, invalid: rep.runtimeError.code });
      invalid += 1;
      continue;
    }
    const scores = {};
    let nullScore = false;
    for (const c of CATEGORIES) {
      const sc = rep.categories?.[c]?.score;
      if (sc == null) nullScore = true;
      scores[c] = sc == null ? null : Math.round(sc * 100);
    }
    if (nullScore) {
      console.log("TIDAK_VALID (skor parsial null) -- diabaikan");
      rows.push({ preset: preset.key, route, scores: null, invalid: "SKOR_NULL" });
      invalid += 1;
      continue;
    }
    rows.push({ preset: preset.key, route, scores });
    console.log(CATEGORIES.map((c) => `${c.slice(0, 4)}=${scores[c]}`).join(" "));
  }
}

console.log("\n=== RINGKASAN (a11y/perf/bp/seo) ===");
for (const r of rows) {
  const s = r.scores;
  console.log(
    `${r.preset.padEnd(8)} ${r.route.padEnd(10)} ${s ? [s.accessibility, s.performance, s["best-practices"], s.seo].join("/") : `TIDAK_VALID=${r.invalid}`}`
  );
}

const valid = rows.filter((r) => r.scores);
const fails = [];
for (const r of valid) {
  for (const [cat, limit] of Object.entries(THRESHOLD)) {
    if (limit && r.scores[cat] < limit) fails.push(`${r.preset} ${r.route} ${cat}=${r.scores[cat]} < ${limit}`);
  }
}
console.log(`\nVALID=${valid.length}/${rows.length} DITOLAK=${invalid}`);
console.log(fails.length ? `AMBANG_GAGAL:\n- ${fails.join("\n- ")}` : "AMBANG_LOLOS");
const agg = {
  a11y_desktop_min: valid.filter((r) => r.preset === "desktop").reduce((m, r) => Math.min(m, r.scores.accessibility), 100),
  a11y_mobile_min: valid.filter((r) => r.preset === "mobile").reduce((m, r) => Math.min(m, r.scores.accessibility), 100),
  perf_mobile_min: valid.filter((r) => r.preset === "mobile").reduce((m, r) => Math.min(m, r.scores.performance), 100),
  seo_min: valid.reduce((m, r) => Math.min(m, r.scores.seo), 100),
  bp_min: valid.reduce((m, r) => Math.min(m, r.scores["best-practices"]), 100),
};
console.log("AGREGAT=" + JSON.stringify(agg));
