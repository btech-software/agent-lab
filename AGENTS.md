# AGENTS.md

This file is the vendor-neutral coordination contract for AI tooling in this repository.

## Source of Truth

This file is the canonical, vendor-neutral source of truth for shared behavior, domain knowledge, and coordination policy in this repository.

Vendor-specific directories are adapters derived from it, never the source of truth:
- `.claude/CLAUDE.md` — Claude Code adapter; MUST defer to this file.
- `.claude/skills/*/SKILL.md` — tool-scoped skill implementations of shared intent declared here.
- `.mcp.json` — shared MCP server configuration.

Adapters MUST NOT redefine shared rules. Tool-local files such as `.claude/settings.local.json` are not part of the shared contract.

## Cross-Tool Rules

- Keep shared behavior and domain knowledge in this file. Adapters reference it; they do not restate it.
- Treat vendor-specific directories such as `.codex/` as generated or adapter layers.
- Use progressive context loading. Do not preload every skill or specialty document by default.
- When the user asks for a specific specialty such as `quant`, `seo`, `software-engineering`, or `quaks-generator`, load only the matching adapter context for the active tool.
- If the user uses slash-like syntax such as `/quant`, interpret that as an intent to activate the corresponding specialty, even if the current CLI does not support custom slash commands natively.
- Prefer the active tool's native mechanisms for scoped instructions, custom agents, prompts, or subagents instead of forcing another vendor's UX model.

## Subagent Orchestration

Cap concurrent subagents at **4 per fan-out wave**. This is a hard limit, counted across nested subagents; excess work MUST queue into a later wave instead of raising the cap.

Rationale: beyond four parallel workers, slices stop being independently verifiable — merge conflicts, duplicated context, and review load grow faster than throughput.

Rules:

- Spawn only for genuinely independent slices: disjoint files, no shared mutable state, no sequential dependency. A shared prerequisite MUST be resolved inline or split into sequenced waves.
- Prefer 2-3 subagents. Do the work in-session when it is single-file, trivial, or needs conversation context the subagent cannot see.
- NEVER fan out for exploration that one or two reads can answer.
- Assign one integration owner per shared file. Sibling subagents MUST NOT edit the same file.
- Give every subagent its complete slice: target files, interfaces, constraints, and acceptance check. Subagents do not inherit this conversation.
- Dispatch all independent tasks in one batch; NEVER spawn-wait-spawn.
- Collect results once. NEVER poll.
- A subagent MAY spawn its own workers only when its slice requires it; nested fan-out counts against the same cap of 4.
- Run build, lint, and tests once after the wave, not per subagent.
- If a tool exposes a max-concurrency setting, set it to 4. If it does not, enforce the cap by dispatching in waves.

## Reference Implementations

Adapters MUST read this file first and defer to it. Use the adapter that matches the current tool for tool-specific mechanics only:

- Claude Code:
  Read `AGENTS.md`, then `.claude/CLAUDE.md` for Claude Code mechanics.
  Treat `.claude/skills/*/SKILL.md` as the skill system implementing the shared intent declared here.

## Adapter Policy

- Root `AGENTS.md` is canonical. Adapters are derived from it and MUST reference it rather than restating shared rules.
- Tool-specific behavior belongs in the matching adapter directory, limited to mechanics, defaults, and native surface mapping.
- If a tool cannot support a feature directly, approximate it with the closest native mechanism instead of copying another vendor's surface API.
- After updating shared intent in this file, propagate the change to every adapter that depends on it.
- Precedence on conflict: direct user instructions override this file; this file overrides adapter files. An adapter MAY add tool-specific mechanics but MUST NOT relax the cap of 4 or contradict the cross-tool rules.

## Project Overview

Agent-Lab is a cloud-native LLM Agent Development and Testing Toolkit built with Python 3.12, FastAPI, LangChain/LangGraph, and PostgreSQL. It provides a platform for building, testing, and deploying autonomous agents and multi-agent systems.

- `/software-engineering` — Architecture, common commands (build, test, lint), and code conventions.

## General Guidelines

1. Before writing any code, describe your approach and wait for approval.
2. If the requirements are ambiguous, ask clarifying questions before writing any code.
3. After writing any code, list the edge cases and suggest test cases to cover them.
4. If a task requires changes to more than 3 files, stop and break it into smaller tasks first.
5. When there is a bug, start by writing a test that reproduces it, then fix it until the test passes.
6. Every time the user corrects you, reflect on what you did wrong and form a plan to never repeat that mistake.

## Behavioral Guidelines

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: every changed line traces directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

## Synchronization with downstream projects

Agent-Lab is the **generic base** for downstream reference implementations. Keep this boundary:

- **Only generic, reusable features belong here.** Never add a downstream project's specialized code: product-specific agent types, frontends, domain services (e.g. markets/waitlist), domain MCP tools/schemas/exceptions, or product skills.
- **Generic improvements flow upstream into Agent-Lab.** When a downstream reference implementation carries a newer generic solution (auth, MCP server/transport, shared schemas, infrastructure), port it here so Agent-Lab stays canonical for generic code. Keep generic capabilities even if a downstream project dropped them in favor of product-specific ones.
- Files like `agent_lab/core/container.py`, `agent_lab/services/agent_types/registry.py`, and the MCP server `instructions` enumerate concrete implementations and will legitimately differ from any downstream fork.
