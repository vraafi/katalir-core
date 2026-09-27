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
lo = {b: v['icon'] for b, v in data.items() if v['pack'] == 'lobehub'}

# Several candidate rows resolve to the SAME icon (Baseten and Baseten2 both
# point at lobehub's Baseten). Importing one identifier twice is a TypeScript
# error, and the second brand is a duplicate on screen, so both are dropped
# here rather than being caught at build time.
def dedupe(items):
    seen, keep = set(), {}
    for b, icon in sorted(items.items()):
        if icon in seen:
            continue
        seen.add(icon)
        keep[b] = icon
    return keep

si, lo = dedupe(si), dedupe(lo)
dropped_dupes = (len(data) - len(si) - len(lo))

def block(items, width=88):
    """One identifier per line, wrapped.

    The identifier is the ICON name, never the brand name. The two differ
    (`Node.js` the brand is `SiNodedotjs` the export), and emitting the brand
    name produces a file that does not compile.
    """
    out, line = [], ''
    for icon in sorted(items.values()):
        piece = icon + ','
        if line and len(line) + 1 + len(piece) > width:
            out.append('  ' + line)
            line = piece
        else:
            line = (line + ' ' + piece) if line else piece
    if line:
        out.append('  ' + line)
    return '\n'.join(out)

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
};

export const denseLogos: DenseLogo[] = [
%s
];
''' % (
    block(si), block(lo),
    '\n'.join('  { name: "%s", Component: %s, brand: true },' % (b, si[b]) for b in sorted(si)) +
    '\n' +
    '\n'.join('  { name: "%s", Component: %s, brand: false },' % (b, lo[b]) for b in sorted(lo)),
)

(ROOT / 'src/lib/dense-logos.ts').write_text(header, encoding='utf-8')
print('wrote src/lib/dense-logos.ts  (%d simple-icons, %d lobehub, %d total, %d duplicate icons dropped)'
      % (len(si), len(lo), len(si) + len(lo), dropped_dupes))
