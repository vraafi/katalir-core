/**
 * Tes satuan murni (tanpa browser): registry `nodeTypes` React Flow HARUS
 * mencakup SETIAP kind yang ada di `META`.
 *
 * KENAPA INI ADA
 * --------------
 * Bug nyata yang ditemukan lewat E2E: node `code` ditambahkan ke store dengan
 * benar (id, `data.kind`, default config semuanya ada) tetapi di kanvas tampil
 * sebagai **kotak bawaan React Flow** — bukan kartu Katalir. Penyebabnya:
 * `NODE_TYPES` tidak punya kunci `code`.
 *
 * Yang membuat bug ini mahal: React Flow **tidak melempar error** untuk
 * `nodeTypes[kind]` yang tidak ada. Ia diam-diam memakai node bawaannya, yang
 * TIDAK punya `data-testid="node-card"` — jadi gejalanya adalah "node tidak
 * muncul" sementara store sudah benar, dan tidak ada satu pun pesan error yang
 * menunjuk ke penyebabnya.
 *
 * Tes ini menutup celah itu dalam hitungan milidetik: menambah kind ke `META`
 * tanpa menambahkannya ke `NODE_TYPES` langsung gagal di sini.
 *
 * Dijalankan oleh Playwright (runner yang sudah ada di repo) — tanpa browser,
 * karena yang diuji hanya dua objek biasa.
 */
import { test, expect } from "@playwright/test";
import { META } from "../src/features/builder/types";
import { NODE_TYPES } from "../src/features/builder/nodes";

test("NODE_TYPES mencakup SETIAP kunci META (tidak ada kind tanpa komponen)", () => {
  const kinds = Object.keys(META).sort();
  const registered = Object.keys(NODE_TYPES).sort();
  console.log(`[node-types] META=${JSON.stringify(kinds)}`);
  console.log(`[node-types] NODE_TYPES=${JSON.stringify(registered)}`);
  const missing = kinds.filter((k) => !registered.includes(k));
  expect(missing, `kind tanpa komponen node: ${missing.join(", ")}`).toHaveLength(0);
  expect(registered).toEqual(kinds);
});

test("setiap kunci META punya komponen node yang benar-benar ada", () => {
  for (const [kind, comp] of Object.entries(NODE_TYPES)) {
    expect(comp, `NODE_TYPES.${kind} kosong`).toBeTruthy();
    expect(typeof comp, `NODE_TYPES.${kind} bukan komponen`).not.toBe("string");
  }
});

test("setiap kind META punya label + desc + warna yang tidak kosong", () => {
  for (const [kind, meta] of Object.entries(META)) {
    expect(meta.label, `${kind}.label kosong`).toBeTruthy();
    expect(meta.desc, `${kind}.desc kosong`).toBeTruthy();
    expect(meta.color, `${kind}.color kosong`).toMatch(/^rgb\(/);
    expect(meta.Icon, `${kind}.Icon kosong`).toBeTruthy();
  }
});

test("kind 'code' terdaftar DAN punya metadata lengkap", () => {
  expect(Object.keys(META)).toContain("code");
  expect(Object.keys(NODE_TYPES)).toContain("code");
  console.log(`[node-types] code.label="${META.code.label}" desc="${META.code.desc}"`);
  expect(META.code.label).toBe("Kode");
  expect(META.code.desc).toContain("sandbox");
});
