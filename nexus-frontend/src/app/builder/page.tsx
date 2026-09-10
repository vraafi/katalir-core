"use client";

import {
  ReactFlowProvider,
} from "@xyflow/react";
import { QueryProvider } from "@/features/builder/provider";
import { BuilderInner } from "@/features/builder/builder-inner";

export default function Builder() {
  return (
    <QueryProvider>
      <ReactFlowProvider>
        <BuilderInner />
      </ReactFlowProvider>
    </QueryProvider>
  );
}
