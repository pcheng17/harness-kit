---
name: code-review
description: Review the changes since a fixed point (commit, branch, tag, merge-base, or PR) along three axes - Standards (does the code follow this repo's documented coding standards?), Spec (does the code match what the originating ticket/spec asked for?), and Correctness (does the code work?). Runs each axis in a parallel sub-agent, verifies the findings, and reports the axes side by side. Use when the user wants to review a branch, a PR, work-in-progress changes, or asks to "review since X".
---

Three-axis review of the diff between the working state and a fixed point:

- **Standards** - does the code conform to this repo's documented coding standards?
- **Spec** - does the code faithfully implement the originating ticket / spec?
- **Correctness** - does the code work: no bugs, unhandled failures, or security holes?

Each axis runs as a **parallel sub-agent** so they don't pollute each other's context, a fresh verifier then tries to refute each axis's findings, and this skill aggregates what survives. A repo can add a **verification gate** (build, tests, coverage) through its review addendum; see step 3.

## Process

### 1. Pin the fixed point

Run `git fetch` first so remote refs are current, then resolve the fixed point from what the user said:

- **A ref** (commit SHA, branch, tag, `main`, `HEAD~5`) - use it as given.
- **A PR/MR** (number or link) - look up its base branch, head branch, and body (`gh pr view <n> --json baseRefName,headRefName,body` on GitHub). The fixed point is `origin/<base>`; if the current branch isn't the head branch, check it out first (`gh pr checkout <n>`), stopping if the working tree has uncommitted changes.
- **Nothing** - if the current branch has an open PR/MR, treat it as named and use the bullet above; otherwise use the remote default branch (`git symbolic-ref --short refs/remotes/origin/HEAD`). State the choice in the report.

Then choose the diff command:

- **Clean working tree** (`git status --porcelain` empty): `git diff <fixed-point>...HEAD` (three-dot, so the comparison is against the merge-base).
- **Dirty working tree**: `git diff $(git merge-base <fixed-point> HEAD)`, which adds staged and unstaged changes to the committed ones. List untracked files with `git ls-files --others --exclude-standard` beside the diff command so reviewers read them whole. Note in the report that uncommitted work was included.

Also note the list of commits via `git log <fixed-point>..HEAD --oneline`.

Before going further, confirm the fixed point resolves (`git rev-parse <fixed-point>`) and the chosen diff (plus untracked files) is non-empty. A bad ref or empty diff should fail here - not inside parallel sub-agents.

Set the **word cap** from the diff's size (`--shortstat` on the chosen diff command): 400 words per reviewer, 800 when insertions plus deletions exceed 1,000.

### 2. Identify the spec source

Look for the originating spec, in this order:

1. Issue references in the commit messages or PR body (`#123`, `Closes #45`, GitLab `!67`, Linear `ENG-123`, etc.) - fetch via the workflow in `docs/agents/issue-tracker.md`. If that file is missing, tell the user to run `/setup-pcheng-skills` and carry on down this list.
2. A path the user passed as an argument.
3. A spec file under `docs/`, `specs/`, or `.scratch/` matching the branch name or feature.
4. If nothing is found, ask the user where the spec is. If they say there isn't one, the **Spec** sub-agent will skip and report "no spec available".

When step 1 resolved a PR/MR (named or defaulted), also fetch its existing review threads, resolved and unresolved, with the mechanics in `../address-pr-comments/REVIEW-THREADS.md` (relative to this skill's folder); resolve the host it needs as step 0 of `../address-pr-comments/SKILL.md` does. Every reviewer brief gets them, so points reviewers already raised are not reported again.

### 3. Identify the standards sources

Anything in the repo that documents how code should be written, such as `CODING_STANDARDS.md` or `CONTRIBUTING.md`.

If `docs/agents/code-review.md` exists, it is the repo's **review addendum**: per-repo input this skill cannot infer (architecture docs, language-specific lowered-bar moves, deterministic checks, build and test commands). Read it and apply each section it has:

- **Standards sources** - add the listed files to the standards sources.
- **Lowered-bar patterns** - append them to the lowered-bar check below.
- **Mechanical checks** - run the listed command(s) now, before spawning anything, with the fixed point from step 1 as the argument. Paste every line of stdout into the Standards brief verbatim so the sub-agent reports it rather than re-deriving it. Lines are hard findings unless the addendum marks a class of them as judgement calls. If a command fails to run (a bad argument or missing tool, as opposed to reporting findings), stop and report that instead of reviewing.
- **Reviewer brief** - append it to every reviewer brief: what this repo's maintainer weights most.
- **Verification** - run in step 4 as an extra sub-agent.

A missing addendum is fine: the repo gets the generic review.

On top of whatever the repo documents, the Standards axis always carries the **smell baseline** below - a fixed set of Fowler code smells (_Refactoring_, ch.3) that applies even when a repo documents nothing. Two rules bind it:

- **The repo overrides.** A documented repo standard always wins; where it endorses something the baseline would flag, suppress the smell.
- **Always a judgement call.** Each smell is a labelled heuristic ("possible Feature Envy"), never a hard violation - and, like any standard here, skip anything tooling already enforces.

Each smell reads *what it is* → *how to fix*; match it against the diff:

- **Mysterious Name** - a function, variable, or type whose name doesn't reveal what it does or holds. → rename it; if no honest name comes, the design's murky.
- **Duplicated Code** - the same logic shape appears in more than one hunk or file in the change. → extract the shared shape, call it from both.
- **Feature Envy** - a method that reaches into another object's data more than its own. → move the method onto the data it envies.
- **Data Clumps** - the same few fields or params keep travelling together (a type wanting to be born). → bundle them into one type, pass that.
- **Primitive Obsession** - a primitive or string standing in for a domain concept that deserves its own type. → give the concept its own small type.
- **Repeated Switches** - the same `switch`/`if`-cascade on the same type recurs across the change. → replace with polymorphism, or one map both sites share.
- **Shotgun Surgery** - one logical change forces scattered edits across many files in the diff. → gather what changes together into one module.
- **Divergent Change** - one file or module is edited for several unrelated reasons. → split so each module changes for one reason.
- **Speculative Generality** - abstraction, parameters, or hooks added for needs the spec doesn't have. → delete it; inline back until a real need shows.
- **Message Chains** - long `a.b().c().d()` navigation the caller shouldn't depend on. → hide the walk behind one method on the first object.
- **Middle Man** - a class or function that mostly just delegates onward. → cut it, call the real target direct.
- **Refused Bequest** - a subclass or implementer that ignores or overrides most of what it inherits. → drop the inheritance, use composition.

The Standards axis also carries the **lowered-bar check**. An agent facing a red check tends to take the cheapest road to green, so flag each of these the diff introduces as a hard finding, even where tooling would otherwise catch it:

- **Threshold moved** - a coverage or performance budget lowered, a lint rule or severity relaxed, a check dropped from CI.
- **Test weakened** - `.skip`/`xfail` added, a test file deleted, assertions removed from a test that stayed.
- **Checker silenced** - a new suppression (`@ts-ignore`, `eslint-disable`, `# noqa`, `# type: ignore`, `istanbul ignore`, `nosemgrep`).
- **Work unfinished** - a stub that throws, an empty `catch`, a `TODO` where the implementation should be.

### 4. Spawn the sub-agents in parallel

Spawn every sub-agent (Standards, Spec, Correctness, and Verification when the addendum calls for it) in the same turn so they run concurrently, not one after the other.

Give each reviewer the diff command, the commit list, the untracked-file list, and its sources, and tell it to read the full touched files and their callers wherever a finding depends on code outside the hunk. Never pass the author's account of the work: a reviewer handed conclusions tends to validate them.

Every reviewer brief also carries these shared rules:

- The existing PR/MR review threads from step 2, if any, with: "Skip any point these threads already raise."
- The addendum's Reviewer brief, if any.
- "Cite every finding's location as `path:line`; a requirement missing from the code cites its spec line instead, and mechanical-check lines stay as-is. Rank findings most severe first. Stay under <word cap> words; if the cap forces you to drop findings, end with how many lower-severity ones you left out." (Fill in the word cap from step 1.)

**Standards sub-agent prompt** - include:

- The list of standards-source files you found in step 3, **plus the smell baseline and lowered-bar check from step 3** pasted in full, with the addendum's lowered-bar patterns appended - the sub-agent has no other access to it.
- The mechanical-check output from the addendum, if any, with the addendum's note on which lines are hard and which are judgement calls.
- The brief: "Report (a) every place the diff violates a documented standard: cite the standard (file + the rule); (b) any baseline smell you spot: name it and quote the hunk; (c) every lowered-bar move: name it and quote the hunk; and (d) each mechanical-check line, repeated as-is. Distinguish hard violations from judgement calls - documented-standard breaches can be hard, baseline smells are always judgement calls, lowered-bar moves are always hard, and a documented repo standard overrides the baseline. Skip anything tooling enforces, except lowered-bar moves."

**Spec sub-agent prompt** - include:

- The path or fetched contents of the spec.
- The brief: "Report: (a) requirements the spec asked for that are missing or partial; (b) behaviour in the diff that wasn't asked for (scope creep); (c) requirements that look implemented but where the implementation looks wrong. Quote the spec line for each finding."

If the spec is missing, skip the Spec sub-agent and note this in the final report.

**Correctness sub-agent prompt** - include:

- The brief: "Find bugs the diff introduces: wrong logic, off-by-one, unhandled errors or nil/empty cases, races, resource leaks, broken callers, security holes. For each, give a concrete failure scenario - the input or state, and the wrong result or crash it produces. Report only defects with such a scenario; leave style and spec fidelity to the other reviewers."

**Verification sub-agent** - only when the addendum has a Verification section. Include:

- The addendum's Verification section in full, and the diff command.
- The brief: "Run each command in order from the repository root. Report pass or fail per command; on a failure, quote the first relevant lines of output and stop. Facts only, no review commentary. Under 200 words."

### 5. Verify the findings

Spawn one fresh verifier per axis that returned findings, all in the same turn. Give each the diff command, the untracked-file list, that axis's sources (the spec for Spec, the standards files for Standards), and the axis's findings - not the reviewer's reasoning beyond each finding itself. Standards findings that are judgement calls and mechanical-check lines go through unverified; send only the rest.

The brief: "Try to disprove each finding against the actual code: read the cited lines and whatever they depend on. Return a verdict per finding: **confirmed** (you could not disprove it), **refuted** (quote the code that disproves it), or **unclear** (say what you couldn't settle). Stay under <word cap> words." (The same cap as the reviewers.)

Verification is done when every sent finding has a verdict. Drop refuted findings, mark unclear ones as **disputed**, and keep confirmed ones as reported.

### 6. Aggregate

Present the reports under `## Standards`, `## Spec`, and `## Correctness` headings, verbatim or lightly cleaned, with step 5's verdicts applied. Do **not** merge or rerank findings across axes - the axes are deliberately separate (see _Why separate axes_). When the verification sub-agent ran, add its report under `## Verification`: it is a gate, not another axis - it states what ran and what failed, and carries no judgement to rerank.

End with a one-line summary: total findings per axis (and how many step 5 refuted), the worst issue _within each axis_ (if any), and whether verification passed when it ran. Don't pick a single winner across axes - that's the reranking the separation exists to prevent.

## Why separate axes

A change can pass one axis and fail another:

- Code that follows every standard but implements the wrong thing → **Standards pass, Spec fail.**
- Code that does exactly what the spec asked but breaks the project's conventions → **Spec pass, Standards fail.**
- Code that is idiomatic and on-spec but crashes on an empty input → **Standards and Spec pass, Correctness fail.**

Reporting them separately stops one axis from masking another.
