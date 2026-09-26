# Reddit posts — Katalir launch

**Read this before posting.** Each subreddit has its own rule about promotion, and
the wrong post in the wrong one gets removed and can get the account banned.
These are drafts *for a human to review and adapt*, not copy-paste-and-fire.

Rules that shaped the drafts:

- **r/SaaS** allows self-promotion with a "[Launch]" tag. It does not allow a
  wall of marketing copy.
- **r/n8n** is hostile to vendors. n8n has thousands of nodes and a large,
  protective community. Positioning Katalir as "n8n's AI-era equivalent" is
  asking to be flamed. The honest angle is the parity audit.
- **r/artificial** is for research and discussion, not products. This is the
  weakest fit of the four; consider skipping it.
- **r/indiehackers** welcomes founder stories with real numbers, including
  unflattering ones.

Every figure below is the same figure `verify_roadmap_claims.mjs` enforces.

---

## r/SaaS — "[Launch] Katalir — publishes which integrations actually work"

> I built this because I kept getting the same afternoon: a vendor says "10,000+
> integrations", there's no way to tell which ten work, and you find out by
> installing one.
>
> So the marketplace issues a real `tools/call` against every integration it can
> reach without your credentials. 351 no-auth MCP connectors, one read-only tool
> each, synthetic arguments. 203 returned a real result.
>
> Every listing carries the tier that earned it:
> `call_verified` / `auth_required` / `tools_listed` / `discovered`
>
> The catalogue is 23,474 unique integrations. 229 are call-verified. I'm
> publishing the 1% rather than rounding up, because the whole point is that the
> number can be trusted.
>
> Two implementation details I'm slightly proud of:
>
> - The tier filter and the tier badge are computed by the same function. Two
>   copies of one rule will eventually disagree, and then the filter lies.
> - The JS sandbox has no network of its own. Its `fetch` calls into our Python
>   SSRF guard. Four protocols, one guard, rather than four blocklists that drift.
>
> Honest limits: `call_verified` is one call with synthetic arguments, not a full
> integration test. Most of the catalogue needs an OAuth flow only you can do.
> Payments are wired but business verification is still pending.
>
> Free tier, no card: katalir.de5.net
>
> Genuinely unsure about two things — is the four-tier vocabulary the right
> granularity, and would anyone actually filter a marketplace by runtime tier? If

---

## r/n8n — the one that needs care

**Recommended framing: ask for feedback, don't pitch.** Lead with the audit, not
the product. n8n's community is protective of n8n.

> We're building an AI agent platform (Katalir) and one of our research steps was
> a parity audit: we pulled n8n's node list and mapped which capabilities we
> cover, which we don't, and where we're deliberately different.
>
> I don't want to post marketing. What I want is the map, because we're at the
> stage where being told "you're missing the boring node everyone actually uses"
> is the most useful thing anyone could say.
>
> Where we came out ahead, honestly: we publish a per-integration verification
> tier. n8n tells you a node exists; we tell you whether we actually executed a
> tool on it. Of our 23,474 catalogue integrations, 229 are call-verified today.
> The rest is listed or discovered only, and we label it that way.
>
> Where we're clearly behind: n8n's node coverage is enormous and ours is a
> fraction of it. Most of the gap is vertical apps we haven't touched.
>
> If anyone has a view on the verification-tier idea — does showing "this one
> needs a credential" on a listing make you more or less likely to trust the
> thing? Genuinely don't know.
>
> Happy to share the parity map if it's useful.

---

## r/artificial — weakest fit, consider skipping

Research and discussion, not products. A product post is likely to be removed.
If you post at all, post the *method* and let the product be a footnote.

> We needed to know how much of a large MCP integration catalogue is actually
> reachable without a user's OAuth credential, and nobody seemed to have measured
> it, so we did.
>
> Method, in case it's useful: take the catalogue, filter to endpoints that
> require no auth, issue one read-only `tools/call` each with arguments
> synthesised from the tool's own JSON schema, and record what comes back.
> Sequential, rate-limited, nothing mutating.
>
> Result on our 351-connector no-auth pool: 203 returned a real result, 107
> errored, 26 had no tool we were willing to call, 14 rejected our synthetic
> arguments.
>
> The finding we didn't expect: a meaningful chunk of failures were servers
> rejecting *plausible* arguments, not being down. If you're benchmarking MCP
> servers, "did it answer" and "did it answer correctly" are different questions,
> and only the first is easy to measure.
>
> We wrote the auditor so it re-derives the call list from the recorded tool names
> rather than trusting the sweep that made the calls. A test that reads its own
> input is not a test.
>
> Happy to share the harness. (We built this for our own product, Katalir, but
> the method is the interesting part.)

---

## r/indiehackers — the numbers-first version

> **What I learned shipping a "23,474 integrations" claim that only 229 of are
> verified.**
>
> I built an AI agent platform. The obvious marketing move was to lead with the
> catalogue size: 23,474 unique integrations. Big number, lots of traffic.
>
> Then I tried to work out how many of them *worked*, and there was no answer,
> because nothing in the industry tracks it. So I built the tracking: issue a
> real `tools/call` against everything reachable without a user's credential,
> and badge every listing with what actually happened.
>
> The uncomfortable result: 229 out of 23,474, about 1%.
>
> I nearly dropped the badge system because it made my own headline number look
> terrible. Then it turned out the opposite — "229 proven, here's exactly how" is
> a far better pitch than "23,474, trust us", and it brought better
> conversations than the big number ever did.
>
> Three specific things that cost me real time:
>
> 1. A 401 from a third-party API does not mean your key is bad. Ours did, for
>    days, because I'd called an endpoint that doesn't exist. The key was fine the
>    whole time.
> 2. The same thing happened as a 403 — that one was Cloudflare blocking a Python
>    User-Agent. Also not an auth failure.
> 3. I shipped a build once that passed locally and failed in CI, because I'd
>    installed a package that never made it into package.json. Local green, CI
>    red, and no test would ever have caught it.
>
> Payments: wired, business verification still pending. Saying that here rather
> than hoping nobody checks.
>
> katalir.de5.net — free tier, no card. Happy to answer anything about the
> verification pipeline, including the parts that are still a mess.

> you've thought about this more than I have, I'd like to hear it.
