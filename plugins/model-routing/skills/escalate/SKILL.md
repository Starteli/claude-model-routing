---
name: escalate
description: Get a stronger model's answer to one hard question without switching this session's model. Claude writes a self-contained brief and hands it to the deep-thinker subagent, which runs on Opus by default.
argument-hint: "<the question> [with fable]"
disable-model-invocation: true
---

Escalate this to the `deep-thinker` subagent (it may be listed as `model-routing:deep-thinker`): $ARGUMENTS

It won't see this conversation, so write it a brief that stands on its own, in under 400 words:
- the goal and the exact question
- relevant file paths with line numbers, so it can read the code itself
- what has been tried or ruled out, and the evidence
- constraints and decisions that are already settled
- the form of answer you need

Don't paste long code or the conversation history; it can read files. If the user asked for a specific model (for example "with fable"), pass it as the subagent's `model`.

When it returns, give the user its recommendation in a few lines, and say whether you agree and why.
