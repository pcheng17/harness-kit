---
name: implement
description: "Implement a piece of work based on a spec or set of tickets."
disable-model-invocation: true
---

Implement the work described by the user in the spec or tickets.

Unless the user explicitly specifies otherwise, all implementation, documentation, testing, and other repository work must be done in a separate git worktree created from `main`. Do not make task changes directly in the primary checkout.

Use /tdd where possible, at pre-agreed seams.

Run single test files regularly, and the full test suite once at the end.

Once done, use /code-review to review the work.
