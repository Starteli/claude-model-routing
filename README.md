# model-routing

A Claude Code plugin that makes model switching cheap.

## The problem

Each model has its own prompt cache. When you run `/model` mid-session, the new model re-reads the whole conversation with no cache hits, even though nothing changed. Late in a long session that's the most expensive request you'll make.

Example: a 150K-token session on Sonnet 5.5, on a subscription (1-hour cache, so writes cost 2x input):

| What you do | What the next request costs (list price) |
|---|---|
| Keep going on Sonnet | 150K cached reads × $0.10/M ≈ **$0.015** |
| `/model opus` | 150K uncached writes × $8/M ≈ **$1.20**, about 80x a normal turn |
| `/handoff` → `/clear` → `/model opus` | Opus reads only the fixed part (system prompt, tools, CLAUDE.md) plus a ~1K handoff. At ~25K that's ≈ **$0.21** |
| `/escalate <question>` (stay on Sonnet) | An Opus subagent reads a short brief and the files it needs. Your Sonnet cache is untouched |

The fixed part gets re-read on any switch, so the savings come from dropping the conversation history. To see your fixed part, check a fresh session's first turn. MCP servers make it bigger.

On a subscription the dollar figures are only estimates. Your plan meters usage its own way, but the token math is the same.

## What it adds

**`/handoff [model]`** writes `.handoff/LATEST.md`: goal, status, decisions with their reasons, key files, commands, gotchas and next steps, in under ~800 words. It archives a copy, records which transcript it came from, and keeps `.handoff/` out of git through `.git/info/exclude`, so it never touches your `.gitignore`. Then you run `/clear` and `/model <name>`, and the handoff loads automatically. The file is plain markdown, so Codex or any other agent can read it too.

**A switch guard (`PreModelSwitch` hook).** When a `/model` would throw away a warm cache on a big context, it asks first. The prompt shows the token count and estimated cost, plus the cheaper path. Cheap switches go straight through without Claude Code's usual confirmation: small context, a cache that's already cold, or a target as cheap as Haiku.

**A resume tip.** If you resume a big session after the cache has expired, the next message re-reads everything anyway. That's the moment to switch models for free, and it tells you so.

**Subagents that route work without switching your session:**

| Agent | Model | Use |
|---|---|---|
| `model-routing:deep-thinker` | Opus | Hard design or debugging question when you're on a smaller model. Called with `/escalate <question>` |
| `model-routing:implementer` | Sonnet | A settled, multi-file plan to carry out |
| `model-routing:recall` | Haiku | Pull a specific detail out of old handoffs and transcripts, returning only excerpts instead of re-reading them |

Each subagent starts with an empty context, so it never re-reads your conversation, and your main cache stays warm. A short note added at session start tells Claude to route this way instead of suggesting `/model`.

**Two helpers on PATH while the plugin is on:** `handoff-finalize`, which the skill calls, and `transcript-grep "<regex>" [--tools] [--all]`, which searches past transcripts and prints short excerpts.

## Install

You need Claude Code 2.1.251 or later (for `PreModelSwitch`) and `python3` on PATH.

From a local copy:

```bash
claude plugin marketplace add /path/to/claude-model-routing
```

```bash
claude plugin install model-routing@claude-routing
```

From GitHub, once it's pushed:

```bash
claude plugin marketplace add <owner>/claude-model-routing
```

```bash
claude plugin install model-routing@claude-routing
```

It costs about 430 tokens always-on (skill and agent descriptions) plus about 170 for the session-start note.

## Tuning

Set these in the `env` block of `~/.claude/settings.json`:

| Variable | Default | Meaning |
|---|---|---|
| `ROUTING_ASK_TOKENS` | `40000` | Ask before a switch that re-sends at least this many tokens |
| `ROUTING_ASK_USD` | `0.10` | ...and whose estimated re-cache cost is at least this much |
| `ROUTING_FAST_SWITCH` | `1` | `0` keeps Claude Code's own confirmation on cheap switches |
| `ROUTING_POLICY` | `1` | `0` drops the session-start routing note |
| `ROUTING_HANDOFF_DIR` | `.handoff` | Where handoffs live, relative to the project |
| `ROUTING_HANDOFF_LOAD_MIN` | `60` | After `/clear`, load the full handoff only if it's younger than this. Older handoffs (up to 24h) get a one-line pointer instead |

To put an agent on a different model, edit its `model:` line. For example, set `deep-thinker` to `fable` for the hardest questions.

## Things that quietly cost a full re-read

- **A `model:` field on a normal skill or slash command.** It switches the main session for one turn, which means one uncached re-read going in and another coming back. Use `context: fork` together with `model:`, or a subagent.
- **`opusplan`.** Every plan-mode toggle is a model switch with a fresh cache. That's fine early in a session and expensive late.
- **Changing effort mid-session** on older models.
- **Switching back and forth.** Each model keeps its own cache for one TTL, so a quick round trip partly survives. A long detour doesn't.
