"use client";

import "@xyflow/react/dist/base.css";
import "@xyflow/react/dist/style.css";

import { Suspense } from "react";
import {
  ReactFlowProvider,
} from "@xyflow/react";
import { QueryProvider } from "@/features/builder/provider";
import { AuthProvider } from "@/context/auth";
import { I18nProvider } from "@/i18n/context";
import { BuilderInner } from "@/features/builder/builder-inner";

export default function Builder() {
  return (
    <Suspense fallback={null}>
      {/* Suspense DI DALAM page: useSearchParams (nuqs) butuh CSR-bailout
          saat prerender statis ("missing-suspense-with-csr-bailout"). */}
      {/* AuthProvider WAJIB di sini: BuilderInner me-render <Shell/>
          yang memanggil useAuth() (auth.tsx:124). Tanpa provider ini
          /builder crash "useAuth must be used within AuthProvider".
          Urutan provider = pola page.tsx root + SimplePage. */}
      <AuthProvider>
        <QueryProvider>
          <I18nProvider>
            <ReactFlowProvider>
              <BuilderInner />
            </ReactFlowProvider>
          </I18nProvider>
        </QueryProvider>
      </AuthProvider>
    </Suspense>
  );
}
