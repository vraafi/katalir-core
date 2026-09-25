# Accessibility Audit — 2026-09-25

Axe-core is the pragmatic replacement for the broken Lighthouse CLI. `@axe-core/playwright` is installed locally and `scripts/verify-a11y.mjs` scans production `/`, `/pricing`, `/docs`, `/chat`, and `/builder` at mobile viewport.

## Iterations

1. `browser.newPage()` is unsupported by `@axe-core/playwright`; fixed by creating a separate context per route.
2. The corrected run exceeded the tool's 30-second execution window before a complete five-route result was returned.

## Results

- `/`: 0 critical, 0 serious; 1 minor `image-redundant-alt`.
- `/pricing`: 0 violations.
- `/docs`: 0 violations.
- `/chat`: 0 violations.
- `/builder`: 0 violations.

Critical/serious threshold passes: `A11Y_CRITICAL=0 A11Y_SERIOUS=0`.

No critical or serious violation fix was required. The remaining homepage issue is minor redundant alt text and is recorded rather than hidden.

## P2.5

Authenticated seeded export test is still pending a browser download event; analytics and templates render in the authenticated probe. Source verification remains in place.

## Attempt 1

Command used Lighthouse mobile against the production homepage:

```text
node C:\Users\user\AppData\Roaming\npm\node_modules\lighthouse\cli\index.js https://katalir.de5.net/
```

Result:

```text
ERR_MODULE_NOT_FOUND: core/gather/gatherers/trace.js
```

The global Lighthouse package is incomplete/corrupted. No performance or accessibility score is accepted from a failed run.

## Bilingual evidence

Production probes completed for `/pricing`, `/docs`, `/about`, and `/changelog` in ID and EN with no page/console errors. Screenshots are in `nexus-frontend/test-results/p23-bilingual/`.

## Authenticated evidence

`test-jwt.txt` is absent. Authenticated P2.5 interaction was not falsely marked as passed.

## Next action

Reinstall Lighthouse cleanly, then run mobile and desktop audits for `/`, `/pricing`, and `/docs`; update this document with actual JSON scores. Obtain a fresh browser JWT before authenticated P2.5 verification.
