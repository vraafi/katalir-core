import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
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
