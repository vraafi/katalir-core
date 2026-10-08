# Fitur #4 — Sub-Workflow Execution

**Tanggal:** 8 Okt 2026 · **Mode:** Autonomous research + hard test

---

## Research

| Sumber | Pendekatan | Verdict |
|---|---|---|
| **didi/tg-flow** (DeepWiki) | field `ref_workflow_id`; kedalaman **tak terbatas** | ✅ pola dipakai, cacat ditambal |
| onsager-ai ADR-0011 | sub-workflow untuk rekursi VSM | ✅ konsep mendukung |
| Python recursion docs | batas rekursi default 1000 | ⚠️ tidak jadi masalah (kita rekursi lewat DB) |

**Pilihan:** pola `ref_workflow_id` dengan **batas kedalaman 3 level +
deteksi siklus** — bukan library, karena ini semantik orkestrasi, bukan
algoritma yang perlu dependensi.

**Dasar batas 3 level:** rekomendasi praktik terbaik dari sumber referensi:
> "Recommended Practice: **Keep nesting depth ≤3 levels** for maintainability"
> — juga menyebut "Debuggability: Deep nesting (>5 levels) …", "Memory Usage"

### ⚠️ CACAT REFERENSI YANG KITA PERBAIKI
tg-flow menyatakan **"Unlimited Depth: Workflows can be nested to arbitrary
depth"** dan **tidak punya deteksi siklus**. Artinya A→B→A akan berputar
tanpa henti sampai kehabisan resource. Ini kita tolak eksplisit.

---

## Implementasi

- **`subworkflow.py`** — `check_allowed` (kedalaman+siklus), `invoke_subworkflow`,
  `list_invocations`, `call_chain`, `execution_depth`.
- **`migrations/2026-10-08-subworkflow.sql`** — `executions.depth`,
  `workflow_call_chain`, `subworkflow_invocations`, RPC
  `check_subworkflow_allowed`, RLS.

### Aturan keamanan
1. **Anak WAJIB milik user yang sama** dengan induk (cegah lintas-tenant).
2. Kedalaman maksimum **3**.
3. **Siklus ditolak** (ditelusuri lewat rantai leluhur, guard 50 iterasi).
4. **Idempoten per `(parent_execution, step_id)`** — replay induk tidak
   menjalankan anak dua kali.

---

## Hard Test — 11/11 PASS (raw evidence)

| # | Skenario | Status | Bukti |
|---|---|---|---|
| 1 | pemanggilan dasar | PASS | `ok=True output={'balik': 2} depth=1` |
| 2 | eksekusi anak dibuat & terhubung | PASS | `parent terhubung, depth=1, status=success` |
| 3 | rantai 3 level | PASS | `induk(0) -> anak(1) -> cucu(2)` |
| 4 | **kedalaman ke-4 ditolak** | PASS | `level diizinkan=depth 3; depth 4 ditolak` |
| 5 | **SIKLUS A→B→A ditolak** | PASS | `siklus terdeteksi: ... ada di rantai leluhur` |
| 6 | idempoten per step | PASS | `2x invoke -> runner dipanggil 1x` |
| 7 | workflow user lain ditolak | PASS | `reason=forbidden` |
| 8 | anak gagal dicatat | PASS | `anak.status=failed`, invokasi failed |
| 9 | rantai tercatat + isolasi | PASS | `rantai=1 baris; user asing -> []` |
| 10 | isolasi invokasi | PASS | `user asing -> []` |
| 11 | performa | PASS | `10 sub-workflow = 9.61s (961 ms/invoke)` |

```
11 passed, 1 warning in 45.40s
```

### 🐞 Temuan tes (bukan bug kode)
Versi pertama tes #4 memakai `wf_child` **dua kali dalam satu rantai**,
sehingga pemeriksaan **siklus** lebih dulu menolak dan batas **kedalaman**
tidak pernah benar-benar teruji. **Kode benar; tesnya yang keliru.**
Diperbaiki dengan workflow berbeda tiap level — sekarang terbukti:
level 3 diizinkan, level 4 ditolak dengan alasan "kedalaman maksimum 3".

---

## Blocker
Tidak ada. (Push git menunggu login GitHub — `docs/PUSH_BLOCKER.md`.)

## Next
Fitur #5 — Parallel Fan-Out / Fan-In.
