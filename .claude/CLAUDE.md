# CLAUDE.md

Claude Code adapter for this repository.

`AGENTS.md` at the repository root is the canonical source of truth for shared behavior, engineering guidelines, and coordination policy. Read it first and follow it. This file MUST NOT restate shared rules; it adds only Claude Code mechanics.

## Claude Code Mechanics

- Skills: `.claude/skills/*/SKILL.md` implement the shared intent declared in `AGENTS.md`.
- Subagents: use the Task tool; dispatch at most 4 concurrently, batched in a single call for independent slices. See `AGENTS.md` § Subagent Orchestration.
- Tool-local settings: `.claude/settings.local.json` is not part of the shared contract.
