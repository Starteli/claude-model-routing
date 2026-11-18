# model-routing

A Claude Code plugin that makes model switching cheap, and mostly automatic: the expensive model plans, cheaper models execute, and nothing re-reads a long conversation it doesn't need.

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

## Plan on Opus, execute on Sonnet in a fresh chat

Claude Code has this built in, but it's off by default. Run the setup once. It backs up `~/.claude/settings.json` first:

| Command | Effect |
|---|---|
| `/model-routing:setup` | `"model": "opusplan"` (Opus plans, Sonnet executes) plus `"showClearContextOnPlanAccept": true` |
| `/model-routing:setup same` | Only `"showClearContextOnPlanAccept": true`. Plans run on whatever model you're using |

`showClearContextOnPlanAccept` makes plan approval offer **"Yes, clear context"**, which starts a fresh session that carries out just the approved plan.

Then, for a bigger task:

1. Press Shift+Tab to enter plan mode.
2. The plan starts with `Executor: sonnet`. To run this plan on another model, press Ctrl+G and change that line before approving. You can also just say "run this one on Opus" while planning.
3. Pick **"Yes, clear context"**. The plan runs in a fresh session. If the executor isn't the session's model, the whole plan goes to a fresh subagent on the executor model. Either way, nothing re-reads the planning chat.

To change your mind midway, run `/execute opus` (or sonnet or haiku). The rest of the work goes to a fresh subagent on that model, which reads a brief of what's done and what's left instead of the whole session. Switching with `/model` this late would make the new model re-read everything.

The plugin also makes this hold up:

- **While you plan,** Claude is told the plan may be all the executing model sees. So the plan spells out decisions and why, files and lines, steps, and how to verify each one.
- **If you approve without clearing,** Claude follows the `Executor` line: it does the work itself if it is that model, and hands it to subagents on that model if not.
- **If entering plan mode re-sends a big conversation to Opus,** you're told what it cost, and that running `/compact` first keeps it small. Claude Code makes this switch itself, so it can't be stopped beforehand.

What a model choice costs:

- **Opus doing the work** costs about twice what Sonnet does per token. You pay that whenever you choose Opus.
- **The switch itself** is close to free while the chat is small: at the start, right after "Yes, clear context", right after `/compact`, and for every subagent. Later in a session, the new model re-reads everything, unless you hand off with `/execute <model>`.

## When it matters

- **Picking a model when a session starts** is free. There's nothing to re-read yet.
- **Switching mid-session** is the expensive moment. The plugin catches it for you.
- **Coming back to an old session** after a break: the cache has expired, so the next message re-reads everything whichever model you use. That makes it the free moment to switch, and the plugin tells you so.

## Switching models mid-session

Type two commands:

1. `/compact`
2. `/model sonnet` (or whichever model you want)

If you forget and type `/model` first, the guard stops you. It shows what the switch would cost and these same steps.

For most work you don't switch at all. Claude sends pieces of work to other models through subagents on its own:

| Agent | Model | Use |
|---|---|---|
| `model-routing:deep-thinker` | Opus | Hard design or debugging question when you're on a smaller model. Ask for it with `/escalate <question>` |
| `model-routing:implementer` | Sonnet, or whichever model you pick | A settled plan, or the rest of one, carried out chunk by chunk. Run with `/execute [model]` |
| `model-routing:recall` | Haiku | Pull a specific detail out of old handoffs and transcripts, returning only excerpts instead of re-reading them |

Each subagent starts with an empty context, so it never re-reads your conversation, and your main cache stays warm.

To save the state without compacting, for Codex, another session or tomorrow, run `/handoff`. It writes `.handoff/LATEST.md`.

## What runs automatically

| Hook | When | What it does |
|---|---|---|
| `PreModelSwitch` | You type `/model` | Big context and warm cache: asks first, with the cost and the cheaper steps. Cheap switches go through without Claude Code's usual confirmation |
| `PostModelSwitch` | Claude Code switches by itself (plan mode, fallback) | If it was expensive, says so and how to avoid it next time |
| `UserPromptSubmit` | Each message, in plan mode only | Tells Claude to write the plan so it stands alone |
| `PostToolUse` (ExitPlanMode) | Plan approved without clearing | Tells Claude how to execute on a cheaper model |
| `PreCompact` | Any compaction | Makes the summary cover what a new model needs: decisions and why, files, exact commands and errors, next steps |
| `PostCompact` | Any compaction | Tells the guard the context is small now. After a manual `/compact`, also saves the summary to `.handoff/LATEST.md` |
| `SessionStart` | Start, `/clear`, resume, after compaction | Adds a short routing note, loads a handoff written in the last 10 minutes after `/clear`, and gives the resume tip |

Handoffs are kept out of git through `.git/info/exclude`, so your `.gitignore` is never touched. Three helpers sit on PATH while the plugin is on: `handoff-finalize`, `routing-setup`, and `transcript-grep "<regex>" [--tools] [--all]`, which searches past transcripts and prints short excerpts.

## Install

You need Claude Code 2.1.251 or later (for the model-switch hooks) and `python3` on PATH.

1. From a local copy:

```bash
claude plugin marketplace add /path/to/claude-model-routing
```

2. Then:

```bash
claude plugin install model-routing@claude-routing
```

3. In Claude Code, run `/model-routing:setup` once, or `/model-routing:setup same` to keep your own model for executing.

From GitHub, once it's pushed, step 1 becomes `claude plugin marketplace add <owner>/claude-model-routing`.

It adds roughly 800 tokens per session: about 570 for the skill and agent descriptions, plus about 200 for the routing note.

## Tuning

Set these in the `env` block of `~/.claude/settings.json`:

| Variable | Default | Meaning |
|---|---|---|
| `ROUTING_ASK_TOKENS` | `40000` | Ask before a switch that re-sends at least this many tokens |
| `ROUTING_ASK_USD` | `0.10` | ...and whose estimated re-cache cost is at least this much |
| `ROUTING_FAST_SWITCH` | `1` | `0` keeps Claude Code's own confirmation on cheap switches |
| `ROUTING_POLICY` | `1` | `0` drops the routing note |
| `ROUTING_EXECUTE` | `1` | `0` drops the plan-mode and plan-approved notes |
| `ROUTING_COMPACT_FORMAT` | `1` | `0` leaves compaction summaries as Claude Code writes them |
| `ROUTING_SAVE_COMPACT` | `1` | `0` stops saving `/compact` summaries to `.handoff/` |
| `ROUTING_HANDOFF_DIR` | `.handoff` | Where handoffs live, relative to the project |
| `ROUTING_HANDOFF_LOAD_MIN` | `10` | After `/clear`, load the full handoff only if it's younger than this. Older handoffs (up to 24h) get a one-line pointer instead |

To put an agent on a different model, edit its `model:` line. For example, set `deep-thinker` to `fable` for the hardest questions.

## Things that quietly cost a full re-read

- **`/branch` and `/fork`.** They copy the whole conversation, so a cheaper model still re-reads all of it. A subagent, or "Yes, clear context", starts from just the plan.
- **A `model:` field on a normal skill or slash command.** It switches the main session for one turn, which means one uncached re-read going in and another coming back. Use `context: fork` together with `model:`, or a subagent.
- **Entering plan mode under `opusplan` late in a session.** Run `/compact` first.
- **Changing effort mid-session** on older models.
- **Switching back and forth.** Each model keeps its own cache for one TTL, so a quick round trip partly survives. A long detour doesn't.
