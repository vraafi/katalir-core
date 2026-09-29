# Audit — Integrasi OAuth yang "hilang"

Diperiksa 29 September 2026,terhadap laporan user: "Slack + Google Sheets
sering hilang — sudah connect, beberapa saat kemudian Not connected lagi."

## Root cause: BUKAN database. UI salah baca "tidak diketahui" sebagai "terputus."

Tiga hipotesis yang diminta diperiksa, dan hasil masing-masing:

| Hipotesis | Hasil | Bukti |
|---|---|---|
| Logout menghapus row vault | **DITOLAK** | `src/context/auth.tsx:153-158` — `signOut()` hanya `await supabase.auth.signOut()` lalu membersihkan state lokal. Tidak ada panggilan delete/revoke ke vault. |
| Cleanup routine di backend | **TIDAK DITEMUKAN** | Tidak ada `DELETE FROM user_vault` di repo. (Kode OAuth backend berjalan di Railway, bukan repo ini — jadi ini dicek dari sisi klien.) |
| Session expiry | **TERKONFIRMASI sebagai pemicu** | Lihat di bawah. |

### Bukti utama

`src/components/OAuthConnections.tsx`, sebelum perbaikan:

```tsx
} catch {
  next[card.id] = { loaded: true, connected: false, target: "", configured: false, error: true };
}
```

Lalu di render:

```tsx
) : st?.connected ? (<span>Connected</span>) : (<span>Not connected</span>)}
```

Field `error` **sudah diisi** tapi tidak pernah dipakai untuk membedakan.
Jadi tiga kondisi berbeda — terhubung, tidak terhubung, dan **tidak bisa
dipastikan** — diratakan menjadi dua, dan yang ketiga ditampilkan
sebagai "Not connected".

Setiap salah satu hal berikut mendarat di `catch` itu dan langsung
menjadi "Not connected" padahal vault utuh:

1. **Timeout 5 detik.** `timeoutMs: 5_000` sementara latensi Railway
   terukur **284–1551 ms** pada endpoint yang sama, dan endpoint status
   harus membaca + decrypt vault. Cool start 1551 ms tinggal sedikit
   ruang sebelum 5 detik habis.
2. **401 dari access_token Supabase yang kedaluwarsa.** `apiFetch`
   mengambil token via `getSession()`; kalau token sudah lewat masa
   berlaku, backend membalas 401, dan `r.json()` dari body error tidak
   punya `connected: true` → `Boolean(undefined)` = `false`.
3. **Blip jaringan atau 5xx.**

Ini persis bentuk laporan user: connect berhasil, card hijau, lalu
beberapa menit kemudian request berikutnya gagal sebentar dan card
berubah jadi "Not connected" — padahal tidak ada yang berubah di sisi
server.

### Yang TIDAK bisa diverifikasi dari sini

Query langsung ke `user_vault` butuh kredensial Supabase yang tidak ada
di lingkungan ini, dan OAuth round-trip butuh browser interaktif. Jadi
"connect → logout → login → masih connected" **belum diuji end-to-end**
dan yang terverifikasi adalah kode yang membuat
gejala itu: jalur error yang salah label.

## Fix yang diterapkan

1. **Badge tiga state.** `st.error` sekarang tampil sebagai "Status
   tidak terbaca" (`data-state="unknown"`), bukan "Not connected".
   Kartu yang benar-benar terputus tetap "Not connected"
   (`data-state="disconnected"`). Test bisa membedakan keduanya lewat
   `data-state`.
2. **Timeout 5s → 15s.** Ruang untuk decrypt vault di Railway.
3. **Retry sekali pada 401.** `supabase.auth.getSession()` dipanggil
   lagi (memicu refresh), lalu request diulang. Token kedaluwarsa
   biasanya tertolong sekali percobaan; yang tidak, baru jadi "unknown".
4. **`!r.ok` sekarang jadi exception.** Sebelumnya response 401/5xx
   tetap diparse dan menghasilkan `connected: false`, yaitu persis
   kebohongan yang diperbaiki.

Tidak ada perubahan di backend OAuth, dan tidak ada baris vault yang
dihapus.

## Screenshot bukti

Belum ada. Butuh browser interaktif untuk menjalankan OAuth consent
dan potret sequence-nya. Yang ada sekarang: regression test di
`tests/oauth-status-truthfulness.spec.ts` yang mengunci perilaku
tiga-state itu dengan sengaja membuat request gagal.
