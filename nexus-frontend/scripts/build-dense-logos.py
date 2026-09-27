"""Resolve candidate brands against the icon packs already installed.

WHY LOCAL AND NOT theSVG / a CDN: this is a statically exported site served
from Cloudflare Pages. Pulling 200+ <img> tags from a third-party host at
runtime means 200 extra requests on the critical path of the hero, which is
where the LCP element lives, plus a visitor-IP leak to that host and a hard
dependency on its uptime. Both packs are already dependencies of this repo, so
the same 200+ brands cost zero requests.

Nothing is substituted. simple-icons removed several brands for trademark
reasons (Slack, OpenAI, AWS, Twilio, ...) and lobehub has no Docker/Postgres,
so the two packs cover different ground. A brand with no icon in either is
DROPPED and reported - the alternative, mapping a near-miss name, is how a
penguin ends up labelled "Slack".

Writes src/lib/dense-logos.generated.json.
"""
import re, io, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

si_raw = (ROOT / 'node_modules/@icons-pack/react-simple-icons/index.d.ts').read_text(encoding='utf-8')
si = set(re.findall(r'default as (Si[A-Za-z0-9]+),', si_raw))
# Exports are PascalCase (SiGithub) while brands are lowercase (github). An
# earlier probe used PowerShell `-contains`, which is case-insensitive, and so
# reported brands as present that were not. Look up case-insensitively but emit
# the real exported name.
si_ci = {n[2:].lower(): n for n in si}

lo = {d.name for d in (ROOT / 'node_modules/@lobehub/icons/es').iterdir() if d.is_dir()}

LO_DIR = ROOT / 'node_modules/@lobehub/icons/es'


def lobehub_primary(icon):
    """The brand's own primary colour, read from the pack's style.js.

    WHY THIS IS NEEDED, measured on production 368881c: `import { OpenAI } from
    '@lobehub/icons'` binds the Mono component (`var Icons = Mono` in the
    package's own index.js), and Mono paints `fill: currentColor`. With no
    colour prop the glyph inherits the theme foreground, so 73 brands rendered
    as flat grey. The previous theory -- that the "grey" logos were a fallback
    placeholder -- was wrong: 0 tiles had a missing fill, 0 network image
    requests were made, and every tile carried `filter: none; opacity: 1`.
    The grey was never a placeholder. It was the correct glyph, unpainted.

    There is no `Combine`-style multicolor alternative: Combine is Mono plus a
    wordmark, not a second colour. `colorPrimary` IS the brand colour, and
    these are the library's own values rather than ones invented here.

    A value of `#fff` is returned as None on purpose. It is a real primary for
    14 of the 73 (Azure, Copilot, Cursor, Midjourney, Ollama, XAI, ...) but
    the hero is a light surface, so painting those white would delete them
    rather than colour them. They keep the foreground and stay visible.
    """
    style = LO_DIR / icon / 'style.js'
    if not style.exists():
        return None
    m = re.search(r"COLOR_PRIMARY\s*=\s*['\"](#[0-9A-Fa-f]{3,8})['\"]",
                  style.read_text(encoding='utf-8'))
    if not m:
        return None
    return None if m.group(1).lower() in ('#fff', '#ffffff') else m.group(1)


candidates = (ROOT / 'scripts/dense-candidates.txt').read_text(encoding='utf-8').splitlines()

found, missing, dupes = {}, [], []
for line in candidates:
    line = line.strip()
    if not line or line.startswith('#'):
        continue
    parts = [p.strip() for p in line.split('|')]
    brand, s_slug, l_dir = (parts + ['', '', ''])[:3]
    if brand in found:
        dupes.append(brand)
        continue
    if s_slug and s_slug.lower() in si_ci:
        found[brand] = {'pack': 'simple-icons', 'icon': si_ci[s_slug.lower()]}
    elif l_dir and l_dir in lo:
        found[brand] = {'pack': 'lobehub', 'icon': l_dir,
                        'color': lobehub_primary(l_dir)}
    else:
        missing.append(brand)

out = ROOT / 'src/lib/dense-logos.generated.json'
out.write_text(json.dumps(found, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')

tiers = {}
for v in found.values():
    tiers[v['pack']] = tiers.get(v['pack'], 0) + 1
print('VERIFIED BRANDS: %d  %s' % (len(found), tiers))
print('DROPPED (%d): %s' % (len(missing), ', '.join(missing)))
if dupes:
    print('DUPLICATE KEYS DROPPED (%d): %s' % (len(dupes), ', '.join(dupes)))
print('written ->', out.relative_to(ROOT))
