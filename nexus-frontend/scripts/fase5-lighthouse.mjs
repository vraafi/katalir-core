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
const ROUTES = ["/", "/settings", "/billing", "/help", "/builder"];
const PRESETS = [
  { key: "desktop", arg: "--preset=desktop" },
  { key: "mobile", arg: "" },
];

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
      execSync(cmd, { stdio: "ignore", timeout: 300000, shell: true });
    } catch (err) {
      console.log(`LIGHTHOUSE_GAGAL (${String(err).slice(0, 120)})`);
      continue;
    }
    if (!existsSync(out)) {
      console.log("TANPA_OUTPUT");
      continue;
    }
    const rep = JSON.parse(readFileSync(out, "utf-8"));
    const score = Math.round((rep.categories.accessibility.score ?? 0) * 100);
    const failed = Object.entries(rep.audits)
      .filter(([, a]) => a && a.scoreDisplayMode === "binary" && a.score !== 1)
      .map(([id]) => id);
    results.push({ preset: preset.key, route, score, failed });
    console.log(`SKOR=${score} GAGAL=[${failed.join(",")}]`);
  }
}

console.log("\n=== RINGKASAN ===");
for (const r of results) console.log(`${r.preset.padEnd(8)} ${r.route.padEnd(10)} ${r.score} ${r.failed.length ? "GAGAL=" + r.failed.join(",") : "BERSIH"}`);
const allPerfect = results.length === ROUTES.length * PRESETS.length && results.every((r) => r.score === 100);
console.log(allPerfect ? "SEMUA_100" : `BELUM_SEMPURNA (${results.length} hasil)`);