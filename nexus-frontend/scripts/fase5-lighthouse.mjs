/**
 * Lighthouse a11y FASE 5: 5 rute x 2 preset, hasil ditulis ke %TEMP%/lhf_<preset>_<route>.json.
 *
 * Kenapa skrip: menjalankan `lighthouse` berulang dari shell PowerShell rawan
 * salah kutip (nama rute "/" jadi argumen kosong) dan hasilnya harus bisa dibaca
 * ulang sebagai angka, bukan "kelihatannya hijau". Skrip ini mencetak SATU baris
 * per rute: SKOR + daftar audit biner yang gagal, sehingga klaim "100" bisa
 * diverifikasi langsung dari output.
 */
import { execSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const BASE = process.env.BASE_URL || "http://localhost:3000";
const ALL_ROUTES = ["/", "/settings", "/billing", "/help", "/builder"];
// Filter debug: mengizinkan satu rute/preset diukur ulang tanpa menunggu 10 run.
// Tanpa ini, setiap diagnosis berarti menjalankan batch penuh (~2 menit).
const ONLY_ROUTE = process.env.ONLY_ROUTE || "";
const ONLY_PRESET = process.env.ONLY_PRESET || "";
const ROUTES = ONLY_ROUTE ? ALL_ROUTES.filter((r) => r === ONLY_ROUTE) : ALL_ROUTES;
if (!ROUTES.length) {
  console.log(`ONLY_ROUTE="${ONLY_ROUTE}" tidak ada di ${JSON.stringify(ALL_ROUTES)}`);
  process.exit(2);
}
const PRESETS = [
  { key: "desktop", arg: "--preset=desktop" },
  { key: "mobile", arg: "" },
].filter((p) => !ONLY_PRESET || p.key === ONLY_PRESET);

const results = [];

for (const preset of PRESETS) {
  for (const route of ROUTES) {
    const out = join(tmpdir(), `lhf_${preset.key}_${route === "/" ? "root" : route.replace(/\//g, "")}.json`);
    const url = route === "/" ? `${BASE}/` : `${BASE}${route}`;
    process.stdout.write(`RUN ${preset.key} ${route} ... `);
    // Perintah dibentuk sebagai SATU string: `--chrome-flags` berisi spasi, dan
    // meneruskannya sebagai array dengan `shell:true` membuat tanda kutip hilang
    // (terbukti: seluruh batch gagal "Command failed"). Dikutip eksplisit di sini.
    const cmd = [
      "npx",
      "--yes",
      "lighthouse",
      url,
      "--only-categories=accessibility",
      preset.arg,
      '--chrome-flags="--headless=new --no-sandbox"',
      "--output=json",
      `--output-path="${out}"`,
      "--quiet",
    ]
      .filter(Boolean)
      .join(" ");
    try {
      execSync(cmd, { stdio: ["ignore", "pipe", "pipe"], timeout: 300000, shell: true });
    } catch (err) {
      // JEBAKAN YANG TERBUKTI (2026-09-24): `npx lighthouse` bisa keluar dengan
      // status != 0 HANYA karena bug pembersihan chrome-launcher di Windows
      // ("EPERM, Permission denied: ...\Temp\lighthouse.<pid>") -- padahal
      // laporannya sudah selesai ditulis. Versi lama skrip ini langsung `continue`
      // di sini, jadi laporan yang SAH dibuang dan batch tampak gagal total.
      // Karena itu kegagalan exit code tidak dipercaya sendirian: berkasnya
      // diperiksa dulu di bawah, dan hanya berkas yang tidak ada/tidak valid
      // yang dianggap gagal.
      const detail = String(err.stderr || err.message || "")
        .split("\n")
        .map((l) => l.trim())
        .filter(Boolean)
        .slice(-2)
        .join(" | ")
        .slice(0, 240);
      console.log(`EXIT_NONZERO (${detail}) -- berkas laporan tetap diperiksa`);
    }
    if (!existsSync(out)) {
      console.log("TANPA_OUTPUT");
      results.push({ preset: preset.key, route, score: null, failed: [], invalid: "TANPA_OUTPUT" });
      continue;
    }
    const rep = JSON.parse(readFileSync(out, "utf-8"));
    // PENTING: laporan Lighthouse BISA tersimpan walau navigasi gagal
    // (`runtimeError`, mis. CHROME_INTERSTITIAL_ERROR). Dalam keadaan itu
    // `categories.accessibility.score` = null dan TIDAK ada audit yang dinilai,
    // sehingga versi lama skrip ini mencetak `SKOR=0 GAGAL=[]` -- terbaca seperti
    // "nol pelanggaran", padahal halaman tidak pernah dimuat. Karena itu laporan
    // semacam ini WAJIB ditolak, bukan dilaporkan sebagai angka.
    const score = rep.categories.accessibility.score == null ? null : Math.round(rep.categories.accessibility.score * 100);
    if (rep.runtimeError || score == null) {
      const code = rep.runtimeError?.code || "SCORE_NULL";
      const scored = Object.values(rep.audits || {}).filter((a) => a && a.scoreDisplayMode === "binary" && a.score !== null).length;
      results.push({ preset: preset.key, route, score: null, failed: [], invalid: code });
      console.log(`TIDAK_VALID (${code}) audit_dinilai=${scored} -- laporan diabaikan`);
      continue;
    }
    const failed = Object.entries(rep.audits)
      .filter(([, a]) => a && a.scoreDisplayMode === "binary" && a.score !== 1)
      .map(([id]) => id);
    results.push({ preset: preset.key, route, score, failed });
    console.log(`SKOR=${score} GAGAL=[${failed.join(",")}]`);
  }
}

console.log("\n=== RINGKASAN ===");
for (const r of results) {
  const verdict = r.invalid ? `TIDAK_VALID=${r.invalid}` : r.failed.length ? "GAGAL=" + r.failed.join(",") : "BERSIH";
  console.log(`${r.preset.padEnd(8)} ${r.route.padEnd(10)} ${r.score ?? "-"} ${verdict}`);
}
const allPerfect = results.length === ROUTES.length * PRESETS.length && results.every((r) => r.score === 100 && !r.invalid);
const invalid = results.filter((r) => r.invalid);
console.log(allPerfect ? "SEMUA_100" : `BELUM_SEMPURNA (${results.length} hasil${invalid.length ? `, ${invalid.length} tidak valid` : ""})`);