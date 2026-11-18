---
name: drawing-workflow
description: Coordinate source-based drawing projects through view mapping, creation, independent checking, issue repair and full review, with per-sheet progress, verified learning and recoverable delivery. Use for multi-sheet or iterative drawing workflows, not generic task management or an automatic fabrication approval.
---

# Drawing Workflow

Use this skill for repeatable plan/elevation drawing work across projects and chats. Ask only for missing inputs that cannot be discovered. Current user instructions govern scope, model choice and presentation.

## Start and route

1. Read [workflow.md](references/workflow.md) and the current project's manifest/state. A new project supplies its own source files, sheet order and output paths; no previous chat or customer folder is required.
2. Use `$elevation-create-and-audit` for source geometry, dimensions, symbols, simplification and actual-export acceptance. Its specialized companion skills handle requested object changes, extraction, standards interpretation or 3D; this workflow does not initiate those scopes on its own.
3. Read the assigned role: [Create](references/roles/create.md), [Check](references/roles/check.md), [Summarize](references/roles/summarize.md) or [Coordinate](references/roles/coordinate.md). Keep creator changes and independent checker reports separate.
4. For bookkeeping, initialization, checkpoints, index or PDF assembly, read [project-state.md](references/project-state.md) and use `scripts/workflow.py`. Technical drawing creation still requires the source and drawing tools; the helper is not a universal drawing engine.

## Working defaults

Use the owner's practical 2 + 1 + 2 profile: two initial detailed-drawing rounds including first creation, one manual issue pass, then two full-review rounds. Track correspondence separately, pass early, and retain truthful limitations. Read the precise counting rules before dispatch.

After every completed independent check, show results and complete Summarize/SKIP before dependent repair or release. Learn through [learning.md](references/learning.md), not through an unverified rule rewrite. Keep project facts local; preserve useful evidence and supersessions.

The coordinator maintains a persistent [to-do register](references/todo-list.md). Capture each new user issue or task before dispatch, preserve its original request and priority, and require evidence before completion. Derive progress views from that register instead of keeping unsynchronized duplicate lists.

Use [delivery.md](references/delivery.md) before publication. Use [preservation.md](references/preservation.md) for cleanup, relocation and restoration. Do not silently reopen old drawings, weaken verification for Fast mode, or claim unavailable setting telemetry.
