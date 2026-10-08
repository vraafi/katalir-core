import type { Metadata, Viewport } from "next";
import { Suspense } from "react";
import { Inter, JetBrains_Mono } from "next/font/google";
import { NavigationTracker } from "@/components/navigation-tracker";
import { ThemeProvider } from "next-themes";
import { Toaster } from "sonner";
import { MotionConfig } from "motion/react";
import { NuqsAdapter } from "nuqs/adapters/next/app";
import { HydrationMonitor } from "@/components/HydrationMonitor";
import { ServiceWorkerRegistrar } from "@/components/pwa/ServiceWorkerRegistrar";
import "./globals.css";

const sans = Inter({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
// FASE 6 lanjutan (perf): JetBrains Mono HANYA dipakai untuk potongan mono
// (model id, metadata), bukan untuk teks LCP. `preload: false` mengeluarkan
// font ini dari jalur kritis sehingga unduhan font tak lagi menahan LCP.
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap", preload: false });

export const metadata: Metadata = {
  title: { default: "Katalir — SaaS AI", template: "%s — Katalir" },
  description: "Katalir: Autonomous AI Agent untuk bisnis Anda.",
  metadataBase: new URL("https://katalir.de5.net"),
  applicationName: "Katalir",
  openGraph: {
    type: "website",
    url: "https://katalir.de5.net",
    title: "Katalir — SaaS AI",
    description: "Bangun AI agent dari satu kalimat.",
    siteName: "Katalir",
    images: ["/logo-v2.png"],
  },
  twitter: { card: "summary", title: "Katalir — SaaS AI", description: "Bangun AI agent dari satu kalimat.", images: ["/logo-v2.png"] },
  // FASE 6 (PWA): manifest + ikon 192/512. Ikon PNG dibuat dari `src/app/icon.svg`
  // dengan headless Chrome (tanpa menambah dependensi image tooling).
  manifest: "/manifest.json",
  appleWebApp: { capable: true, title: "Katalir", statusBarStyle: "default" },
  icons: {
    icon: [
      { url: "/logo-v2.png", type: "image/png", sizes: "192x192" },
    ],
    shortcut: "/favicon-v2.ico",
    apple: "/logo-v2.png",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // `viewport-fit=cover` — layar berponi (iPhone notch/Dynamic Island, Android
  // gesture bar) boleh memakai seluruh tinggi; padding aman ditangani
  // `env(safe-area-inset-*)` di globals.css. Tanpa ini Safari menyisakan
  // bilah putih dan composer tidak menempel di dasar layar.
  viewportFit: "cover",
  // `interactive-widget=resizes-content` — saat keyboard muncul, browser
  // MENGECILKAN layout viewport (bukan hanya visual viewport). Inilah yang
  // membuat `100dvh` ikut mengecil sehingga baris composer terdorong ke ATAS
  // keyboard. Tanpa ini (default `resizes-visual`) layout tetap setinggi layar
  // penuh dan composer tertutup keyboard.
  // Chrome/Edge/Samsung 108+, Android Chrome. Browser lain mengabaikan nilai
  // ini dan tetap memakai perilaku default yang sudah aman (lihat globals.css).
  interactiveWidget: "resizes-content",
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#09090b" },
    { media: "(prefers-color-scheme: light)", color: "#4F46E5" },
  ],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="id" suppressHydrationWarning>
      <body className={`${sans.variable} ${mono.variable} font-sans antialiased`}>
        <NuqsAdapter>
          <MotionConfig reducedMotion="user">
            <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
              <HydrationMonitor />
              {/* Penanda navigasi internal untuk tombol Back. `Suspense`
                  wajib karena komponen ini memakai `useSearchParams`; pada
                  `output: "export"` tanpa boundary Next.js menolak build.
                  Fallback null karena komponen ini tidak merender apa pun. */}
              <Suspense fallback={null}>
                <NavigationTracker />
              </Suspense>
              {/* FASE 6 (PWA): no-op di dev, mendaftarkan /sw.js hanya di produksi. */}
              <ServiceWorkerRegistrar />
              {children}
              <Toaster position="top-center" richColors closeButton />
            </ThemeProvider>
          </MotionConfig>
        </NuqsAdapter>
      </body>
    </html>
  );
}
