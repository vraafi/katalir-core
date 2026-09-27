"""Emit src/lib/dense-logos.ts from the resolved brand -> icon map.

The existing src/lib/mcp-logos.ts imports icons by NAME, which is what makes the
pack tree-shakeable. A namespace import (`import * as Si`) would pull all 3453
simple-icons into the landing bundle, so the imports here are generated as
explicit named imports and the mapping is left to the bundler.

This file is generated. Edit scripts/dense-candidates.txt and re-run
`python scripts/build-dense-logos.py` instead of editing the output.
"""
import json, io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
data = json.loads((ROOT / 'src/lib/dense-logos.generated.json').read_text(encoding='utf-8'))

si = {b: v['icon'] for b, v in data.items() if v['pack'] == 'simple-icons'}
lo = {b: v for b, v in data.items() if v['pack'] == 'lobehub'}

# Several candidate rows resolve to the SAME icon (Baseten and Baseten2 both
# point at lobehub's Baseten). Importing one identifier twice is a TypeScript
# error, and the second brand is a duplicate on screen, so both are dropped
# here rather than being caught at build time.
def dedupe(items, key):
    seen, keep = set(), {}
    for b in sorted(items):
        k = key(items[b])
        if k in seen:
            continue
        seen.add(k)
        keep[b] = items[b]
    return keep


si = dedupe(si, lambda v: v)
lo = dedupe(lo, lambda v: v['icon'])
dropped_dupes = (len(data) - len(si) - len(lo))


def interleave(painted, neutral, ratio=3):
    """Spread unpainted brands evenly through the field instead of appending.

    Measured on production 368881c: emitting simple-icons then lobehub put all
    73 unpainted brands in one contiguous run, which filled the last four grid
    rows. The report was "the logos at the bottom are grey", and that reading
    was correct -- the cause was the emit ORDER, not any gradient or lazy
    load.

    The first attempt consumed painted logos at a fixed 1:3 ratio, which is not
    a real interleave here: 73 neutrals x 4 slots needs 292 painted slots and
    only 145 exist, so the painted list ran dry after 48 neutrals and the last
    24 clumped into a single run again. Placing each neutral at an evenly
    spaced index across the full painted list cannot clump, and it degrades
    gracefully if the share of unpainted brands ever rises.
    """
    p, n = sorted(painted), sorted(neutral)
    if not n:
        return [('painted', x) for x in p]
    out, prev = [], -1
    for j, item in enumerate(n):
        # Stride across the painted list so consecutive gaps differ by at most
        # one cell, which is what makes the field read as even texture.
        target = min(len(p) - 1, int(round((j + 1) * len(p) / (len(n) + 1))))
        for i in range(prev + 1, target + 1):
            out.append(('painted', p[i]))
        out.append(('neutral', item))
        prev = target
    out.extend(('painted', p[i]) for i in range(prev + 1, len(p)))
    return out

def block(icons, width=88):
    """One identifier per line, wrapped.

    The identifier is the ICON name, never the brand name. The two differ
    (`Node.js` the brand is `SiNodedotjs` the export), and emitting the brand
    name produces a file that does not compile.
    """
    out, line = [], ''
    for icon in sorted(icons):
        piece = icon + ','
        if line and len(line) + 1 + len(piece) > width:
            out.append('  ' + line)
            line = piece
        else:
            line = (line + ' ' + piece) if line else piece
    if line:
        out.append('  ' + line)
    return '\n'.join(out)

# All lobehub brands -- coloured and unpainted alike -- are interleaved against
# the simple-icons block together. Grouping the coloured ones at the end would
# reproduce the exact "solid block at the bottom" artefact this fixes.
rows = []
for kind, brand in interleave(sorted(si), sorted(lo)):
    if kind == 'painted':
        rows.append('  { name: "%s", Component: %s, brand: true },' % (brand, si[brand]))
    elif lo[brand].get('color'):
        rows.append('  { name: "%s", Component: %s, brand: false, color: "%s" },'
                    % (brand, lo[brand]['icon'], lo[brand]['color']))
    else:
        rows.append('  { name: "%s", Component: %s, brand: false },' % (brand, lo[brand]['icon']))

header = '''/**
 * DENSE landing logo field — GENERATED, do not edit by hand.
 *
 * Regenerate with: python scripts/build-dense-logos.py
 * (edit scripts/dense-candidates.txt first).
 *
 * WHY THIS FILE EXISTS INSTEAD OF A CDN OF ICONS:
 * the landing page is a static export on Cloudflare Pages, and the hero holds
 * the LCP element. Loading 200+ <img> tags from theSVG or cdn.simpleicons.org
 * would put 200 third-party requests on the critical path, leak every visitor's
 * IP and User-Agent to that host, and make the page's most important screen
 * depend on someone else's uptime. Both icon packs are already dependencies of
 * this repo, so the same 220 brands cost zero network requests and work
 * offline.
 *
 * BRAND ACCURACY, which is the whole point of the verification tier:
 *   - simple-icons v16 REMOVED several brands for trademark reasons (Slack,
 *     OpenAI, AWS, Twilio, Heroku). Those come from lobehub instead.
 *   - lobehub has no Docker/PostgreSQL/Redis, so those come from simple-icons.
 *   - A brand present in neither pack is DROPPED by the generator, never
 *     approximated. `SiSlackware` is a Linux distribution, not Slack, and
 *     shipping a penguin under Slack's name is the exact plausible-looking
 *     wrong this project's tests exist to catch.
 *
 * ORDER IS INTERLEAVED, deliberately. Emitting the two packs as two blocks put
 * all 73 lobehub brands in one contiguous run that filled the last four grid
 * rows, which read as "the logos at the bottom are grey". The glyphs were
 * never wrong; the grey was lobehub Mono inheriting currentColor, and the
 * block was an artefact of emit order. One lobehub brand per three simple-icons
 * brands now keeps the field reading as one texture.
 */
import {
%s
} from "@icons-pack/react-simple-icons";
import {
%s
} from "@lobehub/icons";

export type DenseLogo = {
  name: string;
  Component: React.ElementType;
  /** simple-icons: ask for the real brand fill. lobehub Mono: theme foreground. */
  brand: boolean;
  /**
   * lobehub's own COLOR_PRIMARY, when the brand has one that is visible on the
   * light hero. Absent for simple-icons (which paints itself) and for the 32
   * lobehub brands whose primary is genuinely black or white -- see the note
   * in scripts/build-dense-logos.py for the measured diagnosis.
   */
  color?: string;
};

export const denseLogos: DenseLogo[] = [
%s
];
''' % (
    block(si.values()), block(v['icon'] for v in lo.values()),
    '\n'.join(rows),
)

(ROOT / 'src/lib/dense-logos.ts').write_text(header, encoding='utf-8')
n_col = sum(1 for b in lo if lo[b].get('color'))
print('wrote src/lib/dense-logos.ts  (%d simple-icons, %d lobehub, %d total, '
      '%d duplicate icons dropped)' % (len(si), len(lo), len(si) + len(lo), dropped_dupes))
print('  brand-coloured via colorPrimary: %d  |  monochrome by design (#000/#fff): %d'
      % (n_col, len(lo) - n_col))
