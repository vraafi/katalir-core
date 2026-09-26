"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { mcpLogos, simpleIconUrl, type McpLogo } from "@/lib/mcp-logos";

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

/**
 * One logo tile with a magnetic pull, tilt and a cursor spotlight.
 *
 * Accessibility and clickability rules that are deliberate, not accidents:
 *  - the tile is `pointer-events-none`, so a logo can never be clicked or
 *    focused. It is decoration next to a real link, and a fake button is worse
 *    than no button;
 *  - it is `aria-hidden`, with the brand named once in the section's visually
 *    hidden list, so a screen reader does not announce 50 duplicate images;
 *  - all motion is disabled under `prefers-reduced-motion`.
 */
function MagneticLogo({ logo }: { logo: McpLogo }) {
  const ref = useRef<HTMLDivElement>(null);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [spot, setSpot] = useState({ x: 50, y: 50, on: false });
  const [hovered, setHovered] = useState(false);
  const reduced = usePrefersReducedMotion();

  const onMove = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (reduced) return;
      const el = ref.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const dx = event.clientX - (rect.left + rect.width / 2);
      const dy = event.clientY - (rect.top + rect.height / 2);
      const distance = Math.hypot(dx, dy);
      const inside = distance < RANGE;
      const falloff = inside ? 1 - distance / RANGE : 0;
      setOffset({ x: dx * STRENGTH * falloff, y: dy * STRENGTH * falloff });
      setSpot({
        x: ((event.clientX - rect.left) / rect.width) * 100,
        y: ((event.clientY - rect.top) / rect.height) * 100,
        on: inside,
      });
    },
    [reduced],
  );

  const onLeave = useCallback(() => {
    setOffset({ x: 0, y: 0 });
    setSpot((s) => ({ ...s, on: false }));
    setHovered(false);
  }, []);

  const tilt = reduced ? {} : { rotateX: hovered ? -6 : 0, rotateY: hovered ? 6 : 0 };

  return (
    <div
      ref={ref}
      aria-hidden="true"
      data-testid="mcp-logo"
      onMouseMove={onMove}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={onLeave}
      className="pointer-events-none relative flex h-16 w-full select-none items-center justify-center rounded-2xl border border-border bg-surface/60 transition-colors duration-200"
      style={{
        transform: `translate3d(${offset.x}px, ${offset.y}px, 0)`,
        transition: reduced ? "none" : "transform 220ms cubic-bezier(0.22,1,0.36,1)",
      }}
    >
      <span
        className="pointer-events-none absolute inset-0 rounded-2xl opacity-0 transition-opacity duration-200"
        style={{
          opacity: spot.on ? 1 : 0,
          background: `radial-gradient(120px circle at ${spot.x}% ${spot.y}%, rgba(108,99,255,0.28), transparent 70%)`,
        }}
      />
      <span
        className="pointer-events-none flex items-center justify-center transition-transform duration-200"
        style={{ transform: `perspective(600px) ${tilt ? `rotateX(${tilt.rotateX}deg) rotateY(${tilt.rotateY}deg) scale(${hovered ? 1.12 : 1})` : "scale(1)"}` }}
      >
        {logo.Component ? (
          <logo.Component size={30} />
        ) : (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={simpleIconUrl(logo.slug ?? "")} alt="" width={30} height={30} loading="lazy" decoding="async" />
        )}
      </span>
    </div>
  );
}

export function LogoCloud() {
  return (
    <section className="px-5 py-20 sm:px-8" aria-labelledby="logo-cloud-title" data-testid="logo-cloud">
      <div className="mx-auto max-w-5xl">
        <h2 id="logo-cloud-title" className="text-center text-2xl font-medium tracking-tight text-fg">
          Works with <span className="text-accent">200+ MCP servers</span>
        </h2>
        <p className="mx-auto mt-3 max-w-2xl text-center text-[13.5px] leading-relaxed text-fg-muted">
          A single catalog spans native MCP, OpenConnector, Composio, Glama and generated OpenAPI
          wrappers. Decoration only — open the integrations page for the source and verification
          status of each one.
        </p>
        <ul className="sr-only">
          {mcpLogos.map((l) => (
            <li key={`sr-${l.name}`}>{l.name}</li>
          ))}
        </ul>
        <div className="mt-10 grid grid-cols-3 gap-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8">
          {mcpLogos.map((logo) => (
            <li key={logo.name} className="contents">
              <MagneticLogo logo={logo} />
            </li>
          ))}
        </div>
      </div>
    </section>
  );
}
