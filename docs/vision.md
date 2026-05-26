# Product Vision

ODIN synthesizes structured profiles from the public web. This document records where the product is heading and the constraints that govern how it gets there. For the ranked, actionable work, see [`TODO.md`](../TODO.md).

## North star

Two goals lead, in order:

1. **User value and reach.** Make ODIN more useful to the person searching, and help more people find and trust it: usefulness, discoverability, credibility, and shareability.
2. **Craft and reliability.** A correct, polished, trustworthy product. A close second, and often the thing that earns reach.

Profit is not ODIN's motive; it is a project, not a commercial venture. It must still stay financially sustainable: the project must cover its own hosting and third-party license costs, so the cost to serve a query is a first-class factor in every feature, design, and scaling decision. At critical mass, sustainability will come from either users paying for access or advertising that scales with usage and aligns with these values. That is a future contingency to plan toward, never a reason to compromise citation integrity or user trust.

## Two modes

ODIN offers two experiences over one pipeline:

**Fast profile (default).** Type a name, place, event, or topic and get a structured profile in roughly 30 seconds: a summary, highlights and lowlights, a timeline, citations, and a confidence-and-bias assessment, each stage streaming to the page as it builds. This stays the front door and the funnel.

**Deep research (opt-in).** A bounded, agentic mode for users who want depth. It runs more rounds of search, hunts for connections across sources, and narrates its reasoning as it works. Users choose it deliberately, which keeps its higher cost and longer runtime off the default path.

The ambition behind deep research: a research-automation tool that digs up references and connects pieces of information across the public internet in ways not readily apparent to a human reader.

## The deep research initiative

Four slices, built in sequence. Each ships on its own. `TODO.md` places slice 1 in the High tier (after the grounding and reliability prerequisites) and slices 2 through 4 in Medium.

1. **Bounded iterative search.** After an initial pass, the agent reads what it found, identifies gaps and threads, and issues one or two more targeted rounds of queries and fetches before final synthesis. A hard cap on extra rounds bounds both the cost to serve and the maintainer's cognitive load.
2. **Cross-source connection pass.** A synthesis step that looks for corroboration, contradiction, and links across sources rather than summarizing each in isolation. This is the product's distinctive value, and its highest risk: every asserted connection must cite the sources it bridges.
3. **Narrated reasoning.** The page already streams stage events; this upgrades terse stage labels into a readable account of what the agent is doing and why. It turns the wait into the product and shows the user how the profile was built.
4. **Visual payoff.** A map of the subject's key locations and a representative photograph chosen from cited sources, both driven by the structured data the deeper pipeline now produces. They drive word-of-mouth and feed a per-profile social card.

## Governing constraints

**Grounding over reach.** ODIN's promise is profiles synthesized from cited sources. A large language model is superb at inventing plausible, false connections, so the cross-source connection step is the single highest fabrication risk in the product. Reliable citations and a no-source guardrail are hard prerequisites for depth: a connection without its supporting citations does not ship.

**Bounded cost.** A fast-profile query already costs five Claude calls (two on the larger Sonnet model) plus three to five search-API calls. Deep mode multiplies that. Bounded rounds, aggressive caching, and the opt-in gate keep per-query cost in check so depth does not threaten sustainability.

## Non-goals

- Replacing the fast profile. Deep research extends ODIN; it does not become the only path.
- Unbounded agentic loops. Depth is always capped.
- Growth pursued at the expense of trust. A broken citation does more damage than a missed visitor.
