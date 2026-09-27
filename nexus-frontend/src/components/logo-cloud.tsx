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
import { denseLogos, type DenseLogo } from "@/lib/dense-logos";

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

/** Uniform square cells.
 *
 *  The brief asked for a uniform height rather than a uniform width, because
 *  forcing every logo to the same width distorts the wordmarks: "GitHub" and a
 *  square app icon cannot share a width without one of them stretching. So the
 *  cell is square (`gridAutoRows` = column track) and the glyph keeps its own
 *  aspect ratio inside it, centred. Equal spacing in all four directions is a
 *  property of a square cell with one gap value, not of equal glyph widths.
 */
function renderDense(logo: DenseLogo, size: number) {
  if (logo.brand) {
    // simple-icons paints its own brand fill.
    return <logo.Component size={size} color="default" />;
  }
  // lobehub Mono is currentColor. `logo.color` is the pack's own COLOR_PRIMARY
  // where that value is visible on the light hero; without it the glyph
  // inherits the theme foreground, which is how 73 brands shipped grey.
  return <logo.Component size={size} color={logo.color} />;
}

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
  dense = true,
  gap = 24,
  size = 24,
  cell = 40,
  mobileLimit = 40,
  radius = 250,
  strength = 1.5,
  opacity = 1,
  className = "",
}: {
  logos?: McpLogo[];
  /** Use the 218-brand generated field instead of the 55 curated ones. */
  dense?: boolean;
  gap?: number;
  size?: number;
  /** Square cell edge. Equals the column min so rows and columns match. */
  cell?: number;
  /** How many tiles stay visible below the `sm` breakpoint. */
  mobileLimit?: number;
  radius?: number;
  strength?: number;
  opacity?: number;
  className?: string;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const tiles = useRef<Tile[]>([]);
  const mouse = useRef({ x: -99999, y: -99999, active: false });
  const reduced = useRef(false);

  // The dense set already contains the curated brands, so `dense` replaces the
  // list rather than appending to it; merging would double up GitHub, Stripe,
  // Vercel and friends in adjacent cells.
  const items = dense ? (denseLogos as unknown as (McpLogo | DenseLogo)[]) : logos;

  // The collision-free displacement bound, MEASURED rather than assumed.
  //
  // Reasoning: two adjacent cards can only touch once their combined travel
  // consumes the free space between them, so each may travel at most half of
  // it. The free space is NOT the `gap` prop. The grid is
  // `repeat(auto-fill, minmax(cell, 1fr))`, so columns stretch to fill the
  // hero: measured in the browser the real pitch is 74.5px across and 72px
  // down, giving 26.5px and 24px of clearance, not a clean 24. Assuming
  // `gap` under-counted the horizontal case, and the brief's suggested
  // `cell * 0.4` (~19px) would have left every neighbouring pair overlapping
  // by 12-14px -- Task C's new border makes that far more obvious than it was
  // against a bare glyph.
  //
  // It is a ref, not a const, because it depends on the laid-out grid: it is
  // recomputed from real tile boxes on every measure (resize/scroll/layout),
  // and defaults conservatively until the first one lands.
  const maxDisp = useRef(10);
  // 0.9 leaves a visible hairline of clearance at rest rather than letting the
  // cards exactly touch, which is what a strict gap/2 bound produces.
  const SAFETY = 0.9;

  const measure = useCallback(() => {
    const nodes = hostRef.current?.querySelectorAll<HTMLDivElement>("[data-magnetic-tile]");
    if (!nodes) return;
    tiles.current = Array.from(nodes)
      // Tiles hidden by the mobile budget report a 0x0 box at the origin.
      // Keeping them would put phantom magnet targets at (0,0) that respond to
      // the cursor from across the page.
      .filter((el) => el.getClientRects().length > 0)
      .map((el) => {
        const r = el.getBoundingClientRect();
        return { el, cx: r.left + r.width / 2, cy: r.top + r.height / 2, x: 0, y: 0, tx: 0, ty: 0 };
      });
    // Task D: derive the collision bound from the pitch the browser actually
    // produced, rather than from the `gap` prop. The nearest neighbour on each
    // axis is the smallest non-zero centre-to-centre distance, and the free
    // space is that minus the tile. This has to be measured because the columns
    // are `1fr` and therefore stretch: 24px of declared gap becomes 26.5px of
    // real horizontal clearance in the browser, so a hard-coded gap/2 is wrong
    // on one axis or the other at some viewport width.
    let minX = Infinity;
    let minY = Infinity;
    const t = tiles.current;
    for (let i = 0; i < t.length; i++) {
      for (let j = i + 1; j < t.length; j++) {
        const dx = Math.abs(t[i].cx - t[j].cx);
        const dy = Math.abs(t[i].cy - t[j].cy);
        // Same row / same column only, so diagonal pairs cannot set the bound.
        if (dy < 2 && dx > 2 && dx < minX) minX = dx;
        if (dx < 2 && dy > 2 && dy < minY) minY = dy;
      }
    }
    const w = tiles.current[0].el.offsetWidth;
    const h = tiles.current[0].el.offsetHeight;
    const free = Math.min(
      Number.isFinite(minX) ? minX - w : gap,
      Number.isFinite(minY) ? minY - h : gap,
    );
    // A non-positive bound would freeze the field entirely and an unbounded one
    // would restore the overlap, so fall back to the conservative default.
    maxDisp.current = free > 0 ? (free / 2) * SAFETY : 10;
  }, [gap, SAFETY]);

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

    // The centre cache is only correct for the layout it was measured against,
    // and that layout is NOT final one frame after mount. Measured: with only
    // the rAF + 300ms passes, the cached centres sat well below the tiles'
    // real positions, so a cursor in the upper half of the hero was further
    // than `radius` from every CACHED centre and nothing moved at all - the
    // magnet was silently dead over roughly the top third of the field while
    // still working lower down. It never showed up as a failure because the
    // old unclamped travel was 93px, large enough to paper over a few hundred
    // pixels of offset, and because the test that should have caught it
    // hovered a tile it had itself just measured.
    //
    // What moves the grid after mount: the web font swapping in and changing
    // the hero's height, the hero resolving `100svh` against the real
    // viewport, and the below-fold content settling. A ResizeObserver reacts
    // to all of them, and to any future one, instead of guessing more delays.
    const ro = new ResizeObserver(() => measure());
    if (hostRef.current) ro.observe(hostRef.current);

    // A ResizeObserver only sees SIZE changes, and the layout that shifts here
    // is positional: the header's height changing when the web font swaps moves
    // the hero's top edge without changing the cloud's own box, so no RO
    // callback fires and the cache stays wrong. Measured with the observer in
    // place, the top third of the field was still dead for the first ~2s.
    // `document.fonts.ready` is the event that actually marks the end of that
    // reflow, so re-measure on it as well as on the observer.
    if (typeof document !== "undefined" && "fonts" in document) {
      document.fonts.ready.then(measure).catch(() => {});
    }

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
              //
              // The clamp is not cosmetic. At strength 1.5 the raw force exceeds
              // 1.0 for anything closer than ~83px, which means a tile 25px from
              // the cursor would be told to travel 33.8px - straight past it and
              // out the other side. A dozen tiles doing that at once reads as a
              // vibration, not a shoal. Capping the force at 1 lets a tile travel
              // AT MOST the distance to the cursor: it converges, and it stops.
              //
              // TASK D, a second and independent clamp on the RESULT. Clamping the
              // force alone does not prevent overlap. Neighbouring tiles are
              // `cell + gap` = 72px apart centre to centre, each 48px card, so two
              // tiles pulled towards the same cursor close the gap between them by
              // the SUM of their displacements. Overlap therefore requires
              //   2 * d > (cell + gap) - cell  =  gap = 24
              // so d > 12px is enough to make two cards touch. The brief asked for
              // a ~22px clamp, which would have produced a 20px overlap between
              // every adjacent pair in the magnet's radius - a larger artefact
              // than the one it set out to fix. The bound that is actually
              // collision-free is gap/2, and that is what is used here.
              const f = Math.min(1, (1 - dist / radius) * strength);
              const rawX = dx * f;
              const rawY = dy * f;
              const mag = Math.hypot(rawX, rawY);
              // Guard the divide: at mag 0 the scale would be Infinity, and
              // Infinity * 0 is NaN, which would blank the tile.
              const limit = maxDisp.current;
              const scale = mag > limit ? limit / mag : 1;
              tile.tx = rawX * scale;
              tile.ty = rawY * scale;
            } else {
              tile.tx = 0;
              tile.ty = 0;
            }
          } else {
            tile.tx = 0;
            tile.ty = 0;
          }
          // Exponential lerp, frame-rate independent so a 60Hz and a 144Hz
          // display settle identically. The 1/50 constant is a little snappier
          // than the 1/60 used previously: with tiles now travelling ~90px
          // instead of ~18px, the old curve left them visibly lagging behind the
          // cursor, which is what "sluggish" looks like in motion.
          const k = 1 - Math.pow(0.001, 1 / 50);
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
      ro.disconnect();
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
        // Square cells: the row track is pinned to the same value as the column
        // min, so every logo sits in an identical cell and one `gap` value
        // reads as equal spacing on all four sides. `1fr` rows were the previous
        // approach and are what produced the sparse constellation - with 200+
        // tiles the field is dense enough not to need them.
        gridTemplateColumns: `repeat(auto-fill, minmax(${cell}px, 1fr))`,
        gridAutoRows: `${cell}px`,
        alignContent: "center",
        justifyItems: "center",
        gap: `${gap}px`,
        padding: `${gap}px`,
        opacity,
      }}
    >
      {items.map((logo, i) => (
        <div
          key={logo.name}
          data-magnetic-tile
          data-testid="mcp-logo"
          data-brand={logo.name}
          className={
            // Mobile budget. 218 tiles in 5 columns needs 44 rows, and the hero
            // is one viewport tall, so the field is clipped to a single lonely
            // row - which reads as a rendering bug rather than as texture. No
            // cell size fixes this: 44 rows is 44 rows at any size, and fitting
            // 30 columns into 375px would mean 12px icons. So below `sm` the
            // field is capped, and the cap is removed at `sm` and up. This is
            // pure CSS, so there is no hydration mismatch and no JS bundle cost
            // for a purely presentational decision.
            i < mobileLimit
              ? "pointer-events-none flex select-none items-center justify-center"
              : "pointer-events-none hidden select-none items-center justify-center sm:flex"
          }
          style={{ width: cell, height: cell, willChange: "transform" }}
        >
          {/* Task C: each glyph sits in its own card, the way app icons sit on a
              home screen. The tile keeps the magnetic transform; the card is a
              child, so a moving tile drags its card with it rather than sliding
              a border across the field. */}
          <div
            data-testid="mcp-logo-card"
            className="flex h-full w-full items-center justify-center rounded-xl border border-border/50 bg-card/50"
          >
            {"brand" in logo ? renderDense(logo, size) : renderLogo(logo, size)}
          </div>
        </div>
      ))}
    </div>
  );
}

export default MagneticLogoCloud;


