# Lighthouse Audit — 2026-09-25

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
