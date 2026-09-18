import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { ThemeProvider } from "next-themes";
import { Toaster } from "sonner";
import { MotionConfig } from "motion/react";
import { NuqsAdapter } from "nuqs/adapters/next/app";
import { HydrationMonitor } from "@/components/HydrationMonitor";
import "./globals.css";

const sans = Inter({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: "Katalir — SaaS AI",
  description: "Katalir: Autonomous AI Agent untuk bisnis Anda.",
  icons: {
    icon: "/favicon.ico",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="id" suppressHydrationWarning>
      <body className={`${sans.variable} ${mono.variable} font-sans bg-bg text-fg antialiased`}>
        <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[100] focus:rounded-sm focus:bg-surface focus:px-4 focus:py-2 focus:shadow-md">
          Lompat ke konten
        </a>
        <NuqsAdapter>
          <MotionConfig reducedMotion="user">
            <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
              <HydrationMonitor />
              {children}
              <Toaster position="top-center" richColors closeButton />
            </ThemeProvider>
          </MotionConfig>
        </NuqsAdapter>
      </body>
    </html>
  );
}
