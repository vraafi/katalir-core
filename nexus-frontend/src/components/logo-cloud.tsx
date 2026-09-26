"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { mcpLogos, heroLogos, type McpLogo } from "@/lib/mcp-logos";

const RANGE = 150;
const STRENGTH = 0.3;

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const onChange = () => setReduced(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

type Rect = { left: number; top: number; width: number; height: number };
type Active = { index: number; x: number; y: number; dx: number; dy: number } | null;

/**
 * One logo tile: renders the brand and applies the transform the grid computed.
 *
 * Accessibility and clickability rules that are deliberate, not accidents:
 *  - the tile is `pointer-events-none` and `aria-hidden`, so a logo can never be
 *    clicked, focused or announced. A grid of 55 fake buttons would be worse
 *    than no logos at all, and the brands are named once in the sr-only list;
 *  - because `pointer-events: none` also means the browser never dispatches
 *    mouse events to the tile, the magnetic input is handled on the parent grid
 *    and passed down as props. That is what lets "not clickable" and "moves
 *    toward the cursor" coexist;
 *  - all motion is disabled under `prefers-reduced-motion`.
 */
function MagneticLogo({
  logo,
  active,
  reduced,
}: {
  logo: McpLogo;
  active: Active;
  reduced: boolean;
}) {
  // The grid only hands the matching tile a non-null `active`, so no index
  // comparison is needed in here.
  const x = active?.dx ?? 0;
  const y = active?.dy ?? 0;
  const isActive = active !== null;
  const scale = isActive ? 1.12 : 1;
  // simple-icons paints its own brand fill; lobehub Mono and the baked paths
  // paint `currentColor` and so need the colour set on the wrapper instead.
  const isBrandFill = logo.color === "default";

  return (
    <div
      aria-hidden="true"
      data-testid="mcp-logo"
      className="pointer-events-none relative flex h-16 w-full select-none items-center justify-center rounded-2xl border border-border bg-surface/60 transition-colors duration-200"
      style={{
        transform: reduced ? "none" : `translate3d(${x}px, ${y}px, 0)`,
        transition: reduced ? "none" : "transform 220ms cubic-bezier(0.22,1,0.36,1)",
      }}
    >
      <span
        className="pointer-events-none absolute inset-0 rounded-2xl transition-opacity duration-200"
        style={{
          opacity: active ? 1 : 0,
          background: active
            ? `radial-gradient(120px circle at ${active.x}% ${active.y}%, rgba(108,99,255,0.28), transparent 70%)`
            : "none",
        }}
      />
      <span
        className="pointer-events-none flex items-center justify-center transition-transform duration-200"
        style={{
          transform: reduced
            ? "none"
            : `perspective(600px) rotateX(${isActive ? -6 : 0}deg) rotateY(${isActive ? 6 : 0}deg) scale(${scale})`,
          // Only the lobehub and baked-path tiers read this. `text-fg-muted` stays
          // as the class fallback, so a brand with no colour of its own shows up
          // as muted grey rather than as an invisible or wrongly-coloured logo.
          ...(isBrandFill ? {} : { color: logo.color ?? "var(--fg)" }),
        }}
      >
        {logo.Component ? (
          // simple-icons resolves "default" to the real brand hex itself, which
          // is why the wrapper must not force a colour over it. The outer check
          // on logo.Component is what narrows the type - testing isBrandFill
          // alone leaves it possibly-undefined, and the build (unlike a bare
          // tsc pass) rejects that.
          isBrandFill ? (
            <logo.Component size={30} color="default" />
          ) : (
            <logo.Component size={30} />
          )
        ) : (
          <svg
            viewBox={logo.path?.viewBox ?? "0 0 24 24"}
            width={30}
            height={30}
            fill="currentColor"
            aria-hidden="true"
            focusable="false"
          >
            <path d={logo.path?.d ?? ""} />
          </svg>
        )}
      </span>
    </div>
  );
}

/**
 * The compact cloud that sits in the hero, directly under the CTA.
 *
 * Separate from LogoCloud on purpose. The full grid is 55 tiles across 8
 * columns - roughly 450px tall - and putting that above the fold would push the
 * headline and the CTA down, which is the exact opposite of what a hero is for.
 * So the hero gets the ten most recognisable brands on one row, and the full
 * cloud stays below the fold where it can breathe.
 *
 * Accessibility and clickability rules are inherited from the full cloud's
 * design: decorative only, aria-hidden, pointer-events-none. No logo can be
 * clicked or focused, and the brand names are announced once in the sr-only
 * list of the full cloud below.
 */
export function HeroLogoStrip() {
  return (
    <div className="mt-9" data-testid="hero-logo-strip">
      <p className="text-[11px] uppercase tracking-wider text-fg-subtle">
        Works with 200+ MCP servers
      </p>
      <ul className="mt-3 flex list-none flex-wrap items-center gap-x-6 gap-y-3">
        {heroLogos.map((logo) => (
          <li key={`hero-` + logo.name} className="pointer-events-none select-none" aria-hidden="true">
            {logo.Component ? (
              logo.color === "default" ? (
                <logo.Component size={22} color="default" />
              ) : (
                <span style={{ color: logo.color ?? "var(--fg)" }}>
                  <logo.Component size={22} />
                </span>
              )
            ) : (
              <svg
                viewBox={logo.path?.viewBox ?? "0 0 24 24"}
                width={22}
                height={22}
                fill={logo.color ?? "currentColor"}
                aria-hidden="true"
                focusable="false"
              >
                <path d={logo.path?.d ?? ""} />
              </svg>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function LogoCloud() {
  const gridRef = useRef<HTMLUListElement>(null);
  const [active, setActive] = useState<Active>(null);
  const reduced = usePrefersReducedMotion();

  const onMove = useCallback(
    (event: React.MouseEvent<HTMLUListElement>) => {
      if (reduced) return;
      const grid = gridRef.current;
      if (!grid) return;
      const tiles = grid.querySelectorAll<HTMLElement>("[data-testid=mcp-logo]");
      let best: Active = null;
      let bestDist = RANGE;
      tiles.forEach((tile, index) => {
        const rect = tile.getBoundingClientRect();
        const cx = rect.left + rect.width / 2;
        const cy = rect.top + rect.height / 2;
        const dx = event.clientX - cx;
        const dy = event.clientY - cy;
        const dist = Math.hypot(dx, dy);
        if (dist < bestDist) {
          bestDist = dist;
          best = {
            index,
            x: ((event.clientX - rect.left) / rect.width) * 100,
            y: ((event.clientY - rect.top) / rect.height) * 100,
            dx: dx * STRENGTH * (1 - dist / RANGE),
            dy: dy * STRENGTH * (1 - dist / RANGE),
          };
        }
      });
      setActive(best);
    },
    [reduced],
  );

  return (
    <section
      className="px-5 py-20 sm:px-8"
      aria-labelledby="logo-cloud-title"
      data-testid="logo-cloud"
    >
      <div className="mx-auto max-w-5xl">
        <h2 id="logo-cloud-title" className="text-center text-2xl font-medium tracking-tight text-fg">
          Works with <span className="text-accent">200+ MCP servers</span>
        </h2>
        <p className="mx-auto mt-3 max-w-2xl text-center text-[13.5px] leading-relaxed text-fg-muted">
          One catalog spanning native MCP, OpenConnector, Composio, Glama and generated OpenAPI
          wrappers. Decoration only — open the integrations page for the source and verification
          status of each one.
        </p>
        <ul className="sr-only">
          {mcpLogos.map((l) => (
            <li key={`sr-${l.name}`}>{l.name}</li>
          ))}
        </ul>
        <ul
          ref={gridRef}
          onMouseMove={onMove}
          onMouseLeave={() => setActive(null)}
          className="mt-10 grid list-none grid-cols-3 gap-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8"
        >
          {mcpLogos.map((logo, index) => (
            <li key={logo.name}>
              <MagneticLogo logo={logo} active={active?.index === index ? active : null} reduced={reduced} />
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
