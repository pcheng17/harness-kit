---
name: ask-peter
description: Ask which skill or flow fits your situation. A router over the skills in this repo.
disable-model-invocation: true
---

# Ask Peter

You don't remember every skill, so ask.

A **flow** is a path through the skills. Most paths run along one **main flow**, and two **on-ramps** merge onto it. Everything else is standalone, or a vocabulary layer that runs underneath.

## The main flow: idea → ship

The route most work travels. You have an idea and want it built.

1. **`/grill-with-docs`** - sharpen the idea by interview. Start here when you **have a codebase**: it's stateful, retaining what it learns in `GLOSSARY.md` and ADRs. It runs the `/grilling` primitive underneath.
2. **Branch - is this a multi-session build?**
   - **Yes** → **`/to-spec`** (turn the thread into a spec) → **`/to-tickets`** (split the spec into tracer-bullet tickets, each declaring its **blocking edges**). Work the tickets blockers-first, **`/clear`ing context between each one**: start a fresh session per ticket and kick off **`/implement`** by passing it the spec and the single ticket to work on. Each ticket is self-contained, so the last one's context is disposable.
   - **No** → **`/implement`** right here, in the same context window.

   Either way, **`/implement`** builds each ticket by driving **`/tdd`** internally - one red-green slice at a time - then closes out by running **`/code-review`**, a two-axis review (Standards + Spec) of the diff, before committing. Reach for **`/tdd`** on its own when you just want to build a concrete behaviour test-first without a full spec, and **`/code-review`** on its own whenever you want to review a branch or PR against a fixed point.

   When the work goes up as a pull request, **`/pr`** shapes the body: the smallest visual that shows the change, before/after evidence that it works, and a one-way or two-way door call. It's model-invoked, so the agent reaches for it whenever it writes a PR.

3. **`/retro`** closes the loop. After a build, and especially one that went sideways, it looks back over the session and suggests changes to the agent's **environment**, not the code: navigation pointers, automated checks, the coding standards `/code-review` enforces, steering files, tooling. Mechanical mistakes become deterministic checks; judgement calls become coding standards. The next build then starts from a better environment.

### Context hygiene

Keep steps 1-2 in **one unbroken context window** - don't compact or clear until after `/to-tickets` - so the grilling, spec, and tickets all build on the same thinking. Each `/implement` then starts fresh, working from the ticket. Run `/retro` in the session it's looking back on, before you clear; after clearing, point it at that session's log instead.

The limit on this is the **[smart zone](https://www.aihero.dev/ai-coding-dictionary/smart-zone)**: the window (~150k tokens on state-of-the-art models) within which the model still reasons sharply. If a session approaches it before `/to-tickets`, don't push on degraded - `/compact` at the nearest phase boundary and carry on (see Phase boundaries).

## On-ramps

A starting situation that generates work, then merges onto the main flow.

- **Bugs and requests piling up** → **`/triage`**. It moves issues through triage roles and produces agent-ready issues, which **`/implement`** later picks up.

  Triage is only for issues **you didn't create** - bug reports, incoming feature requests, anything that arrives raw. Tickets that `/to-tickets` produced are already agent-ready, so **don't triage them**.

- **Something's broken** → **`/diagnosing-bugs`**. For the hard ones: the bug that resists a first glance, the intermittent flake, the regression that crept in between two known-good states. It refuses to theorise until it has a **tight feedback loop** - one command that already goes red on *this* bug - then fixes with a regression test. Once the fix is in, run **`/retro`** in the same session to ask what would have prevented the bug; where the real finding is that there's no good seam to lock it down, that's a job for **`/improve-codebase-architecture`**.

## Codebase health

Not feature work - upkeep.

- **`/improve-codebase-architecture`** - run whenever you have a spare moment to keep the codebase good for agents to operate in. It surfaces **deepening opportunities**; picking one _generates an idea_ you can take into the main flow at `/grill-with-docs`. It's the survey that finds the candidates; **`/codebase-design`** (below) is the bench you design the chosen one on.
- **`/dod`** - data-oriented design for **hot paths**: start from the data and its access patterns, do the back-of-the-envelope cache and memory math, and restructure around the most common case. Reach for it when designing or reviewing performance-critical code (a per-frame system, a physics step, a loop over large N); leave cold code alone.

## Vocabulary underneath

Two model-invoked references that run *beneath* the other skills - each the single source of truth for its vocabulary. Reach for them directly when the **words**, not the process, are the problem; or let the skills above pull them in.

- **`/domain-modeling`** - sharpen the project's *domain* language: challenge a fuzzy term, resolve an overloaded word ("account" doing three jobs), record a hard-to-reverse decision as an ADR. It's the active discipline `/grill-with-docs` drives to keep `GLOSSARY.md` a clean glossary.
- **`/codebase-design`** - the deep-module vocabulary (module, interface, depth, seam, adapter, leverage, locality) for designing a module's *shape*: a lot of behaviour behind a small interface at a clean seam. `/tdd` and `/improve-codebase-architecture` both speak it.

## Phase boundaries

A **phase** is a chunk of work inside a session: the grilling, the implementation, the QA. At the **boundary** between two of them you have five options, and picking between them is the fuzziest decision in this whole map:

- **Continue** - stay put. Costs nothing, loses nothing.
- **`/clear`** (built-in) - empty the window, when nothing here matters to what's next.
- **`/handoff`** - write a portable markdown file. Narrow: only for a **new harness**, a **new directory**, a **colleague**, or forking a side task **mid-phase**. What it buys is portability.
- **Sub-agent** - send a tightly-scoped task to its own window and get a report back.
- **`/compact`** (built-in) - compress this context and carry on from the summary. The **default**, at the bottom of the tree rather than the first reach.

Read [PHASE-BOUNDARIES.md](PHASE-BOUNDARIES.md) for the ordered tree: the five questions, the reasoning behind each branch, and why the primary-source cost makes **Continue** the one to rule out first. Make the decision **at** a boundary; mid-phase, continue or split the rest into sub-agents.

## Pull requests and branches

The steps around a PR once the code is written.

- **`/pr`** - the template for a PR body (see step 2 of the main flow).
- **`/address-pr-comments`** - work through a PR's unresolved review threads with you: discuss every thread and get your decision first, then one commit per thread and a reply linking the commit. It never resolves threads; that's left to the reviewer.
- **`/debug-github-actions`** - pass it a failing GitHub Actions run URL; it finds what actually caused the failure, checks the same job's recent history for flakiness, and reports the root cause.
- **`/resolve-merge-conflict`** - finish an in-progress merge or rebase: read the primary sources behind each side, resolve every hunk preserving both intents where possible, run the project's checks, and complete it.
- **`/cleanup-merged-worktree`** - once the PR is merged, delete its worktree, bring the primary checkout back to an up-to-date `main`, and delete the merged local branch. Local only; it never touches the remote branch.

## Standalone

Off the main flow entirely.

- **`/grilling`** - the interview primitive itself: one question at a time, each with a recommended answer; facts are the agent's job and decisions are yours. `/grill-with-docs` is the named way in, and `/triage` and `/improve-codebase-architecture` both run it internally. Reach for it directly when you want the interview with no paper trail - a plan, a design, a piece of writing with no repo under it.
- **`/research`** - delegate reading legwork to a **background agent**: it investigates a question against **primary sources**, then leaves a cited Markdown file in the repo. Keep working while it reads. The file it produces is something to take *into* the main flow at `/grill-with-docs` - research feeds the thinking, it doesn't replace it.
- **`/writing-for-agents`** - the reference for writing documents agents consume: skills, `AGENTS.md` / `CLAUDE.md`, pointed-at docs. Model-invoked, so the agent loads it whenever it creates or edits one; `/retro` loads it too.

## Precondition

**`/setup-pcheng-skills`** - run before your first engineering flow to configure the issue tracker, triage labels, and doc layout the other skills assume. Custom issue trackers also work.
