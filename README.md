# model-routing

A Claude Code plugin that makes model switching cheap, and mostly automatic.

## The problem

Each model has its own prompt cache. When you run `/model` mid-session, the new model re-reads the whole conversation with no cache hits, even though nothing changed. Late in a long session that's the most expensive request you'll make.

Example: a 150K-token session on Sonnet 5.5, on a subscription (1-hour cache, so writes cost 2x input):

| What you do | What the next request costs (list price) |
|---|---|
| Keep going on Sonnet | 150K cached reads × $0.10/M ≈ **$0.015** |
| `/model opus` | 150K uncached writes × $8/M ≈ **$1.20**, about 80x a normal turn |
| `/compact`, then `/model opus` | Opus reads the fixed part (system prompt, tools, CLAUDE.md) plus a ~1–2K summary. At ~25K that's ≈ **$0.21** |
| `/escalate <question>` (stay on Sonnet) | An Opus subagent reads a short brief and the files it needs. Your Sonnet cache is untouched |

The fixed part gets re-read on any switch, so the savings come from dropping the conversation history. To see your fixed part, check a fresh session's first turn. MCP servers make it bigger.

On a subscription the dollar figures are only estimates. Your plan meters usage its own way, but the token math is the same.

## When it matters

- **Picking a model when a session starts** is free. There's nothing to re-read yet.
- **Switching mid-session** is the expensive moment. The plugin catches it for you.
- **Coming back to an old session** after a break: the cache has expired, so the next message re-reads everything whichever model you use. That makes it the free moment to switch, and the plugin tells you so.

The rest of the time there's nothing to do.

## How you use it

**To switch models mid-session**, type two commands:

1. `/compact`
2. `/model sonnet` (or whichever model you want)

If you forget and type `/model` first, the guard stops you. It shows what the switch would cost and these same steps.

**For most work you don't switch at all.** Claude sends pieces of work to other models through subagents on its own:

| Agent | Model | Use |
|---|---|---|
| `model-routing:deep-thinker` | Opus | Hard design or debugging question when you're on a smaller model. Ask for it with `/escalate <question>` |
| `model-routing:implementer` | Sonnet | A settled, multi-file plan to carry out |
| `model-routing:recall` | Haiku | Pull a specific detail out of old handoffs and transcripts, returning only excerpts instead of re-reading them |

Each subagent starts with an empty context, so it never re-reads your conversation, and your main cache stays warm.

**To save the state without compacting**, for Codex, another session or tomorrow, run `/handoff`. It writes `.handoff/LATEST.md`. After `/clear`, a handoff less than an hour old loads by itself.

## What runs automatically

| Hook | When | What it does |
|---|---|---|
| `PreModelSwitch` | You type `/model` | Big context and warm cache: asks first, with the cost and the cheaper steps. Cheap switches go through without Claude Code's usual confirmation |
| `PreCompact` | Any compaction | Makes the summary cover what a new model needs: decisions and why, files, exact commands and errors, next steps |
| `PostCompact` | Any compaction | Tells the guard the context is small now. After a manual `/compact`, also saves the summary to `.handoff/LATEST.md` |
| `SessionStart` | Start, `/clear`, resume, after compaction | Adds a short routing note, loads a fresh handoff after `/clear`, and gives the resume tip |

Handoffs are kept out of git through `.git/info/exclude`, so your `.gitignore` is never touched. Two helpers sit on PATH while the plugin is on: `handoff-finalize`, which `/handoff` uses, and `transcript-grep "<regex>" [--tools] [--all]`, which searches past transcripts and prints short excerpts.

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

It costs about 600 tokens per session: the skill and agent descriptions plus the routing note.

## Tuning

Set these in the `env` block of `~/.claude/settings.json`:

| Variable | Default | Meaning |
|---|---|---|
| `ROUTING_ASK_TOKENS` | `40000` | Ask before a switch that re-sends at least this many tokens |
| `ROUTING_ASK_USD` | `0.10` | ...and whose estimated re-cache cost is at least this much |
| `ROUTING_FAST_SWITCH` | `1` | `0` keeps Claude Code's own confirmation on cheap switches |
| `ROUTING_POLICY` | `1` | `0` drops the routing note |
| `ROUTING_COMPACT_FORMAT` | `1` | `0` leaves compaction summaries as Claude Code writes them |
| `ROUTING_SAVE_COMPACT` | `1` | `0` stops saving `/compact` summaries to `.handoff/` |
| `ROUTING_HANDOFF_DIR` | `.handoff` | Where handoffs live, relative to the project |
| `ROUTING_HANDOFF_LOAD_MIN` | `60` | After `/clear`, load the full handoff only if it's younger than this. Older handoffs (up to 24h) get a one-line pointer instead |

To put an agent on a different model, edit its `model:` line. For example, set `deep-thinker` to `fable` for the hardest questions.

## Things that quietly cost a full re-read

- **A `model:` field on a normal skill or slash command.** It switches the main session for one turn, which means one uncached re-read going in and another coming back. Use `context: fork` together with `model:`, or a subagent.
- **`opusplan`.** Every plan-mode toggle is a model switch with a fresh cache. That's fine early in a session and expensive late.
- **Changing effort mid-session** on older models.
- **Switching back and forth.** Each model keeps its own cache for one TTL, so a quick round trip partly survives. A long detour doesn't.
