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
        found[brand] = {'pack': 'lobehub', 'icon': l_dir}
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
