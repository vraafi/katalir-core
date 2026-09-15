/**
 * GLOBAL SETUP Playwright — menyiapkan fixture auth E2E yang bersifat ARTEFAK.
 *
 * MASALAH YANG DIPERBAIKI (dibuktikan, bukan dugaan):
 *   `_e2e_session*.json` & `_e2e_storage*.json` ada di .gitignore (benar — isinya
 *   bearer token hidup), TETAPI tidak ada skrip yang menghasilkannya. Akibatnya:
 *     1. `_e2e_session.json` tertinggal 2,2 hari (exp -194087s) -> spec chat-auth
 *        gagal dengan pesan menyesatkan "injeksi session gagal".
 *     2. `_e2e_storage.json` tidak pernah ada -> spec _ux/_uxburst error ENOENT
 *        yang terbaca seperti bug produk, padahal fixture hilang.
 *   Gejala kelas ini (fixture kadaluwarsa terbaca sebagai "bug produk") adalah
 *   persis yang menyebabkan investigasi 401 panjang: backend benar, token ada,
 *   hanya fixture-nya basi.
 *
 * YANG DILAKUKAN SEBELUM TEST JALAN:
 *   - Pilih sesi paling sehat dari kandidat: pakai access_token yang masih valid
 *     (> 60s) bila ada; bila semua kedaluwarsa, TUKAR refresh_token lewat
 *     `grant_type=refresh_token` (tanpa dependensi tambahan, cukup fetch).
 *   - Tulis hasilnya ke `_e2e_session.refreshed.json` (dibaca model-filter.spec)
 *     dan `_e2e_storage.json` (storageState untuk spec yang memakainya).
 *
 * SENGAJA TIDAK PERNAH GAGAL TOTAL: bila penukaran token gagal (mis. refresh
 * token sudah dicabut), setup hanya memberi peringatan. Spec tetap punya guard
 * sendiri (assert TTL dengan instruksi jelas), sehingga kegagalan muncul di
 * tempat yang tepat — bukan sebagai crash setup yang menyembunyikan sebab.
 */
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const ROOT = process.cwd();
const FRONTEND_PORT = Number(process.env.E2E_PORT || 3000);
const ORIGIN = `http://localhost:${FRONTEND_PORT}`;
const MIN_TTL_S = 60;

/** Baca env dari .env.local lalu ../.env (konvensi repo ini). */
function envValue(...names) {
  for (const file of [".env.local", "../.env", ".env"]) {
    const p = join(ROOT, file);
    if (!existsSync(p)) continue;
    const text = readFileSync(p, "utf-8");
    for (const name of names) {
      const m = text.match(new RegExp(`^\\s*${name}\\s*=\\s*(.+)\\s*$`, "m"));
      if (m) return m[1].replace(/^["']|["']$/g, "").trim();
    }
  }
  return process.env[names[0]] ?? "";
}

const SUPABASE_URL = envValue("NEXT_PUBLIC_SUPABASE_URL", "SUPABASE_URL").replace(/\/+$/, "");
const ANON_KEY = envValue(
  "NEXT_PUBLIC_SUPABASE_ANON_KEY",
  "NEXT_PUBLIC_SUPABASE_KEY",
  "SUPABASE_ANON_KEY",
  "SUPABASE_PUBLISHABLE_KEY",
  "SUPABASE_KEY"
);

const REF = SUPABASE_URL.match(/https?:\/\/([a-z0-9]+)\.supabase/)?.[1];
const LS_KEY = `sb-${REF ?? "unknown"}-auth-token`;

/** Kandidat dari paling baru ke paling lama. */
const CANDIDATES = [
  "_e2e_session.refreshed.json",
  "_e2e_session.extended.json",
  "_e2e_session.json",
];

function ttl(token) {
  try {
    const p = JSON.parse(Buffer.from(token.split(".")[1] ?? "", "base64url").toString("utf-8"));
    return typeof p.exp === "number" ? p.exp - Math.floor(Date.now() / 1000) : -1;
  } catch {
    return -1;
  }
}

function readSession(file) {
  const p = join(ROOT, file);
  if (!existsSync(p)) return null;
  try {
    const s = JSON.parse(readFileSync(p, "utf-8"));
    return s?.access_token ? s : null;
  } catch {
    return null;
  }
}

/** Tukar refresh_token -> sesi baru (endpoint GoTrue standar). */
async function refresh(session) {
  if (!session?.refresh_token || !SUPABASE_URL || !ANON_KEY) return null;
  try {
    const r = await fetch(`${SUPABASE_URL}/auth/v1/token?grant_type=refresh_token`, {
      method: "POST",
      headers: { apikey: ANON_KEY, "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: session.refresh_token }),
    });
    if (!r.ok) {
      console.log(`[e2e-auth] refresh ditolak HTTP ${r.status}`);
      return null;
    }
    const s = await r.json();
    if (!s?.access_token) return null;
    // GoTrue mengirim expires_in (detik); sesi butuh expires_at (epoch) agar
    // lolos `_isValidSession()` auth-js ('expires_at' in session).
    s.expires_at = Math.floor(Date.now() / 1000) + Number(s.expires_in ?? 3600);
    return s;
  } catch (e) {
    console.log(`[e2e-auth] refresh gagal: ${String(e)}`);
    return null;
  }
}

/** Tulis storageState agar spec dengan `test.use({ storageState })` bekerja. */
function writeStorageState(session) {
  writeFileSync(
    join(ROOT, "_e2e_storage.json"),
    JSON.stringify(
      {
        cookies: [],
        origins: [
          { origin: ORIGIN, localStorage: [{ name: LS_KEY, value: JSON.stringify(session) }] },
        ],
      },
      null,
      2
    )
  );
}

export default async function globalSetup() {
  console.log(`[e2e-auth] ref=${REF ?? "?"} key=${LS_KEY} origin=${ORIGIN}`);

  let chosen = null;
  let source = null;

  // 1) Pakai yang masih hidup — menghindari pemakaian refresh token yang bisa
  //    memicu deteksi reuse di Supabase (rotasi refresh token).
  for (const f of CANDIDATES) {
    const s = readSession(f);
    if (s && ttl(s.access_token) > MIN_TTL_S) {
      chosen = s;
      source = `${f} (masih valid, ttl=${ttl(s.access_token)}s)`;
      break;
    }
  }

  // 2) Semua kedaluwarsa -> tukar refresh token, kandidat terbaru lebih dulu.
  if (!chosen) {
    for (const f of CANDIDATES) {
      const s = readSession(f);
      if (!s) continue;
      console.log(`[e2e-auth] ${f} kedaluwarsa (ttl=${ttl(s.access_token)}s) -> refresh`);
      const fresh = await refresh(s);
      if (fresh) {
        chosen = fresh;
        source = `${f} (hasil refresh, ttl=${ttl(fresh.access_token)}s)`;
        break;
      }
    }
  }

  if (!chosen) {
    console.log(
      "[e2e-auth] PERINGATAN: tidak ada sesi E2E yang valid. Spec yang butuh auth " +
        "akan gagal pada guard TTL-nya (bukan crash di sini). Perbarui " +
        "_e2e_session.json dengan login baru."
    );
    return;
  }

  writeFileSync(join(ROOT, "_e2e_session.refreshed.json"), JSON.stringify(chosen, null, 2));
  writeStorageState(chosen);
  console.log(`[e2e-auth] siap: ${source}`);
  console.log(
    `[e2e-auth] email=${chosen.user?.email ?? "?"} -> _e2e_session.refreshed.json + _e2e_storage.json`
  );
}