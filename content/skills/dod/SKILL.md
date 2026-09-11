---
name: dod
description: Apply data-oriented design (DoD) when designing or reviewing performance-critical code - analyze the data and its access patterns first, reason about cache lines and memory cost with back-of-the-envelope math, and restructure hot paths around the most statistically common case. Use when the user says "data-oriented design", "/dod", "DoD review", "cache-friendly", "SoA vs AoS", "why is this loop slow", or wants a hot path, game/simulation system, or data-heavy transform designed or optimized the Mike Acton way.
---

# Data-Oriented Design

Design and review code by starting from the data, not the code. Distilled from Mike Acton's CppCon 2014 keynote "Data-Oriented Design and C++" ([youtu.be/rX0ItVEVjHc](https://youtu.be/rX0ItVEVjHc)).

The core premise: **the purpose of every program is to transform data from one form to another.** If you don't understand the data - its shape, its volume, its access frequency, its statistical distribution - you don't understand the problem. Code is the tool, not the job; the job is solving the data transformation well on the finite hardware you actually target.

## Reference doc

[PRINCIPLES.md](PRINCIPLES.md) - the talk's full argument distilled: the three big lies, cost numbers, the worked examples (dictionary lookup, bools-in-structs, the Ogre `Node` teardown), and the compiler's real role. Read it when you need the reasoning behind a step, or when the user asks "why".

## When this applies - and when it doesn't

Apply this to **hot paths**: code that runs per-frame, per-request, per-row over large N, or anywhere the user cares about throughput/latency. Do **not** data-orient cold code (config loading, CLI glue, one-shot scripts) - that trades clarity for nothing. If it's unclear whether the code is hot, ask or measure first.

## Procedure

### 1. Understand the data before touching the code

For the transform in question, establish:

- **What are the inputs and outputs?** Actual bytes, actual types, actual sizes - not the class diagram.
- **Where does one exist, are there many?** "Where there's one, there are many" - look along the time axis. The common case is almost never a single object in a vacuum; it's a batch (a hierarchy of nodes, an array of entities, a stream of rows).
- **What is the statistical distribution?** Which branch is taken 99% of the time? Which fields are actually read in the hot loop vs. dragged along cold? Count, profile, or print-and-compress to estimate information density (see PRINCIPLES.md).

If you can't answer these, gather the data first (instrument, log, profile). Don't design from a mental model of the world - design from measured reality.

### 2. Do the back-of-the-envelope cost math

Reason in cache lines, not big-O. Rough numbers for a modern x64-class machine:

| Access | Cost |
|---|---|
| Register / L1 | ~0–3 cycles |
| L2 | ~20 cycles |
| Main RAM | ~200+ cycles |

For the hot loop, estimate:

- **Bytes read per iteration vs. bytes actually used.** A 64-byte line pulled in to read one 4-byte field is ~94% waste. That waste ratio, not the arithmetic, is usually the whole story - an L2 miss costs an order of magnitude more than a square root.
- **Cycles of real work per cache line read.** If work-per-line ≈ cost-per-line-read (~200 cycles), you're balanced; far under it, you're memory-bound and data layout is the lever.

### 3. Restructure the data around the most common case

Solve the statistically common case first, not the most generic one. Standard moves, in the order to try them:

- **Split hot from cold.** Pull the fields the hot transform actually reads into their own packed arrays/structs (SoA over AoS). Keys separate from values; positions separate from names and debug strings.
- **Process in batches sized to cache lines.** Take arrays/counts as arguments, not single objects. Pick batch multiples that fill whole lines with no slack.
- **Hoist decisions out of the loop.** A bool or switch checked per-element inside a hot loop is last-minute decision-making - the caller almost always already knows the answer. Split into separate arrays/functions per state (e.g. roots vs. children) and let the caller dispatch once. Store same-state items together so per-item state flags disappear entirely.
- **Kill bools in hot structs.** One bit occupying a byte, pushing hot fields onto a second cache line, is paying ~200 cycles to read one bit. Turn states into separate lists or bit-packed batch masks.
- **Move work off the hot path in time.** Precompute offline, hash strings at build time, generate code for statically-knowable results, or schedule rare events into a future command buffer instead of re-checking them every frame. The best code is code that doesn't need to run at all.
- **Help the compiler with the 10% it can see.** Hoist invariant reads (especially member variables and globals) into locals outside loops. The compiler reasons about registers and instruction selection - roughly 10% of the problem; memory layout, the other 90%, is yours.

### 4. Verify

- Re-run the back-of-the-envelope math on the new layout: line utilization should approach 100% on the hot inputs/outputs.
- Measure if the stakes warrant it (profiler cache-miss rate on the function is enough - misses × line size vs. bytes actually needed gives the waste directly).
- Sanity-check maintainability: well-organized data with few states is *easier* to reason about, debug, and parallelize, not harder. If the restructure made the code harder to reason about, the split is probably wrong - revisit step 1.

## Reviewing existing code with /dod

When asked to review rather than design: walk the hot structs and loops, and flag - cold fields interleaved with hot ones, bools/state flags in structs, per-element branches the caller could decide, one-at-a-time interfaces where batches are the real case, strings/lookups on the hot path, over-general "node"/"manager" classes hiding access patterns, and virtual dispatch in tight loops (unmanaged icache). For each flag, show the cache-line cost estimate, not just the smell. For a legacy codebase: don't boil the ocean - find the single most common transform, fix that one end-to-end, and expand outward.
