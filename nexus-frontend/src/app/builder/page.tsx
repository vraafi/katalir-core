"use client";

import "@xyflow/react/dist/base.css";
import "@xyflow/react/dist/style.css";

import { Suspense } from "react";
import {
  ReactFlowProvider,
} from "@xyflow/react";
import { QueryProvider } from "@/features/builder/provider";
import { BuilderInner } from "@/features/builder/builder-inner";

export default function Builder() {
  return (
    <QueryProvider>
      <ReactFlowProvider>
        {/* Suspense boundary DI IN de page component — vereist door
            Next 15 static-export voor useSearchParams (nuqs). Zonder dit
            faalt prerender met "missing-suspense-with-csr-bailout". */}
        <Suspense fallback={null}>
          <BuilderInner />
        </Suspense>
      </ReactFlowProvider>
    </QueryProvider>
  );
}
