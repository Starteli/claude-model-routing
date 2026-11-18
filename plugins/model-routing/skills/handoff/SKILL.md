---
name: handoff
description: Write a compact handoff of the current work to .handoff/LATEST.md without compacting this conversation, so a fresh session, another tool such as Codex, or a later day can pick it up from a few thousand tokens. Use when the user wants to save the state or pass the work on. For a plain model switch, /compact then /model is enough.
argument-hint: "[target model, e.g. sonnet]"
allowed-tools: Write, Bash(handoff-finalize *)
# No `model:` here on purpose. On a skill without `context: fork`, a model
# override switches the main session for one turn, which costs two full
# uncached re-reads (in and back out).
---

Write a handoff for whoever continues this work: a different model, a fresh session, or another tool such as Codex. They won't see this conversation, only the file.

Write it to `${CLAUDE_PROJECT_DIR}/.handoff/LATEST.md`, replacing any old one, with this structure:

```markdown
# Handoff: <one-line task title>

## Goal
<what we're trying to achieve and what "done" means>

## Status
- Done: ...
- In progress: ...
- Not started: ...

## Decisions
- <decision>, because <reason>. Rejected: <alternative> (<why>)

## Key files
- `path/to/file.ext:LINE`: <its role and current state>

## Commands
<exact build / test / run commands that matter, and their current result>

## Gotchas
<constraints, traps, error messages and values that were expensive to discover>

## Open questions
<anything undecided, and who decides>

## Next steps
1. <first concrete action>
2. ...
```

Rules:
- Stay under about 800 words. This file replaces the whole conversation, so every line has to earn its place.
- Point to `file:line` instead of pasting code. Paste only short snippets the next model can't find by reading the repo.
- Keep exact strings exact: commands, error messages, IDs, numbers.
- Record why each decision was made and what was rejected, so it doesn't get relitigated.
- Leave out the story of how we got here, dead ends that taught nothing, and pleasantries.
- If you're unsure about something, say so in the file.

Then run:

```bash
handoff-finalize "${CLAUDE_PROJECT_DIR}" "${CLAUDE_SESSION_ID}"
```

Finally, tell the user in two or three short lines how big the handoff is (from the script output) and what to do next: run `/clear`, then `/model $ARGUMENTS` (or `/model <name>` if no target was given). The handoff loads by itself after `/clear`. Another tool can read `.handoff/LATEST.md` directly.
