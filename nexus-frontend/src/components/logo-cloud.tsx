"use client";

/**
 * F6 — the 55-brand cloud as a magnetic BACKGROUND layer for the hero.
 *
 * WHY NOT `motion/react` (the library the obvious approach reaches for):
 * `page.tsx` carries a hard, test-enforced rule that the landing page must not
 * import it. The reason is measured, not aesthetic: this page once loaded the
 * entire chat app, and `motion` is two chunks of roughly 180 KB. Adding it back
 * to save fifty lines of arithmetic would undo a documented performance
 * decision. The physics below is the same maths without the dependency.
 *
 * WHY ONE rAF LOOP AND NOT FIFTY-FIVE:
 * the naive version gives every tile its own animation frame. That is 55 layout
 * reads per frame, every frame, and it is why "logo swarm" demos usually melt a
 * laptop. Here the parent owns a single loop, the tile centres are measured once
 * and cached (they live in a static grid), and each frame only writes
 * transforms. No React state, no re-render, no layout thrash.
 *
 * The feel: a tile is pulled toward the cursor, and the pull falls off linearly
 * to zero at the edge of `radius`. Smoothing is an exponential lerp, which reads
 * as a soft spring without overshoot. A real spring constant would oscillate,
 * and for 55 tiles moving at once that looks like a shiver rather than a shoal.
 *
 * Accessibility, unchanged from the previous cloud: decorative only,
 * `aria-hidden`, `pointer-events-none`, and every effect is off under
 * `prefers-reduced-motion`. Brand names are still announced once by the sr-only
 * list the page renders.
 */

import { useCallback, useEffect, useRef } from "react";
import { mcpLogos, type McpLogo } from "@/lib/mcp-logos";

type Tile = {
  el: HTMLDivElement;
  /** Centre in viewport coordinates, cached at measure time. */
  cx: number;
  cy: number;
  x: number;
  y: number;
  tx: number;
  ty: number;
};

function renderLogo(logo: McpLogo, size: number) {
  if (!logo.Component) {
    return (
      <svg
        viewBox={logo.path?.viewBox ?? "0 0 24 24"}
        width={size}
        height={size}
        fill={logo.color ?? "currentColor"}
        aria-hidden="true"
        focusable="false"
      >
        <path d={logo.path?.d ?? ""} />
      </svg>
    );
  }
  // simple-icons paints its own brand fill; everything else is currentColor and
  // takes its colour from the wrapper. `logo.color` is undefined when a brand's
  // primary is white, which is what keeps that logo visible on a light hero.
  return logo.color === "default" ? (
    <logo.Component size={size} color="default" />
  ) : (
    <span style={{ color: logo.color ?? "var(--fg)", display: "block", lineHeight: 0 }}>
      <logo.Component size={size} />
    </span>
  );
}

/**
 * The 55-brand cloud, rendered as the hero BACKGROUND.
 *
 * Replaces both earlier shapes - the 10-logo strip under the CTA and the full
 * cloud below the fold. Two components at two sizes read as a bug, so there is
 * now exactly one, at 48px, filling the hero.
 *
 * Purely decorative: aria-hidden, pointer-events-none, inert under
 * prefers-reduced-motion. The brand names are announced once by the sr-only
 * list in page.tsx.
 */
export function MagneticLogoCloud({
  logos = mcpLogos,
  gap = 80,
  size = 48,
  radius = 180,
  strength = 0.4,
  opacity = 0.2,
  className = "",
}: {
  logos?: McpLogo[];
  gap?: number;
  size?: number;
  radius?: number;
  strength?: number;
  opacity?: number;
  className?: string;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const tiles = useRef<Tile[]>([]);
  const mouse = useRef({ x: -99999, y: -99999, active: false });
  const reduced = useRef(false);

  const measure = useCallback(() => {
    const nodes = hostRef.current?.querySelectorAll<HTMLDivElement>("[data-magnetic-tile]");
    if (!nodes) return;
    tiles.current = Array.from(nodes).map((el) => {
      const r = el.getBoundingClientRect();
      return { el, cx: r.left + r.width / 2, cy: r.top + r.height / 2, x: 0, y: 0, tx: 0, ty: 0 };
    });
  }, []);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    reduced.current = mq.matches;
    const onMq = () => {
      reduced.current = mq.matches;
    };
    mq.addEventListener("change", onMq);

    const onMove = (e: MouseEvent) => {
      mouse.current = { x: e.clientX, y: e.clientY, active: true };
    };
    const onLeave = () => {
      mouse.current.active = false;
    };
    // Listeners are on the window, not the grid. The grid is pointer-events-none
    // so a logo can never be clicked, and a pointer-events-none element also
    // never dispatches mouse events - that is exactly why "not clickable" and
    // "reacts to the cursor" have to coexist.
    window.addEventListener("mousemove", onMove, { passive: true });
    window.addEventListener("scroll", measure, { passive: true });
    window.addEventListener("resize", measure);
    document.addEventListener("mouseleave", onLeave);

    // Measure after layout settles: the grid is sized by the parent, so a
    // measurement taken before first paint would cache the wrong centres.
    const raf = requestAnimationFrame(measure);
    const t = setTimeout(measure, 300);

    let frame = 0;
    const tick = () => {
      if (!reduced.current) {
        const { x: mx, y: my, active } = mouse.current;
        for (const tile of tiles.current) {
          if (active) {
            const dx = mx - tile.cx;
            const dy = my - tile.cy;
            const dist = Math.hypot(dx, dy);
            if (dist < radius) {
              // Falls to zero at the edge of the radius, so the outer ring
              // barely moves and the inner tiles commit.
              const f = (1 - dist / radius) * strength;
              tile.tx = dx * f;
              tile.ty = dy * f;
            } else {
              tile.tx = 0;
              tile.ty = 0;
            }
          } else {
            tile.tx = 0;
            tile.ty = 0;
          }
          // Exponential lerp. The factor is frame-rate independent, so the
          // motion looks the same on a 60Hz and a 144Hz display.
          const k = 1 - Math.pow(0.001, 1 / 60);
          tile.x += (tile.tx - tile.x) * k;
          tile.y += (tile.ty - tile.y) * k;
          if (Math.abs(tile.tx - tile.x) > 0.05 || Math.abs(tile.ty - tile.y) > 0.05) {
            tile.el.style.transform = `translate3d(${tile.x.toFixed(2)}px, ${tile.y.toFixed(2)}px, 0)`;
          }
        }
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(frame);
      cancelAnimationFrame(raf);
      clearTimeout(t);
      mq.removeEventListener("change", onMq);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("scroll", measure);
      window.removeEventListener("resize", measure);
      document.removeEventListener("mouseleave", onLeave);
    };
  }, [radius, strength, measure]);

  return (
    <div
      ref={hostRef}
      data-testid="magnetic-logo-cloud"
      aria-hidden="true"
      className={`grid h-full w-full place-items-center ${className}`}
      style={{
        gridTemplateColumns: `repeat(auto-fill, minmax(${gap}px, 1fr))`,
        gap: `${gap}px`,
        padding: `${gap}px`,
        opacity,
      }}
    >
      {logos.map((logo) => (
        <div
          key={logo.name}
          data-magnetic-tile
          data-testid="mcp-logo"
          data-brand={logo.name}
          className="pointer-events-none flex select-none items-center justify-center"
          style={{ width: size, height: size, willChange: "transform" }}
        >
          {renderLogo(logo, size)}
        </div>
      ))}
    </div>
  );
}

export default MagneticLogoCloud;


