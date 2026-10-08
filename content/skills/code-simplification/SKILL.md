---
name: code-simplification
description: Behaviour-preserving cleanup of a diff. Use after an implementation goes green and before review, or when the user asks to tidy recent changes.
---

Simplify the code changed since a fixed point without changing what it does. Simpler means a reader understands it faster, not fewer lines.

## Process

### 1. Pin the scope

Use the fixed point the caller passed (e.g. `origin/main`); if none was passed, ask. The scope is the non-test code in `git diff <fixed-point>...HEAD`, uncommitted changes, and untracked files (`git status --short`). Code outside that stays as it is; note anything worth changing there for the report.

Record the baseline: run the full test suite, the build, and the linter. The tests must be green to start; if they're red, stop and report.

### 2. Find candidates

Match the scope against:

- The **smell baseline** in step 3 of the `code-review` skill (`../code-review/SKILL.md`, relative to this skill's folder). Read that list; don't run the review.
- Readability signals: nesting 3+ levels deep (→ guard clauses), nested ternaries, boolean flag parameters, dead code and commented-out blocks, comments that restate the code, redundant casts or type assertions.

A documented repo standard overrides both lists.

### 3. Read the fence

Before changing or deleting each candidate, apply **Chesterton's Fence**: say what it's responsible for, what calls it and what it calls, which tests pin its behaviour, and why it was written this way. For code that predates the fixed point, the why comes from `git log -L` or `git blame`; for code new in this change, from the ticket or spec. A candidate whose reason you can't state stays as it is.

### 4. Keep modules deep

Simplify toward **deep modules**, in the `codebase-design` vocabulary:

- The **interface** stays fixed: anything a test or another module calls keeps its interface. An extracted helper is private to the module it came from.
- To remove a layer, apply the **deletion test**: inline a pass-through whose deletion makes complexity vanish; keep one that concentrates complexity for its callers.

### 5. Apply one at a time

For each simplification: make the edit, run the tests covering it, and if they go **red**, undo that edit and move on to the next candidate. Test files, including ones added in this change, stay byte-for-byte unchanged; a simplification that needs a test edit has changed behaviour, so undo it. Error handling, validation, and logging keep their current behaviour.

### 6. Check the whole

Rerun the full test suite, the build, and the linter: tests green, and no build or lint failure the baseline didn't have. Then reread the simplified code end to end and undo any change that reads worse than what it replaced.

### 7. Report

- **Applied**: each simplification, with file and the reason it's simpler.
- **Rejected**: each candidate left alone and why (fence unexplained, went red, would widen an interface).
- **Noticed, not touched**: anything worth changing outside the scope.
