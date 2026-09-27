# Bounty Program — DESIGN ONLY, NOT LAUNCHED

> **Status: `[!] DEFERRED`**
> This document is a design proposal. **No bounty programme is running, no
> funds are committed, and no submissions are being accepted.** Do not
> advertise this as an open programme. See "Why deferred" at the bottom for
> what has to be true before this can be switched on.

## What a bounty would cover

Work that expands what Katalir can do for users, in rough priority order:

| Area | Example task | Why it pays |
|------|--------------|-------------|
| Integrations | Add a well-maintained SaaS connector | Direct user value |
| Node/tool coverage | Port a missing node into the Katalir catalogue | Closes catalog gaps |
| Docs & tutorials | Indonesian-language guides | SEA go-to-market |
| Tooling | Test harness, benchmark harness, CLI | Improves everyone's work |
| Bug triage | Reproduce + fix with a regression test | Unblocks other people |

## Rules this would operate under

1. **Scope is agreed in writing before work starts.** No retroactive scope
   changes. If the scope moves, the bounty moves with it.
2. **Test-first.** A submission that fixes a bug includes the failing test that
   proved it. No test, no merge.
3. **Original work only.** Copying an upstream implementation verbatim does not
   count, even with attribution.
4. **Licensing is compatible with the project.** Contributors keep authorship;
   they grant the licence needed to ship the work.
5. **One payout per accepted task**, released on merge, not on merge-to-main.
6. **Disclosure.** A contributor who later joins the team full-time discloses it;
   that is normal and not a penalty.

## Payout structure (proposed)

- **Tier 1 — small, well-defined:** docs fix, single connector, regression test
- **Tier 2 — medium:** multi-endpoint integration, node port, benchmark harness
- **Tier 3 — large:** new subsystem, language/framework support

Amounts are **not** set here. Setting them before the programme runs would be a
commitment we have not scoped.

## Anti-patterns this design is meant to prevent

- **Reward volume over quality.** A rubric of "merged PRs" manufactures busywork.
  Bounties pay for outcomes.
- **Race to the bottom on scope.** Work is verified against the agreed scope, not
  the easiest possible interpretation of it.
- **Unfunded promises.** Tiers are only published once funded.

## Why deferred

Three blockers, all of which need a human decision rather than more writing:

1. **Funding is unconfirmed.** A bounty without a funded pool is a debt owed to
   the community. Until the pool exists, advertising tiers is a commitment the
   project cannot honour.
2. **Review capacity is unproven.** Every bounty creates review load. Shipping
   understaffed review turns a contribution programme into a support queue.
3. **Abuse vectors are unmitigated.** Reward programmes attract duplicate
   submissions, plagiarised PRs, and sockpuppets farming tier-1 tasks. The
   defences (one-account enforcement, originality review) need to exist first.

**To un-defer:** fund a pool, measure review throughput, land the abuse
controls, then set tier amounts and publish.
