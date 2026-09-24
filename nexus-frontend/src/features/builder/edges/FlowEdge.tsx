"use client";

import { BaseEdge, getSmoothStepPath, type EdgeProps } from "@xyflow/react";

/**
 * Edge kanvas (FASE 3).
 *
 * Default: BaseEdge + getSmoothStepPath, 2px, warna `var(--edge-color)`.
 * Saat data mengalir (`edge.animated` true) React Flow menambahkan kelas
 * `animated` pada `.react-flow__edge`, dan CSS di globals.css mengganti warna
 * ke `--edge-animated-color` + dash pattern yang bergerak.
 *
 * Kenapa warna TIDAK diambil lewat prop `style`: dengan cara itu tema harus
 * dioper satu per satu ke setiap edge (dan ke setiap update), sedangkan CSS
 * variable sudah otomatis ikut tema yang aktif. `style` di sini hanya membawa
 * hal yang tidak bisa diatur CSS (markerEnd).
 */
export function FlowEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
  selected,
}: EdgeProps) {
  const [path] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    borderRadius: 10,
  });

  return (
    <BaseEdge
      id={id}
      path={path}
      markerEnd={markerEnd}
      className={"k-edge" + (selected ? " k-edge--selected" : "")}
      style={{ strokeWidth: 2 }}
    />
  );
}
