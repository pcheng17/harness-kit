# Session logs

Where each supported harness stores session transcripts, one JSONL file per session. Verified against each harness's on-disk layout on the author's machine (and Pi's bundled docs); a path that does not match is a finding to report, not one to guess around. Find the session by its working directory and time first (directory names and file timestamps), then open only the file you need.

## Claude Code (verified)

`~/.claude/projects/<project>/<session-id>.jsonl`

`<project>` is the session's working directory with every `/` and `.` replaced by `-` (for example `/Users/me/git/repo` becomes `-Users-me-git-repo`). A sibling directory named `<session-id>` may hold that session's subagent transcripts.

## Pi (verified)

`~/.pi/agent/sessions/--<path>--/<timestamp>_<session-id>.jsonl` by default, grouped by working directory.

The location moves with `--session-dir`, then `PI_CODING_AGENT_SESSION_DIR`, then the `sessionDir` setting in `~/.pi/agent/settings.json` (or a project's `.pi/settings.json`), in that precedence. A custom `sessionDir` can store sessions flat, without the per-directory grouping. A sibling directory named after a session may hold its subagent artifacts.

## Codex (verified)

`$CODEX_HOME/sessions/<YYYY>/<MM>/<DD>/rollout-<timestamp>-<session-id>.jsonl`, with `CODEX_HOME` defaulting to `~/.codex`.

Files are grouped by date, not by working directory. `$CODEX_HOME/session_index.jsonl` indexes sessions.
