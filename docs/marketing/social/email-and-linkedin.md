# Email + LinkedIn — Katalir launch

Figures here are the same ones `verify_roadmap_claims.mjs` enforces against
`dedup_report.json`. If you edit a number, the check fails rather than letting a
stale claim reach a subscriber.

---

## Email 1 — early users / waitlist

**Subject options** (test 2–3; the second is more honest and usually wins):

- `23,474 integrations, 229 proven — here's the difference`
- `I ran tools/call on 351 integrations. Here's what came back.`

**Preheader:** Every listing shows whether we actually executed it, or only
found it.

---

Hi {{first_name}},

You've probably seen a lot of integration directories this year. Most of them
lead with a number.

Katalir leads with a number too, but not the one you'd expect.

**The catalogue is 23,474 unique integrations. 229 of them are proven.**

That's the honest split, and here's what it means:

| What you see | What it means |
| --- | --- |
| `call_verified` | we issued a real tool call and it returned a result |
| `auth_required` | we reached it; it needs your credential |
| `tools_listed` | the server answers `tools/list` |
| `discovered` | metadata only — we've never contacted it |

We ran 351 no-auth MCP connectors, one read-only tool each. 203 came back with
a real result. Every one of those 203 is a green badge you can click into.

**Why bother?** Because the first useful question about "10,000 integrations" is
"how many did you call?" and nobody could answer it — including us, until we
built the thing that measures it.

A few things you might poke at:

- The runtime-tier filter and the badge are computed by the *same function*, so
  the filter can't return rows that aren't what they claim.
- Four protocol importers — MCP, OpenAPI, GraphQL, sandboxed JS — all behind a
  single SSRF guard rather than four that drift apart.
- Your OAuth credentials stay per-user. We don't proxy them.

**Where it's not ready:** payments are wired but business verification is still
pending, and `call_verified` is one call with synthetic arguments, not a full
integration test. Both things are on the site rather than hidden.

{{cta_url}}

If you try it, reply to this email directly. I read them, and the roadmap
changes based on what people actually hit.

— {{founder_name}}
Katalir · https://katalir.de5.net

*You're getting this because you signed up for the waitlist. Unsubscribe:
{{unsubscribe_url}}*

---

## Email 2 — post-launch follow-up (send ~1 week after)

**Subject:** The 3 things people asked me most

Hi {{first_name}},

A week of answers. Three questions came up more than the rest, so here they are
without the fluff.

**1. "So only 229 work? That's not many."**
Fair, and it's the right question. That is what we can *prove* without your OAuth
credentials. Most of the rest needs an account connection only you can authorise
— we're not going to count those as working before you do. If it goes up, it'll
be because more integrations became reachable, and the badge moves with it.

**2. "How do you call tools on someone else's server?"**
Read-only tools only, on endpoints that need no authentication, one at a time
with a delay. Arguments are synthesised from each tool's own JSON schema. There's
an auditor that re-derives the call list from the recorded tool names and
rejects anything mutating — and it runs as a test, not a one-off script.

**3. "What's not done?"**
Payment business verification is still pending. A few verticals are thin. And
the JS sandbox is a process sandbox, not a security boundary — fine for "a user
writes a small integration", not what I'd want for hostile tenants.

---

## LinkedIn post

> I spent most of last month removing a number from a product.
>
> Not because it was false. Because it was useless.
>
> We had a catalogue of 23,474 integrations and every pitch deck said the same
> thing: "10,000+ integrations." It's a great number. It tells you nothing.
>
> So I asked the only question that matters: **how many of those actually work?**
>
> Nobody could answer. Not the vendors, not us. There was no way to find out
> short of installing each one and discovering it was broken — an afternoon per
> integration.
>
> So we went and measured it.
>
> We took 351 MCP integrations that don't need a user's OAuth credential, issued
> one read-only `tools/call` against each with arguments synthesised from the
> tool's own schema, and recorded what came back.
>
> **203 returned a real result.**
>
> Two thirds of the pool. The rest were down, misconfigured, or rejected our
> arguments outright.
>
> Then we did the part nobody likes: every listing now carries the tier that
> earned it. `call_verified`. `auth_required`. `tools_listed`. `discovered`. Not
> collapsed into a friendly "Ready" badge.
>
> The catalogue still says 23,474. But now it also says **229 proven**, and you
> can filter by it.
>
> I nearly cut the whole thing. It made my headline number look terrible — 1% of
> the catalogue. Then something unexpected happened: the "1%" version of the
> pitch started better conversations than the big number ever did. People
> immediately asked smart questions about methodology. Nobody had ever asked me a
> single follow-up about "23,474".
>
> Some things I got wrong along the way, since everyone does:
>
> • A 401 from a vendor API that I spent days diagnosing as "my key is broken."
>   The key was fine. I'd called an endpoint that doesn't exist.
> • A 403 that looked identical. That one was Cloudflare blocking a Python
>   User-Agent. Also not an auth failure.
> • A build that passed locally and failed in CI, because a package I'd
>   installed never made it into package.json. Local green, CI red, and no test
>   on earth would have caught it.
>
> All three had the same shape: **a signal that looked like a fact.** A status
> code, a green checkmark, a passing build. The discipline is in refusing to read
> them as the thing they resemble.
>
> If you're building something similar, the single highest-value thing we did
> was re-derive the evidence from the raw artefacts on a schedule, and exit
> non-zero when it stops reproducing. Not a dashboard. A gate.
>
> Katalir is live: https://katalir.de5.net
> Free tier, no card. Payments are wired but business verification is still
> pending, which I'm stating here so you don't find out later.


I'd rather send this than let you find out later.

— {{founder_name}}
