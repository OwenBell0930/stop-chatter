---
name: stop-chatter
description: Keep only the user's current requested result after a correction by removing unrequested scope, rejected ideas, correction history, redundant tests, compliance labels, and memory leakage from artifacts. Use when a user retracts, narrows, or replaces a requirement, points out an unrequested addition, or asks to clean final artifacts after a course correction. Do not use merely to shorten ordinary prose.
---

# Stop Chatter

Keep only what the user currently asked for. Make a correction change the working target instead of becoming new content about the old mistake.

## Choose the lightest mode

- **Light mode:** Use for one correction and a small, inspectable output. Keep the target in working context and perform the workflow below without creating transient state files or other workflow artifacts. Create or edit the task's requested artifacts normally.
- **Guarded mode:** Use for long tasks, multiple artifacts, Git changes, repeated regressions, or handoffs. Read [references/protocol.md](references/protocol.md), create the transient state, and run the checker before delivery.

Do not mention Stop Chatter, a compliance mode, or the correction history in the deliverable. A short conversational acknowledgement is enough when one is useful.

## Recompile the current target

After every correction:

1. Rewrite the goal as the current positive outcome.
2. Keep only still-active requirements. A retracted item is deleted, not retained as a negative requirement.
3. Separate meta-constraints such as concise, efficient, or do not overbuild. They shape execution and must not become titles, labels, UI copy, version names, or feature text.
4. Keep explicit exclusions only when absence is itself an active external contract, safety property, or acceptance criterion.

Do not use the raw conversation as the continuing specification after this step.

## Prune the dependency cone

For each retired item, inspect everything it may have created:

- plan and task list;
- implementation and configuration;
- comments and documentation;
- tests and fixtures;
- UI text and user-visible metadata;
- PR title, description, release notes, version labels, and hashes;
- candidate memories or reusable rules.

Delete derivatives that have no independent support in the active target. Do not add a test merely to prove that an unrequested item is absent. Keep a negative test only when an active requirement makes that absence externally observable or safety-critical.

## Trace additions to active requirements

Every changed artifact must map to at least one active requirement. Remove an addition when its only justification is helpfulness, completeness, the earlier mistake, or demonstrating compliance with the correction.

Comments explain non-obvious properties of code that still exists. PR and release text describe the resulting positive state. UI contains user-facing product content, never internal requirements or correction history. Do not add version numbers, immutable-release claims, hashes, or extra ceremony unless the user or release process requires them.

## Keep memory clean

Treat corrections as task-local by default. Persist one only when the user explicitly asks for durable memory or clearly states a stable cross-task preference. Store the positive abstract behavior and scope, not the rejected example.

## Run the guarded check

In guarded mode, keep `.stop-chatter/state.json` transient and out of Git. Initialize it from the installed skill:

```bash
python3 <skill-dir>/scripts/stop_chatter.py init --root .
```

Replace the template values with the active target, path mappings, retired labels and semantic aliases, and meta-instruction leak markers. Set `ready` to `true` only after those values are current. Then check the changed artifacts:

```bash
python3 <skill-dir>/scripts/stop_chatter.py check --root .
```

Fix only reported scope or residue failures, then run the check once more. The checker is deterministic: it cannot infer unlisted semantic aliases or prove that implementation behavior matches the goal. Use the reasoning workflow for those judgments.

After the task ends, remove `.stop-chatter/state.json` unless an active handoff still needs it. A portable cleanup command is `python3 -c 'from pathlib import Path; Path(".stop-chatter/state.json").unlink(missing_ok=True)'`. Standard interpreter and test caches are outside the checker artifact set; do not delete them merely to satisfy this workflow. Never promote the transient retired ledger into memory.

For installation paths and host-specific invocation, read [references/host-setup.md](references/host-setup.md) only when installing or diagnosing discovery.

## Deliver the result

Return the requested artifact or concise completion summary in current-state language. Do not call it a corrected, clean, concise, no-X, or final-state version. Mention removed history only when the user asks for an audit trail or the removal itself is materially relevant to migration, safety, or compatibility.
