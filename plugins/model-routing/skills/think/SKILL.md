---
name: think
description: "Runs one hard question on this session's model at high effort in a fresh context. Argument: a self-contained brief (goal, question, paths, tried)."
user-invocable: false
context: fork
agent: model-routing:deep-thinker
model: inherit
effort: high
background: false
---
Brief from the calling session:

$ARGUMENTS

Answer in the shape your instructions give. If the brief lacks something you need and can't find in the repository, say exactly what is missing.
