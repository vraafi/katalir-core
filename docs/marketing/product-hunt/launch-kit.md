# Katalir — Product Hunt launch kit

Everything here is copy-paste ready. Nothing is submitted; submitting is a
human action and stays that way.

**Every number below is checked by `node verify_roadmap_claims.mjs`**, which
re-derives it from `dedup_report.json` and exits non-zero if any claim stops
reproducing. If a figure here drifts from the evidence, the build breaks rather
than the launch quietly shipping a number nobody measured.

---

## Tagline

> The AI agent platform that tells you which integrations actually work.

## Subtitle (60 chars)

> 23,474 integrations. 229 proven by a real tool call.

## Description

Katalir is an AI agent platform for teams that are tired of integration lists
nobody has checked.

Most platforms advertise a catalogue size. We publish a **verification tier for
every single integration**, and the badge tells you exactly what was done to
earn it:

| Badge | What actually happened |
| --- | --- |
| `call_verified` | a real `tools/call` was issued and returned a result |
| `auth_required` | we reached it; it needs your credential |
| `tools_listed` | `initialize` + `tools/list` answered |
| `discovered` | metadata only, never contacted |

Today that means **23,474 unique integrations** in the catalogue, **229 proven
by a real tool call**, and 1,896 that at least answer `tools/list`. We would
rather show you 229 that work than imply 23,474 do.

**What it does**

- **Describe the workflow in a sentence.** No node graph to learn.
- **Four protocol importers** — MCP, OpenAPI, GraphQL, and sandboxed JS — all
  behind one SSRF guard rather than four separate ones.
- **A marketplace that cannot lie to you.** Filter by runtime tier, and the
  filter and the badge are computed by the same function, so they cannot
  disagree.
- **Your credentials stay yours.** OAuth per user, per tenant.

**Built for people who got burned by a catalogue number.** If a vendor says
"10,000 integrations", the first question is "how many did you call?" Ours is
in the badge, on every card.

### The honest caveat, in our own words

`call_verified` means one read-only tool on a no-auth endpoint returned a real
result. It is not a full integration test: single call, synthetic arguments,
third-party servers, no auth. We would rather you know exactly what the badge
means than discover later that it meant less than you hoped.

---

## Topics

`developer-tools`, `ai`, `automation`, `api`, `mcp`, `no-code`,
`self-hosted`, `open-source`

## Links

- Product: `https://katalir.de5.net`
- Docs: `https://katalir.de5.net/docs`
- Repository: _(add before submitting)_

---

## First comment (founder post)

> Hi — I'm the founder of Katalir.
>
> I started this because I kept getting burned the same way: a vendor's site
> would say "10,000+ integrations", and there would be no way to tell which ten
> actually worked. Installing one and finding out was my afternoon, every time.
>
> So we built the boring part first. Katalir issues a real `tools/call` against
> each integration we can reach without your credentials, and every listing
> carries the tier that earned:
>
> - `call_verified` — a real call returned a result
> - `auth_required` — reachable, needs your credential
> - `tools_listed` — the server answers `tools/list`
> - `discovered` — metadata only, never contacted
>
> That's 229 call-verified out of 23,474 in the catalogue today. The gap is
> real and I'd rather show it than hide it. The remaining ones mostly need a
> credential that is yours to give, not work we skipped.
>
> Two things I'd especially like feedback on:
>
> 1. **Is this tier vocabulary the right one?** We collapsed "Ready/Auth
>    required/Catalog" into four states because "listed" is not "usable" and we
>    didn't want the UI to blur them.
> 2. **Would you filter a marketplace by runtime tier?** It's the feature we're
>    least sure anyone wants.
>
> Happy to answer anything about the verification pipeline — including the parts
> that are messy. There's a lot more to build.

---

## Screenshots

In `docs/marketing/screenshots/`. All are real captures of the running product,
not mockups.

| File | What it shows |
| --- | --- |
| `01-landing-marketplace.png` | Landing claim + marketplace |
| `02-call-verified-badges.png` | The four runtime tiers on real cards |
| `03-dedup-toggle.png` | Unique (dedup) view |
| `04-ten-source-tabs.png` | All 10 source tabs, incl. Nango labelled as OAuth |
| `05-mobile.png` | 390px, no horizontal overflow |

Regenerate with:
`npx playwright test -c playwright.dev.config.ts tests/marketplace-f3-evidence.spec.ts`

## Video

`docs/marketing/video/katalir-demo-60s.webm` — 1.0 min, 1.1 MB, 1440x900.

It is a real Playwright recording driving the real product against the real
backend, not a scripted mock, so a number visible in the video is a number the
site actually served. Regenerate with:

```
npx playwright test -c playwright.demo.config.ts
```

The recording lives in its own config on purpose. It is not an assertion, and
putting a camera in the regression suite would slow every test run and make a
recording hiccup look like a product regression.

**Note:** the webm is raw video with no audio, no captions and no titles. For
Product Hunt you will want to add voiceover and captions in a video editor.
That is a human production step and is not automated here.

---

## Launch day checklist

**Before submitting**

- [ ] Add the repository link (we left it blank rather than guess)
- [ ] Re-run `node verify_roadmap_claims.mjs` — must exit 0
- [ ] Confirm the live site serves the same numbers as this file
- [ ] Verify payment flow end to end (Dodo verification is **deferred** — see below)
- [ ] Pick a hunter, or self-post
- [ ] Set up a 2FA-capable account for the launch account

**At launch**

- [ ] Post at a time your audience is awake (SEA: 09:00 or 20:00 WIB)
- [ ] Post the founder comment immediately, not after the upvotes settle
- [ ] Reply to every comment within 30 minutes for the first 2 hours
- [ ] Do **not** ask for upvotes in the first hour
- [ ] Be honest in replies about what is not built yet

**After**

- [ ] Log every question asked into `docs/feedback/blockers-and-complaints.md`
- [ ] Triage within 48h
- [ ] Update this file with what the launch actually taught us

---

## Known deferred work — say it, don't hide it

- **Dodo payment verification (KYC) is deferred.** The API key is present and
  checkout is wired; business verification has not been done. Do not claim
  "payments fully live" on the launch page until it is.
- **Vendor verification beyond Dodo is deferred.**
- **2,000 verified target is not met.** Current: 229. We are publishing the
  real number.

If a commenter asks whether payments work, the answer is the truth, not the
plan.
