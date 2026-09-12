"use client";

import { motion, type Variants } from "motion/react";

/**
 * Motion primitives (Phase 4a) — import uit "motion/react" (nieuw, niet
 * "framer-motion"). Alle animaties animeren transform/opacity (performant)
 * en respecteren reduced-motion via MotionConfig reducedMotion="user" in layout.
 */

/** FadeIn — gedeeld voor server/client elementen. */
export function FadeIn({
  children,
  className,
  delay = 0,
  y = 8,
}: {
  children: React.ReactNode;
  className?: string;
  delay?: number;
  y?: number;
}) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.32, 0.72, 0, 1], delay: delay ?? 0 }}
      style={{ willChange: "opacity, transform" }}
    >
      {children}
    </motion.div>
  );
}

const staggerContainer: Variants = {
  hidden: {},
  show: {
    transition: { staggerChildren: 0.05 }, // stagger 50ms
  },
};

const staggerItem: Variants = {
  hidden: { opacity: 0, y: 8 },
  show: { opacity: 1, y: 0, transition: { duration: 0.3 } },
};

/** StaggerList — omhult items die met 50ms stagger binnenkomen. */
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

/** StaggerItem — individueel item binnen een StaggerList. */
export function StaggerItem({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <motion.div className={className} variants={staggerItem} style={{ willChange: "opacity, transform" }}>
      {children}
    </motion.div>
  );
}

/** Spring-in config voor panels/toast (stiffness 400, damping 30). */
export const springPanel = {
  type: "spring" as const,
  stiffness: 400,
  damping: 30,
};