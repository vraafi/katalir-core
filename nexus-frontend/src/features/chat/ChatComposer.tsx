"use client";

/**
 * ChatComposer — kolom input chat gaya DeepSeek (2026).
 *
 * Kenapa komponen terpisah: `ChatApp.tsx` sudah 1400+ baris. Composer punya
 * tiga perilaku yang harus diuji sendiri (auto-resize, Enter/Shift+Enter,
 * tata letak responsif), jadi memisahkannya membuat tiap perilaku bisa
 * diverifikasi tanpa membaca seluruh ChatApp.
 *
 * Keputusan desain + alasannya:
 *
 * 1. `textarea`, bukan `input`. Input satu baris tidak bisa tumbuh; DeepSeek
 *    dan seluruh chat AI 2026 memakai textarea yang tumbuh sampai batas lalu
 *    menggulir sendiri. Tinggi dikendalikan `scrollHeight` (JS), bukan
 *    `field-sizing: content`, karena dukungan `field-sizing` belum merata.
 *
 * 2. Batas tumbuh 200 px (~10 baris pada 16px/1.5). Di atas itu area pesan
 *    terdorong keluar layar di ponsel.
 *
 * 3. `font-size: 16px` (di globals.css). Di bawah 16px iOS Safari MEMPERBESAR
 *    halaman saat field difokus, dan seluruh layout ikut bergeser.
 *
 * 4. Tata letak dua mode memakai GRID dengan penempatan eksplisit, bukan
 *    `flex flex-wrap` + `basis-full`:
 *      mobile  → textarea satu baris penuh; model di kiri, kirim di kanan,
 *                pada baris berikutnya (pola LifeOS/vm0).
 *      desktop → model, textarea, tombol kirim dalam SATU baris.
 *    Composer tetap di dalam aliran dokumen sehingga browser ikut mendorongnya
 *    ke atas keyboard — sesuatu yang TIDAK terjadi pada elemen `fixed`.
 *    Alasan grid (dan bukan flex-wrap) ada di komentar `className` textarea:
 *    flex-wrap membuat textarea selalu pindah baris di desktop.
 *
 * 5. `autoFocus` hanya di desktop. Di ponsel, fokus otomatis memunculkan
 *    keyboard tepat saat halaman dibuka dan menyembunyikan separuh percakapan.
 *
 * 6. `enterKeyHint="send"` supaya papan ketik ponsel menampilkan tombol
 *    "Kirim", bukan "Enter".
 */
import { useCallback, useEffect, useRef, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { Send, Square } from "lucide-react";
import { Button } from "@/components/ui/button";

/** Tinggi maksimum area teks (px). ~10 baris @16px/1.5. */
export const COMPOSER_MAX_PX = 200;
/** Tinggi minimum saat istirahat: 1 baris di mobile. */
export const COMPOSER_MIN_MOBILE_PX = 24;
/** Tinggi minimum saat istirahat: 3 baris di desktop. */
export const COMPOSER_MIN_DESKTOP_PX = 72;

export interface ChatComposerProps {
  value: string;
  onChange: (v: string) => void;
  /** Dipanggil saat Enter (tanpa Shift) atau tombol kirim ditekan. */
  onSubmit: () => void;
  onStop?: () => void;
  /** True saat AI sedang menjawab DAN composer kosong → tombol berubah jadi Stop. */
  showStop: boolean;
  placeholder: string;
  sendLabel: string;
  stopLabel: string;
  messageLabel: string;
  title?: string;
  disabled?: boolean;
  /** Slot kiri (pemilih model). Dirender sebelum textarea di desktop. */
  modelSlot?: ReactNode;
  /** data-testid textarea. Default dipertahankan agar spec lama tetap jalan. */
  inputTestId?: string;
  /** data-testid tombol kirim. */
  sendTestId?: string;
}

export function ChatComposer({
  value,
  onChange,
  onSubmit,
  onStop,
  showStop,
  placeholder,
  sendLabel,
  stopLabel,
  messageLabel,
  title,
  disabled = false,
  modelSlot,
  inputTestId = "composer-input",
  sendTestId = "composer-send",
}: ChatComposerProps) {
  const ref = useRef<HTMLTextAreaElement>(null);

  /** Samakan tinggi kotak dengan isinya, dibatasi COMPOSER_MAX_PX. */
  const resize = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    // `height: auto` dulu supaya scrollHeight mengukur isi sebenarnya
    // (tanpa ini, kotak hanya bisa tumbuh dan tidak pernah menyusut).
    el.style.height = "auto";
    const isi = el.scrollHeight;
    const tinggi = Math.min(isi, COMPOSER_MAX_PX);
    el.style.height = `${tinggi}px`;
    el.style.overflowY = isi > COMPOSER_MAX_PX ? "auto" : "hidden";
  }, []);

  // Nilai bisa berubah dari luar (kirim → dikosongkan, pilih saran → terisi).
  useEffect(() => {
    resize();
  }, [value, resize]);

  // Fokus otomatis HANYA di desktop (lihat catatan #5 di header).
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!window.matchMedia("(min-width: 768px)").matches) return;
    ref.current?.focus();
  }, []);

  const kirim = () => {
    if (showStop) {
      onStop?.();
      return;
    }
    if (value.trim()) onSubmit();
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Escape menghentikan jawaban yang sedang berjalan (perilaku lama).
    if (e.key === "Escape" && showStop) {
      e.preventDefault();
      onStop?.();
      return;
    }
    // Enter = kirim, Shift+Enter = baris baru.
    // `isComposing` penting: saat IME menyusun karakter (mis. papan ketik
    // Jepang/Cina), Enter memilih kandidat — bukan mengirim.
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      kirim();
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    kirim();
  };

  return (
    <form
      onSubmit={handleSubmit}
      data-testid="chat-composer"
      className="k-chat-composer grid grid-cols-[auto_1fr] items-end gap-x-2 gap-y-1.5 rounded-3xl border border-border bg-surface px-3 py-2.5 shadow-lg transition-[box-shadow,border-color] duration-200 focus-within:border-accent/50 focus-within:shadow-xl focus-within:ring-2 focus-within:ring-accent/25 dark:bg-zinc-800 md:grid-cols-[auto_1fr_auto]"
    >
      <textarea
        ref={ref}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        title={title}
        aria-label={messageLabel}
        rows={1}
        disabled={disabled}
        enterKeyHint="send"
        spellCheck={false}
        /* HOOK STABIL UNTUK E2E: `aria-label` sengaja tetap diterjemahkan
           (a11y), jadi tes TIDAK boleh memakainya sebagai selector —
           data-testid tidak ikut bahasa. */
        data-testid={inputTestId}
        /* TATA LETAK DUA MODE — memakai GRID, bukan flex-wrap.
           Kenapa bukan `flex flex-wrap` + `basis-full`: pembungkusan flex
           diputuskan dari hypothetical main size, dan `width: 100%` pada
           textarea membuat ukuran itu = lebar penuh wadah, sehingga textarea
           SELALU pindah baris sendiri walau `md:flex-1` sudah dipasang
           (`basis-auto` menang atas basis dari shorthand `flex-1`). Terukur
           di desktop: composer jadi 3 baris bertumpuk (h=174px) padahal
           seharusnya satu baris. Grid menempatkan tiap anak secara eksplisit
           sehingga tidak ada ambiguitas sama sekali.

             mobile  (2 kolom): textarea = baris 1 span 2 kolom;
                                 model = kiri bawah, kirim = kanan bawah.
             desktop (3 kolom): model | textarea | kirim dalam SATU baris. */
        className="col-span-2 col-start-1 row-start-1 min-h-[24px] max-h-[200px] w-full resize-none border-0 bg-transparent p-0 text-fg outline-none placeholder:text-fg-subtle disabled:opacity-60 md:col-span-1 md:col-start-2 md:row-start-1 md:min-h-[72px]"
      />
      {modelSlot ? (
        <div data-testid="composer-model" className="col-start-1 row-start-2 shrink-0 md:row-start-1">{modelSlot}</div>
      ) : null}
      <Button
        type={showStop ? "button" : "submit"}
        size="icon"
        aria-label={showStop ? stopLabel : sendLabel}
        onClick={showStop ? onStop : undefined}
        disabled={showStop ? false : !value.trim()}
        data-testid={sendTestId}
        className="col-start-2 row-start-2 justify-self-end md:col-start-3 md:row-start-1 md:justify-self-end"
      >
        {showStop ? <Square size={16} strokeWidth={1.75} /> : <Send size={16} strokeWidth={1.75} />}
      </Button>
    </form>
  );
}

export default ChatComposer;
