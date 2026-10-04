# Arsitektur Chat Frontend — Audit 5 Oktober 2026

## Ringkasan: koreksi terhadap klaim sebelumnya

Saya sebelumnya melaporkan "frontend tidak punya komponen credential" dan
menyebutnya blocker launch. **Klaim itu salah.** Audit ini membuktikannya:

```
CredentialForm.tsx   240 baris  -> POST /chat/resume   (sudah ada)
OAuthConnections.tsx 305 baris  -> kartu OAuth        (sudah ada)
thread.tsx:244             -> memakai <CredentialForm> (sudah terpasang)
useChat.ts:357             -> cabang requires_credential (sudah ada)
```

Kesalahan saya: saya mencari string `requires_credential` di `*.tsx` dan
tidak menemukannya, lalu menyimpulkan komponennya tidak ada. Padahal
penanganan status itu ada di `useChat.ts` (file `.ts`, bukan `.tsx`) dan
nama komponennya `CredentialForm`, bukan `ApprovalCard`.

Gap yang sebenarnya jauh lebih sempit dan spesifik.

## Alur data

```
ChatApp.tsx (1346 baris)
   |  kirim prompt
   v
features/chat/hooks/useChat.ts  (629 baris)  <- SEMUA parsing respons di sini
   |  POST /chat  -> res.json()
   |  cabang berdasarkan data.status
   v
Query cache TanStack Query: ChatMessage[]
   |
   v
features/thread.tsx (441 baris)  <- render per message.type
   |  "credential_form" -> <CredentialForm .../>  -> POST /chat/resume
   |  "oauth_prompt"    -> <OAuthConnections .../>
   v
components/CredentialForm.tsx (240 baris)

State management: TanStack Query (useQuery + useMutation).
Bukan useState polos - cache ditulis via qc.setQueryData supaya pesan
optimis tidak hilang (lihat komentar FIX Bug2 di useChat.ts:610).
```

### Bentuk `ChatMessage` (useChat.ts:40-78)

```ts
interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  type?: "credential_form" | "oauth_prompt" | "error";
  interrupted?: boolean;
  provider?: string;
  connectUrl?: string;        // hanya oauth_prompt
  displayName?: string;
  icon?: string;
  fields?: CredentialField[]; // hanya credential_form
  resumeToken?: string;
  meta?: ChatMeta;
  clientRequestId?: string;
}
```

`fields` bertipe `CredentialField[]` yang di-import dari
`@/components/CredentialForm` — jadi bentuk field sudah terpusat di satu
tempat. Menambah provider cukup di backend.

## Status backend vs penanganan frontend

| Status backend |_pc_Frontend | Bukti |
|---|---|---|
| `requires_credential` | ✅ `credential_form` | useChat.ts:357 |
| `needs_credential` | ✅ `credential_form` (jalur lama) | useChat.ts:372 |
| `requires_oauth` | ✅ `oauth_prompt` | useChat.ts:381 |
| `needs_oauth` | ✅ `oauth_prompt` (jalur lama) | useChat.ts:381 |
| `requires_approval` | ❌ **TIDAK ADA** | tidak ditemukan |
| `denied` | ❌ **TIDAK ADA** | tidak ditemukan |
| `needs_spec` | ❌ **TIDAK ADA** | tidak ditemukan |

Tiga status terakhir semuanya BARU dan berasal dari commit minggu ini:

- `requires_approval` — dari `tool_policy_gate` (TELEGRAM/SLACK) dan dari
  `intent_alignment` (tool tidak selaras dengan pesan user).
- `denied` — dari policy gate / allowlist argumen.
- `needs_spec` — dari handler `WORKFLOW`, yang sengaja tidak mengarang node.

Sebelum hari ini ketiganya jatuh ke penanganan error generik. Artinya
`requires_approval` yang saya tambahkan kemarin akan tampil sebagai error
bukan sebagai tombol Setujui.

## Rekomendasi implementasi

Satu jalur baru saja, mengikuti pola yang sudah ada (jangan bikin
pola baru):

1. `ChatMessage.type` tambah `"approval_prompt"` (dan `denied`/`needs_spec`
   cukup jadi `type: "error"` dengan `content` yang jelas - tidak perlu
   komponen baru).
2. `useChat.ts`: cabang `data.status === "requires_approval"` yang
   mengembalikan flag `requiresApproval` beserta tool/args/token/reason.
3. `thread.tsx`: render `<ApprovalCard>` saat `type === "approval_prompt"`.
4. `ApprovalCard.tsx` (baru, satu-satunya komponen baru): tombol
   Tolak/Setujui -> `POST /chat/approve`.

Tidak ada perubahan yang diperlukan pada `CredentialForm.tsx`,
`OAuthConnections.tsx`, atau alur `/chat/resume` - semuanya sudah benar.

## Catatan risiko

- `needs_spec` yang jadi `error` adalah pilihan sadar: artinya user perlu
  mengulang prompt dengan lebih spesifik. Menyembunyikannya sebagai
  "sukses" akan menyesatkan.
- `denied` juga sebaiknya ditampilkan jelas (alasan dari backend), bukan
  error kosong, supaya user paham kenapa aksinya ditolak.