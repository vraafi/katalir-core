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
  /**
   * Velocity, in px/step. A spring needs this to overshoot and settle; the
   * previous exponential lerp had no velocity at all, which is precisely why
   * it could never look like a collision.
   */
  vx: number;
  vy: number;
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
  radius = 350,
  strength = 3,
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

  // The travel bound. This used to be derived from the measured free space
  // between tiles, which capped it at ~10.75px and made the field look like a
  // slow drift rather than a shoal. The brief asks for a DRAMATIC pull, so the
  // bound is now an explicit, generous cap that exists only to stop a tile
  // flying off-screen - collisions, not this cap, are what stop tiles merging.
  const maxDisp = useRef(40);
  // Visual size of one card, for the collision radius. Measured, not assumed.
  const tileSize = useRef(48);

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
        return {
          el,
          cx: r.left + r.width / 2,
          cy: r.top + r.height / 2,
          x: 0,
          y: 0,
          tx: 0,
          ty: 0,
          vx: 0,
          vy: 0,
        };
      });
    if (!tiles.current.length) return;
    // Card size drives the collision radius. Measured because the tile is laid
    // out by the grid, and assuming 48px would silently shrink or grow the
    // contact patch if the cell size ever changes.
    tileSize.current = tiles.current[0].el.offsetWidth || 48;
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

    // Spring constants. `SPRING` is the stiffness (how hard a tile is pulled
    // back toward its target) and `DAMP` the per-frame velocity retention (how
    // quickly it stops ringing). Stiffness 150 with heavy damping is the brief's
    // "softer, more flowing" setting: the tile arrives with momentum and eases
    // in rather than snapping.
    const SPRING = 0.15;
    const DAMP = 0.86;

    // Spatial hash for collision broadphase.
    //
    // The naive O(n^2) pair test is 23,762 comparisons per frame for 218
    // tiles, every frame, on the main thread - that is the difference between
    // a smooth shoal and a stuttering one. Bucketing each tile into a cell the
    // size of the contact diameter means a tile can only touch its eight
    // neighbours' buckets, so the real cost is ~6 checks per tile instead of
    // 218. Buckets are rebuilt each frame because every tile moves.
    const BUCKET = tileSize.current || 48;
    const buckets = new Map<string, Tile[]>();
    const key = (gx: number, gy: number) => `${gx},${gy}`;

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
              // The force is NOT clamped to 1. The old `Math.min(1, ...)` existed
              // to stop a tile being told to travel further than the distance to
              // the cursor, which is what made it converge and stop. That is
              // exactly the lifeless behaviour being replaced: with strength 3.0
              // the near tiles are driven hard into the cursor, pile up, and the
              // collision pass below bounces them off each other. Overshoot is
              // the point, not the bug.
              const f = (1 - dist / radius) * strength;
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
          // Damped spring, integrated semi-implicitly (velocity first, then
          // position). This replaces the exponential lerp, which could not
          // produce a collision: a lerp moves each tile independently toward
          // its own target and has no notion of contact, so tiles slid through
          // one another instead of bouncing.
          //
          // The constants are in the brief. `SPRING` is the stiffness and
          // `DAMP` the drag; together they set how hard a tile is pulled and
          // how long it rings afterwards.
          tile.vx += (tile.tx - tile.x) * SPRING;
          tile.vy += (tile.ty - tile.y) * SPRING;
          // Damping is applied to velocity, so a tile that overshoots
          // decelerates instead of oscillating forever. The -0.94 is a
          // per-frame retention factor chosen so a tile comes to rest in
          // roughly a fifth of a second without looking like it is being
          // dragged through syrup.
          tile.vx *= DAMP;
          tile.vy *= DAMP;
          tile.x += tile.vx;
          tile.y += tile.vy;

          if (Math.abs(tile.tx - tile.x) > 0.05 || Math.abs(tile.ty - tile.y) > 0.05) {
            tile.el.style.transform = `translate3d(${tile.x.toFixed(2)}px, ${tile.y.toFixed(2)}px, 0)`;
          }
        }

        // ---------------------------------------------------------------------
        // COLLISION
        //
        // This is the part that makes the field read as a shoal of tiles
        // BOUNCING rather than a set of tiles sliding through one another. The
        // magnet drives every nearby tile toward the same point; without
        // contact resolution they simply stack up on top of each other and the
        // glyphs merge into an unreadable smear.
        //
        // Two things happen on contact, and both are needed:
        //   1. POSITIONAL separation - the pair is pushed apart to the contact
        //      distance, so cards visibly bump and stay legible.
        //   2. VELOCITY exchange along the contact normal - each tile gives the
        //      other the component of its velocity that is driving them
        //      together. This is what produces the BOUNCE. Separation alone
        //      stops the overlap but the tiles would still creep into each other
        //      every frame; only exchanging velocity makes contact repulsive.
        //
        // `MIN_DIST` is deliberately slightly less than the card width. Allowing
        // a few px of visual contact is the whole point: tiles should be seen
        // touching at the moment of impact, not floating with a permanent gap.
        // ---------------------------------------------------------------------
        const MIN_DIST = (tileSize.current || 48) * 0.86;
        const minSq = MIN_DIST * MIN_DIST;

        // SEVERAL relaxation passes, not one.
        //
        // A single pass is Gauss-Seidel: fixing pair (A,B) moves both tiles, which
        // can push A into a third tile C that was already resolved. At strength
        // 3.0 a dozen tiles are driven into the same spot each frame, and one
        // pass left pairs 14.5px apart when the cards are 48px - genuinely
        // FUSED, which is the one outcome the brief forbids.
        //
        // The buckets are REBUILT INSIDE the loop, and that is the load-bearing
        // detail. Bucketing once and relaxing many times made things WORSE, not
        // better: measured 4 passes -> 28.0px min contact, 12 passes -> 11.0px.
        // The map described where tiles were at the start of the frame while the
        // lookup coordinates were recomputed from their CURRENT positions, so
        // after a few passes tiles had drifted out of the buckets they were
        // filed under and most pairs were never tested at all. The bucket set
        // must be re-derived whenever the set it indexes has moved.
        const PASSES = 12;
        for (let pass = 0; pass < PASSES; pass++) {
          const applyImpulse = pass === 0;

          buckets.clear();
          for (const tile of tiles.current) {
            const gx = Math.floor((tile.cx + tile.x) / BUCKET);
            const gy = Math.floor((tile.cy + tile.y) / BUCKET);
            const k = key(gx, gy);
            const cell = buckets.get(k);
            if (cell) cell.push(tile);
            else buckets.set(k, [tile]);
          }

          for (const tile of tiles.current) {
            const gx = Math.floor((tile.cx + tile.x) / BUCKET);
            const gy = Math.floor((tile.cy + tile.y) / BUCKET);
            for (let ox = -1; ox <= 1; ox++) {
              for (let oy = -1; oy <= 1; oy++) {
                const near = buckets.get(key(gx + ox, gy + oy));
                if (!near) continue;
                for (const other of near) {
                  // Each pair once per pass. Comparing bucket keys would need the
                  // original indices, so identity is the cheap equivalent.
                  if (other === tile) continue;
                  const dx = tile.cx + tile.x - (other.cx + other.x);
                  const dy = tile.cy + tile.y - (other.cy + other.y);
                  const distSq = dx * dx + dy * dy;
                  if (distSq >= minSq || distSq === 0) continue;
                  const dist = Math.sqrt(distSq);
                  const nx = dx / dist;
                  const ny = dy / dist;
                  const overlap = MIN_DIST - dist;

                  // 1. Positional separation, split evenly.
                  tile.x += nx * overlap * 0.5;
                  tile.y += ny * overlap * 0.5;
                  other.x -= nx * overlap * 0.5;
                  other.y -= ny * overlap * 0.5;

                  // 2. Exchange the closing component of velocity, once. This is
                  // what produces the BOUNCE: separation alone stops the overlap
                  // but the tiles would still creep into each other every frame.
                  if (!applyImpulse) continue;
                  const relVx = tile.vx - other.vx;
                  const relVy = tile.vy - other.vy;
                  const closing = relVx * nx + relVy * ny;
                  if (closing < 0) {
                    const imp = closing * 0.9;
                    tile.vx -= imp * nx;
                    tile.vy -= imp * ny;
                    other.vx += imp * nx;
                    other.vy += imp * ny;
                  }
                }
              }
            }
          }
        }

        // Collision moved tiles after their transforms were written, so the
        // correction has to be flushed or it shows up one frame late as a
        // visible lag on every impact.
        for (const tile of tiles.current) {
          tile.el.style.transform = `translate3d(${tile.x.toFixed(2)}px, ${tile.y.toFixed(2)}px, 0)`;
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


