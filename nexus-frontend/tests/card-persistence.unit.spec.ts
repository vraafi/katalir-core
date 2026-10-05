/**
 * Tes satuan murni untuk `decodePersistedCard` — dekoder yang menyelamatkan
 * kartu kredensial/approval saat halaman di-refresh (Bug #3, 6 Okt 2026).
 *
 * KENAPA INI ADA
 * --------------
 * `tests/card-persistence.spec.ts` membuktikan rantai lengkapnya di browser,
 * tetapi ia butuh `next build` + server statis. Tes ini menjaga HAL YANG SAMA
 * di level fungsi, sehingga regresi pada decoder tertangkap dalam hitungan
 * detik tanpa toolchain build:
 *
 *   * baris `role="system"` berisi envelope `{__katalir_card}` didekode jadi
 *     ChatMessage BERTIPE (bukan dibiarkan sebagai pesan teks kosong);
 *   * `_localId` diisi — TANPA ini kartu dibuang `overlay` di `ChatApp` dan
 *     fitur ini mati lagi tanpa error apa pun (persis bug yang diperbaiki);
 *   * nama field backend (snake_case: `display_name`, `resume_token`,
 *     `approval_token`) dipetakan ke bentuk camelCase frontend;
 *   * baris biasa (user/assistant) dan JSON yang bukan kartu TIDAK diubah.
 *
 * Dijalankan oleh Playwright (runner yang sudah ada di repo) — tanpa browser,
 * karena yang diuji hanya fungsi murni.
 */
import { test, expect } from "@playwright/test";
import { decodePersistedCard } from "../src/features/chat/hooks/useChat";
import type { ChatMessage } from "../src/features/chat/hooks/useChat";

/** Bikin baris persis seperti yang ditulis `_persist_card` di api_server.py. */
function serverRow(id: string, payload: Record<string, unknown>): ChatMessage {
  return {
    id,
    role: "system",
    content: JSON.stringify({ __katalir_card: payload.type, ...payload }),
  };
}

test("credential_form: envelope server menjadi kartu bertipe + _localId stabil", () => {
  const row = serverRow("m-card-1", {
    type: "credential_form",
    provider: "supabase",
    display_name: "Supabase",
    icon: "supabase",
    fields: [
      { name: "project_url", type: "url", label: "Project URL" },
      { name: "service_role_key", type: "password", label: "Service Role Key" },
    ],
    resume_token: "resume-abc",
    original: "sambungkan supabase",
  });

  const out = decodePersistedCard(row);

  expect(out.type).toBe("credential_form");
  expect(out.provider).toBe("supabase");
  expect(out.displayName).toBe("Supabase");
  expect(out.icon).toBe("supabase");
  expect(out.fields?.map((f) => f.name)).toEqual(["project_url", "service_role_key"]);
  expect(out.resumeToken).toBe("resume-abc");
  expect(out.original).toBe("sambungkan supabase");
  // KUNCI BUG #3: kartu tanpa `_localId` dibuang oleh filter `overlay`.
  expect(out._localId).toBe("srv-card-m-card-1");
  // Isi mentah envelope tidak boleh bocor sebagai teks bubble.
  expect(out.content).toBe("");
});

test("approval_prompt: token persetujuan ikut terbawa setelah refresh", () => {
  const row = serverRow("m-card-2", {
    type: "approval_prompt",
    tool: "TELEGRAM",
    toolArgs: { chat_id: "-100123", text: "laporan" },
    reason: "Mengirim data ke pihak luar.",
    alignment: "not_aligned",
    approval_token: "tok.header.sig",
    original: "kirim ke telegram",
  });

  const out = decodePersistedCard(row);

  expect(out.type).toBe("approval_prompt");
  expect(out.tool).toBe("TELEGRAM");
  expect(out.toolArgs).toEqual({ chat_id: "-100123", text: "laporan" });
  expect(out.reason).toBe("Mengirim data ke pihak luar.");
  expect(out.alignment).toBe("not_aligned");
  // Tanpa token, `thread.tsx` menampilkan "Persetujuan tidak tersedia".
  expect(out.approvalToken).toBe("tok.header.sig");
  expect(out._localId).toBe("srv-card-m-card-2");
});

test("oauth_prompt: connect_url diambil dari connect_url ATAU oauth_url", () => {
  const a = decodePersistedCard(
    serverRow("m-a", { type: "oauth_prompt", provider: "gdrive", connect_url: "https://x/a" }),
  );
  const b = decodePersistedCard(
    serverRow("m-b", { type: "oauth_prompt", provider: "gdrive", oauth_url: "https://x/b" }),
  );
  expect(a.connectUrl).toBe("https://x/a");
  expect(b.connectUrl).toBe("https://x/b");
  expect(a.type).toBe("oauth_prompt");
});

test("error: kartu error dari policy gate bertahan sebagai kartu error", () => {
  const out = decodePersistedCard(
    serverRow("m-e", { type: "error", content: "Allowlist menolak argumen `to`.", original: "kirim email" }),
  );
  expect(out.type).toBe("error");
  expect(out.content).toBe("Allowlist menolak argumen `to`.");
  expect(out._localId).toBe("srv-card-m-e");
});

test("baris biasa TIDAK diubah (user/assistant tetap apa adanya)", () => {
  const user: ChatMessage = { id: "u1", role: "user", content: "halo" };
  const asst: ChatMessage = { id: "a1", role: "assistant", content: "Baik." };
  expect(decodePersistedCard(user)).toBe(user);
  expect(decodePersistedCard(asst)).toBe(asst);
});

test("JSON tanpa sentinel kartu TIDAK diubah (tidak salah tebak)", () => {
  const row: ChatMessage = { id: "s1", role: "system", content: JSON.stringify({ foo: "bar" }) };
  expect(decodePersistedCard(row)).toBe(row);
});

test("content bukan JSON tetap diteruskan (tidak melempar)", () => {
  const row: ChatMessage = { id: "s2", role: "system", content: "catatan sistem biasa" };
  expect(decodePersistedCard(row)).toBe(row);
  const broken: ChatMessage = { id: "s3", role: "system", content: "{ rusak" };
  expect(decodePersistedCard(broken)).toBe(broken);
});
