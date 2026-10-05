# Skill mechanics

The skill-specific branch of [`writing-for-agents`](SKILL.md): what changes when the document is a skill (frontmatter, the invocation choice, reaching other skills, and router skills). Everything else about writing it is the universal reference in `SKILL.md`.

## Invocation

Two choices, trading the two loads:

- A **model-invoked** skill keeps a `description`, so the agent can fire it autonomously, and other skills can reach it. You can still type its name: model-invocation always _includes_ user reach; a description only ever adds agent discovery, never removes the human's. The description is the skill's top-level context pointer, forced to stay loaded at all times: permanent context load in exchange for discoverability. A model-invoked skill whose content is all reference is also one home for shared reference: another skill can invoke it, so reference needed by several skills lives in one place. Mechanics: omit `disable-model-invocation`, and write a model-facing description carrying the trigger branches (the pointer-writing rules in `SKILL.md` apply in full).
- A **user-invoked** skill strips the description from the agent's reach: only the human typing its name can invoke it, and no other skill can. Zero context load, but it spends cognitive load: you are the index that must remember it exists. Mechanics: set `disable-model-invocation: true` and ship an `agents/openai.yaml` (see below); the `description` becomes human-facing: a one-line summary, trigger lists stripped.

The `disable-model-invocation` field is harness-specific. Claude Code and Pi both honor it (Pi still runs the skill when the user types `/skill:name`). Codex declares the same choice in a per-skill `agents/openai.yaml` (`policy.allow_implicit_invocation: false`) rather than in frontmatter, and ignores the frontmatter field, so every user-invoked skill in this repo also ships that file; `harness-kit check` fails if the two disagree. It also enforces a canonical form for both (unquoted lowercase `true` or `false`), since harnesses read other spellings differently. With it, `codex debug prompt-input` no longer lists the skill to the model.

Pick model-invocation only when the agent must reach the skill on its own, or another skill must. If it only ever fires by hand, make it user-invoked and pay no context load.

Shared reference that two user-invoked skills both need can live in neither: with no descriptions, neither can fire the other. Push it to a plain file outside the skill system: external reference any skill can point at.

## Reaching another skill

When a step needs a model-invoked skill, write: Load the `grilling` skill (on Claude Code, call the Skill tool with "grilling"; elsewhere, read its `SKILL.md`). Only Claude Code has a Skill tool; Pi and Codex list each skill's `SKILL.md` path and load it by reading the file. A bare `/grilling` or "run the `grilling` skill" often fails to load it. A step needing two skills names two loads: Load the `grilling` and `domain-modeling` skills (on Claude Code, call the Skill tool twice, once for each; elsewhere, read each one's `SKILL.md`). (This rule is recorded as an ADR in harness-kit.)

A user-invoked skill can't be loaded this way. When a step depends on one, tell the user to run it: "If not, tell the user to run `/setup-pcheng-skills`." Router prose that names skills for the human to pick from isn't invoking anything, so it keeps `/name` labels.

Ask for a sub-agent as "spawn a sub-agent", not by a harness's tool name (`Agent`, `spawn_agent`).

## Splitting by invocation

The invocation cut of splitting (the sequence cut lives in `SKILL.md`): split off a model-invoked skill when you have a distinct leading word that should trigger it on its own (a trigger word you actually use in your prompts), or another skill must reach it. You pay context load for the new always-loaded description, so that independent reach has to be worth it.

## Router skills

When user-invoked skills multiply past what you can remember, that piled-up cognitive load is cured by a **router skill**: one user-invoked skill that names the others and when to reach for each, so the human has one skill to remember instead of many. It can only hint, never fire them: user-invoked skills have no description, so nothing but the human can reach them.
