# model-routing

A Claude Code plugin that shows you which models do the work, keeps Claude Code's model mix on, and makes model switches cheaper.

Three words you will see:

- **Subagent**: a helper Claude starts for one task. It begins with an empty context, so it never re-reads your chat.
- **Model mix**: a row in `/model` that some accounts get. One lead model runs the chat, and a cheaper model runs all subagents.
- **Switching cost**: when you change model mid-chat, the new model re-reads the whole chat without cache. Late in a long chat that is the expensive moment, so the plugin warns you then.

## What you will see

1. **One line when a session starts.** It says how subagents are routed. For example:
   - `Routing on · recall Haiku · build Sonnet · hard Opus` (no model mix: the plugin picks per task)
   - `Model mix on · Opus 5.5 leads · Sonnet 5 runs subagents` (your account's model mix is on)
   - `Subagents forced to Sonnet 5 (set at launch) · /model-routing:status` (something else forces one model)
2. **One line after a turn where subagents ran.** For example: `Routed: 2× Haiku 5.5 (low) | 1× Opus 5.5 fork (high)`. Claude Code hides finished subagents, so this is how you see where work went.
   - The word in brackets is the effort level the subagent was given.
   - `fork` means a side task on your main model (from `/model-routing:escalate`).
3. **A line only when something is wrong.** Each one ends with the fix:

   | You see | It means |
   |---|---|
   | `Old opusplan pin may block your model mix · Fix: /model-routing:setup` | An old setting stops the mix. Run the fix. |
   | `Model mix didn't load in time · /model → "…" row turns it on` | The mix was late at startup. Pick its row in `/model`. |
   | `Model mix blocked by CLAUDE_CODE_SUBAGENT_MODEL · …` | A variable you set stops the mix. Unset it, then restart. |
   | `Mix half-on (main …) · fix: /model → …` | You changed model outside `/model`. Pick the mix row again. |
   | `Mix off after resume · restore: /model → …` | Resuming an old chat turned the mix off. |
   | `model-routing is off: Python 3 not found.` | Install Python 3. |

4. **A question before an expensive `/model` switch.** Late in a long chat, a switch makes the new model re-read everything. You see the cost and a cheaper way: `1) /compact 2) /model <name>`.
5. **`/model-routing:status` any time.** Five short lines: who runs subagents, your main model, runs so far, problems, commands.

You can turn the routine lines off and keep the problem lines: set `ROUTING_QUIET=1` (see Settings).

## Install

You need Claude Code 2.1.332 or later and Python 3. On Windows you also need Git Bash: without it the hooks don't run, and `/model-routing:status`, `setup`, `execute` and `escalate` stop with a shell error.

1. Add the marketplace:

   ```bash
   claude plugin marketplace add Starteli/claude-model-routing
   ```

2. Install the plugin:

   ```bash
   claude plugin install model-routing@claude-routing
   ```

3. Restart Claude Code. You should see the startup line.
4. Run `/model-routing:setup` once. It lists settings that get in the way and fixes only the ones you pick.

**Update later:**

1. Run:

   ```bash
   claude plugin update model-routing@claude-routing
   ```

2. Restart Claude Code.

**Cloud sessions (claude.ai/code):** plugins from your own settings don't load there. Add it at claude.ai/customize/plugins.

## Everyday commands

| Command | What it does |
|---|---|
| `/model-routing:status` | Shows the routing state and any problems. |
| `/model-routing:escalate <question>` | Gets a stronger answer to one hard question without switching your model. |
| `/model-routing:execute [opus\|sonnet\|haiku]` | Hands the agreed plan to fresh subagents, so no model re-reads the chat. |
| `/model-routing:handoff` | Saves the work to `.handoff/LATEST.md`. Then run `/clear`: it loads by itself. |
| `/model-routing:setup` | Run once. Finds and fixes settings that block the mix or routing. |

## If your account has a model mix

A model mix is a row in `/model`: one lead model plus a cheaper model for subagents.

1. **Don't set `CLAUDE_CODE_SUBAGENT_MODEL` or `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` yourself.** Either one blocks the mix. `/model-routing:setup` finds them in settings files; for a shell export, remove it from your shell profile.
2. **Any `/model` choice other than the mix row turns the mix off.** To turn it back on, pick the mix row.
3. **`/config` and Alt+P can leave it half-on** (new main model, old subagent model). The plugin tells you once.
4. **While the mix is on, all subagents use its subagent model.** Only effort still changes per task. `/model-routing:escalate` then runs the hard question on your main model at high effort.
5. **Never start with `claude --agent model-routing:…`.** That turns the mix off.

## Without a model mix

Claude sends work to three helper agents on their own models:

| Agent | Model | Used for |
|---|---|---|
| `model-routing:recall` | Haiku | Finding a detail from past sessions |
| `model-routing:implementer` | Sonnet | Carrying out a settled plan |
| `model-routing:deep-thinker` | Opus | Hard design or debugging questions |

Each one starts with an empty context, so it never re-reads your chat. To use another model for one job, run `/model-routing:execute <opus|sonnet|haiku>`. Editing the plugin's agent files is undone by updates.

## Switching the whole chat to another model

1. Run `/compact`.
2. Run `/model <name>`. If a model mix is on, pick the mix row instead: any other choice turns the mix off.

If you type `/model` first late in a long chat, the plugin asks before the switch and shows the cost.

## Plans

1. Shift+Tab enters plan mode. Claude writes the plan so it stands alone.
2. Without a model mix, the plan starts with `Executor: sonnet`. Change that line before you approve it to run the plan on another model.
3. Pick **Yes, clear context** when you approve, so the plan runs in a fresh chat. `/model-routing:setup` turns that option on.

## Settings

Put these in the `env` block of your settings file.

| Variable | Default | Effect |
|---|---|---|
| `ROUTING_QUIET` | `0` | `1` hides the startup and `Routed:` lines. Problem lines still show. |
| `ROUTING_RECEIPTS` | `1` | `0` hides the `Routed:` line. |
| `ROUTING_MIX_GUARD` | `0` | `1` asks before any `/model` switch that would leave the mix. Claude Code can only ask inside `/model`, so with `1` a change through `/config`, Alt+P or fast mode that would leave the mix is blocked: use `/model` for it. |
| `ROUTING_MIX_CACHE` | `1` | `0` stops reading the cached mix recipe in `~/.claude.json`. |
| `ROUTING_POLICY` | `1` | `0` stops the short routing note to Claude. |
| `ROUTING_EXECUTE` | `1` | `0` stops the plan-mode notes. |
| `ROUTING_ASK_TOKENS` | `40000` | Ask before a switch that re-sends at least this many tokens. |
| `ROUTING_ASK_USD` | `0.10` | ...and costs at least this much. |
| `ROUTING_FAST_SWITCH` | `1` | `0` keeps Claude Code's own confirmation on cheap switches. |
| `ROUTING_HANDOFF_DIR` | `.handoff` | Where handoffs live. |
| `ROUTING_HANDOFF_LOAD_MIN` | `10` | After `/clear`, load the handoff only if it's younger than this (minutes). |
| `ROUTING_SAVE_COMPACT` | `1` | `0` stops saving `/compact` summaries as handoffs. |
| `ROUTING_COMPACT_FORMAT` | `1` | `0` leaves compaction summaries as Claude Code writes them. |

The plugin never sets `CLAUDE_CODE_SUBAGENT_*` or `CLAUDE_CODE_EFFORT_LEVEL`, and never pins a model.

## Upgrading from v1

1. Run `/model-routing:setup`. If v1 pinned `"model": "opusplan"`, it offers to remove it.
2. The `routing-setup` helper is gone. Use `/model-routing:setup`.

## Optional: the advisor tool

Not used by this plugin. Claude Code's experimental advisor tool (`/advisor <model>`) lets cheaper workers ask a stronger model for advice. It isn't available on Bedrock, Agent Platform or Foundry.

## What it costs

About 210 tokens on every request (agent and skill descriptions), plus about 100 tokens for the routing note at the start and after `/clear` or a routing change.
