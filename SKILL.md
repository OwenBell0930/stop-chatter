---
name: stop-chatter
description: Keep only the user's current requested result after a correction by removing unrequested scope, rejected ideas, correction history, redundant tests, compliance labels, and memory leakage from artifacts. Use when a user retracts, narrows, or replaces a requirement, points out an unrequested addition, or asks to clean final artifacts after a course correction. Do not use merely to shorten ordinary prose.
---

# Stop Chatter

Keep only what the user currently asked for. A correction should change the working target, not become new content about the old mistake.

## Choose the lightest mode

- **Light mode (default):** Use for ordinary corrections and later supplements. Keep the target in working context and follow the rules below. Do not create transient state or other workflow artifacts. Reading this skill or restating the plan in chat is not delivery; change the files.
- **Guarded mode:** Use only when the user explicitly asks for it, or when the same retracted item has already come back and the check scope can be bounded to that residue. Read [references/protocol.md](references/protocol.md) before changing deliverables, initialize once, then run the checker before delivery.

Do not switch to Guarded merely because the task is long, touches Git, or spans multiple files. After this correction finishes, ordinary continuation returns to Light. An explicit unfinished handoff may reuse the same task state; do not write the retired list into durable memory.

Do not mention Stop Chatter, a compliance mode, or the correction history in the deliverable. Keep the conversational completion summary useful: report material changes, checks, and known limits when the user needs them to align on what happened.

## Recompile the current target

After every correction:

1. Rewrite the goal as the current positive outcome.
2. Keep only still-active requirements. A retracted item is deleted, not retained as a negative requirement.
3. Separate meta-constraints such as concise, efficient, or do not overbuild. They shape execution and must not become titles, labels, UI copy, version names, or durable preferences.
4. Keep explicit exclusions only when absence is itself an active external contract, safety property, or acceptance criterion.

Put that rewritten target into the files before removing residue. This round did not mention something ≠ retract it. Retracting one item does not authorize dropping still-active features or cleaning the rest of the project. Do not use the raw conversation as the continuing specification after this step.

## What may be removed

Only explicitly retracted content, and derivatives that visible evidence shows exist solely to serve it, enter the cleanup set. Existing files and the user's prior edits stay by default. Still-valid features, safety properties, and compatibility contracts stay. If the source of a file is unclear, keep it.

After the primary artifact matches the current target, look once for derivatives that exist solely to serve the retired item: commemorative changelog or release notes for this correction, tests whose only job is proving the retracted item is absent, records of the rejected option, and files named after the retired feature. That pass is not a project-wide cleanup.

Ask only when ambiguity blocks delivery. Do not add a confirmation step for every file.

Do not add a test merely to commemorate a correction or to prove that an unrequested item is absent. Keep a negative test only when an active requirement makes that absence externally observable or safety-critical. The checker's own file-operation contract tests may remain.

## Trace this round's file operations

Every file added or modified this round must map to at least one active requirement. Mapping a path as allowed to change does not authorize deleting the whole file. Delete a whole file only when visible task evidence supports that removal.

Comments explain non-obvious properties of code that still exists. PR and release text describe the resulting positive state. UI contains user-facing product content, never internal requirements or correction history. Do not add version numbers, immutable-release claims, hashes, or extra ceremony unless the user or release process requires them.

## Keep memory clean

Treat corrections as task-local by default. Persist one only when the user explicitly asks for durable memory or clearly states a stable cross-task preference. Store the positive abstract behavior and scope, not the rejected example. After edits, scan remaining files—including memory—for the retired item and its aliases in other languages or nearby names; remove those traces only.

## Guarded check

In Guarded mode, initialize before changing deliverables. If valid task state already exists for this root, reuse it; do not overwrite it or reset the start baseline. If the state is invalid or belongs to a different root, stop instead of reusing or replacing it.

```bash
python3 <skill-dir>/scripts/stop_chatter.py init --root .
```

Replace the template values with the current target, the narrowest add/modify paths, exact `must_remove` paths supported by visible evidence, retired labels and aliases, and meta-instruction leak markers. Do not edit the init-captured baseline. Set `ready` to `true` only after those values are current. Then check once:

```bash
python3 <skill-dir>/scripts/stop_chatter.py check --root . --cleanup-state-on-pass
```

On success, this same command removes only `.stop-chatter/state.json`. Do not run a second successful check or a separate cleanup command. Do not delete interpreter caches, test caches, or other user files to “clean state.” On failure, the state is preserved; fix only evidenced scope or residue problems, then rerun at most once.

The checker only reports. It does not delete or restore deliverables, and it does not decide product ownership. A pass means the configured checks passed, not that the implementation is correct or that nothing remains.

If an active handoff still needs the state, omit `--cleanup-state-on-pass` and remove the file when that handoff ends. Never promote the transient retired ledger into memory.

For installation paths and host-specific invocation, read [references/host-setup.md](references/host-setup.md) only when installing or diagnosing discovery.

## Deliver the result

Stop only when the files match the current target. Return the requested artifact plus enough completion information for the user to understand material changes, validation, and known limits. Do not suppress useful status merely to make the reply look clean. Keep the artifact itself in current-state language: do not call it a corrected, clean, concise, no-X, or final-state version. In the reply, mention removed history when the user asks for an audit trail or when the removal is materially relevant to scope, migration, safety, or compatibility.
