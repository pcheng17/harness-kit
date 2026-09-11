# Data-Oriented Design — Principles from the Talk

Distilled notes on Mike Acton's CppCon 2014 keynote "Data-Oriented Design and C++"
([youtu.be/rX0ItVEVjHc](https://youtu.be/rX0ItVEVjHc)). Acton was engine director at
Insomniac Games (Ratchet & Clank, Sunset Overdrive) — hard ship dates, soft-realtime
frames of 16/33 ms, budgets reasoned about in microseconds. These are paraphrased
notes, not a transcript.

## First principles

- The purpose of all programs, and all parts of programs, is to transform data from
  one form to another. That's a physical fact, not a belief.
- If you don't understand the data, you don't understand the problem. You understand
  a problem better by understanding its data.
- Different data ⇒ different problem ⇒ different solution. You cannot make a problem
  simpler than it actually is.
- If you can't reason about the cost of solving a problem, you don't understand it.
  If you don't understand the hardware, you can't reason about the cost.
- Everything is a data problem — including usability, maintenance, and debuggability.
- Solving problems you probably don't have creates problems you definitely do.
  ("Future-proofing" is a trap: no code survives every imaginable future platform.)
- Rules of thumb: where there's one, there are many (look along the time axis);
  solve the most common case first, not the most generic; keep context — the more
  constraints you keep, the better the solution can be.
- Software is real engineering on real hardware solving a real problem — it does not
  run in a "magic fairy ether."

## The three big lies (of mainstream C++/OO culture)

1. **"Software is a platform."** Hardware is the platform. Different hardware demands
   different solutions; reality isn't a hack you're forced to tolerate — reality *is*
   the problem.
2. **"Code should model the world."** World-modeling conflates two different things:
   maintenance of data access (fine) and understanding of the data's properties
   (essential, and hidden by the model). Real-world similarity is superficial: a
   static chair, a physics chair, and a breakable chair share almost nothing in how
   their data is transformed. World modeling is "engineering by analogy" and leads
   to monolithic structures gluing together unrelated transforms.
3. **"Code is more important than data."** The programmer's job is not writing code;
   code is the tool. The job is transforming data — correctly, quickly, maintainably.
   Only write code with direct, provable value for the transform at hand.

Symptoms these lies cause: poor performance, poor concurrency, poor optimizability,
poor stability, poor testability — then layers of infrastructure to fight the
self-inflicted problems.

## The cost model

Latency reference points (order-of-magnitude, x64-class):

| Operation | Cycles |
|---|---|
| Register | ~0 |
| L1 hit | ~3 |
| L2 hit | ~20 |
| Main RAM | ~200+ |
| sqrt (the "expensive" instruction) | ~15–30 |
| Transcendentals (worst instructions) | ~100 |

The punchline: one RAM access outweighs the "scary" math by an order of magnitude.
In a typical scalar member-function update, L2 misses vs. actual work is roughly
10:1 — **the compiler can only reason about that ~10%** (instruction selection,
registers). The other ~90% — memory layout and access order — is the programmer's
job. The compiler is a tool, not a magic wand, and even trivially foldable code
(a bool test in a loop calling a helper) routinely defeats real compilers unless
you hoist invariant reads yourself.

## Worked examples from the talk

### Dictionary lookup

Storing key–value pairs interleaved matches the programmer's mental model ("they're
associated"), but the *actual* dominant operation is scanning keys; the value is
needed on only one hit. Interleaving drags every value through cache to be thrown
away. Store keys packed together, values in a parallel table indexed on hit: cache
fills with what's statistically needed.

### Packing a hot update

A monolithic game object (position, velocity, name, model pointer, misc fields)
updated one at a time wastes ~56–60 of every 64-byte line. Restructure: an input
struct of just the fields read (velocity + factor), an output array of just the
field written, processed 32 at a time → 6 input lines + 2 output lines, 100%
utilized, streaming prefetch kicks in, ~10× speedup — *just from using the line at
all*. Bonus: the cost of future changes becomes reasonable to estimate.

### Bools in structs

A bool stores one bit in a byte — low information density — and worse, pushes hot
fields onto a second cache line: ~200 extra cycles to read one bit. Bools are also
"last-minute decision making": a per-element branch the caller usually could have
decided once. Measure information density cheaply: print the value stream over many
frames and compress it; compressed size ≈ real information content. In the talk's
example the read traffic was ~99.9% noise. Fixes: batch the decision (512 bools →
one packed 64-byte read), merge with other transforms that need the same line, or
schedule rare events into future frames' command buffers so intermediate frames
never look at them.

### The Ogre `Node` class teardown

What you can diagnose from a struct definition alone: many interleaved member
variables ⇒ unmanaged reads, ABI-frozen layout, unavoidable dead bytes per line;
seven bools ⇒ ~128 implicit states to reason about in every method; the name
`Node` ⇒ over-generalized, designed one-at-a-time when the common case is a whole
hierarchy; virtual updates ⇒ unmanaged icache; name strings generated in a default
constructor ⇒ work done just to be overwritten (do it offline — hash strings,
precompute; the best code is code that doesn't need to exist).

The refactor pattern: separate states into separate functions taking *lists*
(translate-local(list), translate-world(list), translate-parent-relative(list));
triage by measured call probability × count; split again (roots vs. nodes with
parents — the caller knows which is which); precondition the data into a packed
stream for the dominant case; check work-per-line against ~200 cycles/line before
deciding whether deeper optimization is worth it. Apply recursively.

## Objections, answered (from the Q&A)

- **"I need templates to avoid duplication."** The duplication is usually smaller
  than feared, and codegen (a template is a poor man's text processor) covers the
  real cases.
- **"I target many platforms — I can't know cache sizes."** You target a *finite
  range* of platforms. Know the min, max, and common case of the range; general
  portability across all imaginable hardware is a fool's errand.
- **"Doesn't this hurt maintainability?"** The opposite: separated states mean fewer
  simultaneous states to reason about per function, and packed layouts resist the
  "someone adds a bool in the middle" regression. Well-organized data makes
  maintenance, debugging, and concurrency easier.
- **"How do I fix a big legacy codebase?"** One step at a time. Pick the most common
  transform, dump the data, reason about density and line usage, fix it, expand
  outward. Don't try to do it everywhere at once.
- **"My constraint is developer time, not CPU time."** Acton's answer: performance
  matters to users in every domain (his mindset wouldn't change in business
  software), and the discipline is the same — spend effort where it's actually
  valuable, which you only know by understanding the real constraints.

Insomniac's own house rules, for context: no exceptions, no RTTI, no STL, no
multiple inheritance, frowned-on templates and operator overloading, all memory
allocated up front into per-system sandboxes with custom allocators — every feature
evaluated on whether it helps solve the actual problem on the actual hardware.
