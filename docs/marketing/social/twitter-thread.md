# Twitter/X thread — Katalir launch

Every number here is locked by `node verify_roadmap_claims.mjs`, which re-derives
it from `dedup_report.json`. If a number stops matching the evidence the build
fails, so nothing in this thread can quietly go stale.

**Post order matters: the hook is tweet 1, the proof is tweet 2, the offer is last.**

---

## 1/10 — the hook

> Every integration platform shows you a catalogue size.
>
> Almost none of them show you which ones actually work.
>
> So we built one that does. 🧵

---

## 2/10 — the problem, concretely

> The pitch is always "10,000+ integrations".
>
> The first useful question is "how many did you call?"
>
> Usually nobody knows. Installing one and finding out is your afternoon, every
> single time.

---

## 3/10 — what we did

> Katalir issues a real `tools/call` against every integration it can reach
> without your credentials.
>
> 351 no-auth MCP connectors. One read-only tool each. Synthetic arguments.
> We record what came back.

---

## 4/10 — the result

> 351 attempted.
> 203 returned a real result.
>
> That's the whole number. Not 203,000. 203.

---

## 5/10 — the badge

> So every listing carries the tier that earned it:
>
> `call_verified` — a real call returned
> `auth_required` — reachable, needs your credential
> `tools_listed` — the server answers tools/list
> `discovered` — metadata only, never contacted
>
> "Listed" is not "usable". Collapsing those is how marketplaces lie.

---

## 6/10 — the awkward part

> The catalogue says 23,474 unique integrations.
>
> 229 of them are call-verified. That's 1%.
>
> I'd rather tell you that than round the catalogue number up and hope you don't
> open the drawer.

---

## 7/10 — the part most platforms skip

> The filter and the badge are computed by the *same function*.
>
> Not similar functions. The same one.
>
> Otherwise "call_verified" quietly returns rows that aren't call-verified, and
> you find out after you wired it into production.

---

## 8/10 — four protocols

> MCP, OpenAPI, GraphQL, and sandboxed JS.
>
> All four behind one SSRF guard, not four. Four blocklists is four chances to
> ship the weaker one.
>
> The JS sandbox has no network of its own. Its `fetch` calls into our Python
> guard or it doesn't happen.

---

## 9/10 — the honest caveat

> What `call_verified` does NOT mean: a full integration test.
>
> One call. Synthetic args. Third-party servers. No auth, no retries, no
> persistence.
>
> We publish what the badge means rather than let you find the gap later.

---

## 10/10 — the ask

> Katalir is live. Free tier, no card.
>
> Two things I'd genuinely like feedback on:
>
> 1. Is the four-tier vocabulary right, or is it over-engineered?
> 2. Would you filter a marketplace by runtime tier?
>
> That's the part we're least sure about. katalir.de5.net

---

## Replies to expect

**"So 229 working integrations isn't impressive."**
Correct, and that's the point of this post. 229 is what we can *prove*. Everyone
else's 10,000 is unproven by definition. If we hit 2,000 you'll see the number
move, because the badge is driven by the same evidence.

**"Isn't the 1% a red flag?"**
It's a measurement of how much of a typical catalogue is reachable without a
credential. Most of the rest needs an OAuth flow that only you can do. We're
telling you that instead of hiding it.

**"How do you call tools on other people's servers?"**
Read-only tools only, on endpoints that need no auth, one at a time, with a
delay. There's a script that re-audits the call list for mutating verbs, and it
runs as a test.
