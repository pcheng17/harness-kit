# Harness Kit

This repository owns shared agent and skill content plus adapters that deploy it to supported harnesses.

- Keep authored content under `content/`; add harness-specific assets only when an asset is genuinely harness-specific.
- Never edit `.generated/`; it is deterministic build output.
- Run `uv run harness-kit check` before applying changes.
- Use `uv run harness-kit preview` before deployment and `uv run harness-kit install` to mutate harness state.
- Do not overwrite unmanaged files or symlinks.
