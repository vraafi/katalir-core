/**
 * Sakelar pembayaran terpusat (FASE 7 — "tutup payment, coming soon").
 *
 * MASALAH YANG DIPECAHKAN: sebelumnya SETIAP komponen membaca
 * `process.env.NEXT_PUBLIC_DODO_CHECKOUT_URL` sendiri-sendiri (billing,
 * UserMenu, ModelSelector). Artinya "mematikan pembayaran" menuntut menghapus
 * satu variabel env lalu membangun ulang — dan satu tempat yang terlewat
 * otomatis tetap menampilkan tautan checkout yang masih hidup. Tidak ada satu
 * titik pun untuk mengauditnya.
 *
 * KONTRAK:
 *   PAYMENT_ENABLED  — satu-satunya sumber kebenaran. Default **false**.
 *   CHECKOUT_URL     — "" bila pembayaran mati. Komponen yang hanya tahu
 *                      "ada URL / tidak ada URL" otomatis ikut mati.
 *
 * Default `false` dipilih sengaja (fail-closed): env yang lupa di-set, typo,
 * atau build tanpa `.env.production` TIDAK akan membuka kembali tombol bayar.
 * Untuk membuka, set `NEXT_PUBLIC_PAYMENT_ENABLED=true` **dan** isi
 * `NEXT_PUBLIC_DODO_CHECKOUT_URL` (di-INLINE saat build → perlu build ulang).
 */
const RAW_ENABLED = (process.env.NEXT_PUBLIC_PAYMENT_ENABLED || "").trim().toLowerCase();

/** `true` hanya bila dinyatakan eksplisit. Apa pun selain "true" = mati. */
export const PAYMENT_ENABLED = RAW_ENABLED === "true";

const RAW_CHECKOUT = (process.env.NEXT_PUBLIC_DODO_CHECKOUT_URL || "").trim();

/** URL checkout yang boleh dipakai — kosong saat pembayaran dimatikan. */
export const CHECKOUT_URL = PAYMENT_ENABLED ? RAW_CHECKOUT : "";

/** Penanda untuk UI: tampilkan lencana/notifikasi "segera hadir". */
export const PAYMENT_COMING_SOON = !PAYMENT_ENABLED;
