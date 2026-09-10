"use client";

import {
  ReactFlowProvider,
} from "@xyflow/react";
import { BuilderInner } from "@/features/builder/builder-inner";

export default function Builder() {
  return (
    <ReactFlowProvider>
      <BuilderInner />
    </ReactFlowProvider>
  );
}
