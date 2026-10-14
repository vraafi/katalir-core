import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
// `/templates` + `/integrations` ditambahkan 14 Okt 2026: keduanya adalah rute
// yang pernah kena BUG-10 (kontras teks) tetapi TIDAK pernah ikut diaudit di
// sini — jadi perbaikan kontrasnya tidak punya penjaga regresi. Mengaudit
// rute yang tidak pernah bermasalah sambil melewatkan yang pernah rusak
// membuat skrip ini hijau tanpa membuktikan apa pun.
const routes = ["/", "/pricing", "/docs", "/chat", "/builder", "/templates", "/integrations"];
const b = await chromium.launch(); let critical = 0, serious = 0;
// `waitUntil: "networkidle"` DIGANTI 14 Okt 2026: `/docs` menahan koneksi
// sehingga networkidle tidak pernah tercapai dan skrip mati dengan
// TimeoutError sebelum menilai satu rute pun (audit jadi hijau-palsu: rute
// yang tidak pernah dievaluasi tidak melaporkan pelanggaran). Pola yang
// dipakai sekarang sama dengan harness uji: tunggu `load`, lalu beri jeda
// agar React ter-hidrasi sebelum axe mengukur DOM final.
for (const route of routes) { const ctx = await b.newContext({ viewport: { width: 390, height: 844 } }); const p = await ctx.newPage(); await p.goto(`https://katalir.de5.net${route}`, { waitUntil: "load", timeout: 45000 }); await p.waitForTimeout(2500); const r = await new AxeBuilder({ page: p }).analyze(); critical += r.violations.filter(v => v.impact === "critical").length; serious += r.violations.filter(v => v.impact === "serious").length; console.log(`${route}: VIOLATIONS=${r.violations.length}`); r.violations.forEach(v => console.log(`  [${v.impact}] ${v.id}: ${v.description}`)); await p.close(); }
await b.close(); console.log(`A11Y_CRITICAL=${critical} A11Y_SERIOUS=${serious}`); if (critical || serious) process.exit(1);
