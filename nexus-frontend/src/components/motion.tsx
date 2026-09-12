"use client";

import { motion, useReducedMotion, type Variants } from "motion/react";

/**
 * Motion primitives (Phase 4a fix) — import uit "motion/react" (nieuw, niet
 * "framer-motion"). Alle animaties animeren transform/opacity (performant).
 * A11y: useReducedMotion() per-component — bij OS reduce-motion, transform
 * wordt gedeactiveerd (y→0) maar opacity (fade) blijft behouden (WCAG 2.3.3).
 * MotionConfig reducedMotion="user" blijft ook op layout-niveau staan.
 */

/** FadeIn — gedeeld voor server/client elementen. */
export function FadeIn({
  children,
  className,
  delay = 0,
  y = 16,
}: {
  children: React.ReactNode;
  className?: string;
  delay?: number;
  y?: number;
}) {
  const shouldReduceMotion = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: shouldReduceMotion ? 0 : y }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: [0.32, 0.72, 0, 1], delay: delay ?? 0 }}
      style={{ willChange: "opacity, transform" }}
    >
      {children}
    </motion.div>
  );
}

const staggerContainer: Variants = {
  hidden: {},
  show: {
    transition: { staggerChildren: 0.08 }, // stagger 80ms
  },
};

/** item-variant builder (respect reducermotion: y=0 bij reduce). */
function staggerItem(shouldReduceMotion: boolean | null): Variants {
  return {
    hidden: { opacity: 0, y: shouldReduceMotion ? 0 : 16 },
    show: { opacity: 1, y: 0, transition: { duration: 0.4 } },
  };
}

/** StaggerList — omhult items die met 80ms stagger binnenkomen. */
export function StaggerList({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <motion.div
      className={className}
      variants={staggerContainer}
      initial="hidden"
      animate="show"
      style={{ willChange: "opacity, transform" }}
    >
      {children}
    </motion.div>
  );
}

/** StaggerItem — individueel item binnen een StaggerList (y16, fade). */
export function StaggerItem({ children, className }: { children: React.ReactNode; className?: string }) {
  const shouldReduceMotion = useReducedMotion();
  return (
    <motion.div
      className={className}
      variants={staggerItem(shouldReduceMotion)}
      style={{ willChange: "opacity, transform" }}
    >
      {children}
    </motion.div>
  );
}

/** Spring-in config voor panels/toast — Default preset (300/25), niet micro. */
export const springPanel = {
  type: "spring" as const,
  stiffness: 300,
  damping: 25,
};