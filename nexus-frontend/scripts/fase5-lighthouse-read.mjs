/**
 * Baca ulang artefak Lighthouse FASE 5 TANPA menjalankan Lighthouse lagi.
 *
 * Kenapa terpisah dari `fase5-lighthouse.mjs`: skrip itu selalu MENJALANKAN
 * Lighthouse (10 run) sehingga tidak bisa dipakai untuk memeriksa ulang angka
 * yang sudah ada. Klaim "100" di laporan harus bisa diverifikasi dari file bukti,
 * bukan dengan mengulang pengukuran (yang bisa menghasilkan angka berbeda).
 *
 * Berkas yang dibaca (yang paling baru menang):
 *   desktop: %TEMP%/lhfd_*.json      (scripts/fase5-lighthouse.cmd)
 *            %TEMP%/lhf_desktop_*.json (scripts/fase5-lighthouse.mjs)
 *   mobile : %TEMP%/lhfm_*.json      (scripts/fase5-lighthouse.cmd)
 *            %TEMP%/lhf_mobile_*.json  (scripts/fase5-lighthouse.mjs)
 *
 * `lhfm2_*` sengaja TIDAK dibaca: itu batch ulang parsial 3 rute (riwayat
 * perbaikan §4.6) yang tidak boleh dianggap sebagai cakupan 5 rute.
 *
 * Pakai: node scripts/fase5-lighthouse-read.mjs
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const ROUTES = ["/", "/settings", "/billing", "/help", "/builder"];
const PRESETS = [
  { key: "desktop", prefixes: ["lhfd_", "lhf_desktop_"] },
  { key: "mobile", prefixes: ["lhfm_", "lhf_mobile_"] },
];

const files = readdirSync(tmpdir()).filter((f) => f.endsWith(".json") && /^lhf/.test(f));

/** Ambil berkas terbaru per (preset, rute). */
function pick(prefix, route) {
  const suffix = (route === "/" ? "root" : route.replace(/\//g, "")) + ".json";
  const matches = files.filter((f) => f.startsWith(prefix) && f.endsWith(suffix));
  if (!matches.length) return null;
  return matches
    .map((f) => ({ f, t: statSync(join(tmpdir(), f)).mtimeMs }))
    .sort((a, b) => b.t - a.t)[0];
}

const rows = [];
for (const preset of PRESETS) {
  for (const route of ROUTES) {
    let art = null;
    for (const prefix of preset.prefixes) {
      const found = pick(prefix, route);
      if (found && (!art || found.t > art.t)) art = found;
    }
    if (!art) {
      rows.push({ preset: preset.key, route, score: null, failed: [], weight0: [], invalid: "TIDAK_ADA_BERKAS" });
      continue;
    }
    const rep = JSON.parse(readFileSync(join(tmpdir(), art.f), "utf-8"));
    // Laporan bisa tersimpan walau navigasi GAGAL (runtimeError, mis.
    // CHROME_INTERSTITIAL_ERROR): skornya null dan tidak ada audit dinilai.
    // Kalau itu ditampilkan sebagai "0 + GAGAL=[]" ia terbaca seolah bersih --
    // jadi laporan seperti ini harus ditandai TIDAK VALID, bukan diberi angka.
    const rawScore = rep.categories?.accessibility?.score ?? null;
    const invalid = rep.runtimeError?.code || (rawScore == null ? "SCORE_NULL" : null);
    const score = invalid ? null : Math.round(rawScore * 100);
    const failed = Object.entries(rep.audits)
      .filter(([, a]) => a && a.scoreDisplayMode === "binary" && a.score !== 1)
      .map(([id]) => id);
    // Audit gagal yang bobotnya 0: skor bisa tetap 100 walau audit merah --
    // persis jebakan `/builder` mobile di FASE 5. Karena itu dipisah.
    const weight0 = Object.entries(rep.audits)
      .filter(([, a]) => a && a.scoreDisplayMode === "binary" && a.score !== 1 && !a.weight)
      .map(([id]) => id);
    const mtime = new Date(art.t).toISOString().replace("T", " ").slice(0, 19);
    rows.push({ preset: preset.key, route, score, failed, weight0, invalid, file: art.f, mtime });
  }
}

console.log("PRESET   RUTE        SKOR BERKAS                                  WAKTU                  VALIDITAS");
for (const r of rows) {
  console.log(
    [
      r.preset.padEnd(8),
      r.route.padEnd(11),
      String(r.score ?? "-").padEnd(4),
      (r.file ?? "(TIDAK ADA)").padEnd(38),
      (r.mtime ?? "").padEnd(21),
      r.invalid ? `TIDAK_VALID=${r.invalid}` : "valid",
    ].join(" ")
  );
}

console.log("\nGAGAL / BOBOT-0:");
for (const r of rows) {
  const failed = r.failed.length ? r.failed.join(",") : "-";
  const w0 = r.weight0.length ? r.weight0.join(",") : "-";
  console.log(`${r.preset}/${r.route}  GAGAL=[${failed}]  BOBOT0=[${w0}]`);
}

const invalidRows = rows.filter((r) => r.invalid);
const perfect =
  rows.length === ROUTES.length * PRESETS.length &&
  rows.every((r) => r.score === 100 && !r.failed.length && !r.invalid);
const hasWeight0 = rows.some((r) => r.weight0.length);
console.log("\n" + (perfect ? "SEMUA_100" : "BELUM_SEMPURNA"));
if (invalidRows.length) {
  console.log(
    `PERINGATAN: ${invalidRows.length} berkas TIDAK VALID (navigasi gagal) -- angkanya TIDAK boleh dipakai: ` +
      invalidRows.map((r) => `${r.preset}${r.route}=${r.invalid}`).join(", ")
  );
}
if (hasWeight0) console.log("PERINGATAN: ada audit merah BERBOBOT 0 (skor 100 menyesatkan)");
