import Link from "next/link";

const TIERS = [
  {
    id: "free",
    name: "Free",
    price: "Rp 0",
    period: "selamanya",
    cta: "Mulai gratis",
    ctaHref: "/",
    features: ["Gemma 4 — 100 request / hari", "Reset setiap 00:00 WIB", "Tanpa kartu kredit"],
  },
  {
    id: "plus",
    name: "Plus",
    price: "Rp 5.000.000",
    period: "/ tahun",
    cta: "Upgrade ke Plus",
    ctaHref: "/",
    popular: true,
    features: [
      "Gemma 4 — 500 request / hari",
      "DeepSeek V4 Flash — 100 request / hari",
      "Total 600 request / hari",
      "Reset setiap 00:00 WIB",
    ],
  },
];

/**
 * Halaman pricing untuk LAUNCH: hanya 2 tier (Free + Plus).
 *
 * Pro/Ultra DISEMBUNYIKAN sementara (bukan dihapus): tidak dirender sama
 * sekali di sini, tetapi id, harga (Pro Rp 20jt/tahun, Ultra Rp 50jt/tahun),
 * dan batas kuotanya tetap ada di backend (`database.QUOTA_LIMITS` +
 * `SELLABLE_MODELS`) dan siap dinyalakan lagi tanpa migrasi. User lama
 * pro/ultra diperlakukan setara Plus (`database.effective_tier`).
 */
export default function PricingPage() {
  return (
    <main id="main-content" tabIndex={-1} className="mx-auto flex min-h-screen max-w-3xl flex-col items-center px-6 py-16 outline-none">
      <h1 className="text-3xl font-bold">Katalir</h1>
      <p className="mt-2 text-[14px] text-fg-subtle">
        Satu harga per tier per tahun. Kuota dihitung per <b>request</b> dan direset 00:00 WIB.
      </p>
      <div className="mt-8 grid w-full gap-4 sm:grid-cols-2">
        {TIERS.map((t) => (
          <section
            key={t.id}
            aria-label={`Paket ${t.name}`}
            className={
              "flex flex-col gap-3 rounded-xl border px-5 py-6 " +
              ("popular" in t && t.popular ? "border-accent" : "border-border")
            }
          >
            <h2 className="text-xl font-semibold">{t.name}</h2>
            <p className="text-2xl font-bold">
              {t.price} <span className="text-[13px] font-normal text-fg-subtle">{t.period}</span>
            </p>
            <ul className="flex flex-col gap-1.5 text-[13px]">
              {t.features.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
            <Link
              href={t.ctaHref}
              className="mt-2 rounded-lg bg-accent px-4 py-2 text-center text-[13px] font-semibold text-white"
            >
              {t.cta}
            </Link>
          </section>
        ))}
      </div>
      <p className="mt-6 text-[12px] text-fg-subtle">
        Tier Pro &amp; Ultra tidak ditawarkan saat peluncuran.
      </p>
    </main>
  );
}
